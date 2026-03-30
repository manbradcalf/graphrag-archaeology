"""Claude-based relationship extraction, guided by the SHACL schema.

Extracts typed relationships between known entities from document sections.
Each section's text is sent to Claude along with the entity registry and the
valid SHACL relationship types + constraints. Claude returns structured JSON
which is validated against the schema before being accepted.

Uses the same async patterns as the LLM cleanup module: AsyncAnthropic client,
semaphore for concurrency control, exponential-backoff retry.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from .ner import ExtractedEntity

import anthropic

from src.config import ANTHROPIC_API_KEY, NER_MODEL
from src.extract.sectioning import split_by_pages
from src.schema import (
    ENTITY_TYPES,
    RELATIONSHIP_CONSTRAINTS,
    RELATIONSHIP_DISPLAY_LABELS,
    RELATIONSHIP_TYPES,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Throttle — prevents 429s on tight rate limits
# ---------------------------------------------------------------------------
MAX_REQUESTS_PER_MINUTE = 3


class ThrottledClient:
    """Wraps AsyncAnthropic with token-bucket throttle."""

    def __init__(
        self, client: anthropic.AsyncAnthropic, rpm: int = MAX_REQUESTS_PER_MINUTE
    ):
        self._client = client
        self._semaphore = asyncio.Semaphore(1)
        self._min_interval = 60.0 / rpm
        self._last_request = 0.0

    async def create(self, **kwargs):
        async with self._semaphore:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_request)
            if wait > 0:
                logger.debug("Throttling: waiting %.1fs before next API call", wait)
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()
            return await self._client.messages.create(**kwargs)


# Relationship types that map to node properties rather than graph edges.
# These use free-text targets (e.g., "chert", "projectile point") and do not
# require a matching entity in the registry.
_PROPERTY_RELATION_TYPES = {"P45_CONSISTS_OF", "P101_HAD_AS_GENERAL_USE"}

# RAG-infrastructure types — not extracted from text.
_INFRA_RELATION_TYPES = {"MENTIONS", "FROM_DOCUMENT"}

# Extraction-eligible relationship types: everything except infra types.
EXTRACTABLE_RELATION_TYPES = [
    rt for rt in RELATIONSHIP_TYPES if rt not in _INFRA_RELATION_TYPES
]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ExtractedRelation:
    """A single relationship extracted from a document section."""

    head_name: str  # source entity name (must match an extracted entity)
    head_type: str  # source entity Neo4j label
    relation_type: str  # relationship type from RELATIONSHIP_TYPES
    tail_name: str  # target entity name
    tail_type: str  # target entity Neo4j label
    source_section: str  # which section this was extracted from
    confidence: float  # 0.0-1.0


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _build_constraint_description() -> str:
    """Build a human-readable description of valid relationship constraints."""
    lines: list[str] = []
    for rt in EXTRACTABLE_RELATION_TYPES:
        constraint = RELATIONSHIP_CONSTRAINTS.get(rt)
        if not constraint:
            continue
        sources = ", ".join(constraint["source"]) if constraint["source"] else "*"
        targets = (
            ", ".join(constraint["target"])
            if constraint["target"]
            else "(free text value)"
        )
        display = RELATIONSHIP_DISPLAY_LABELS.get(rt, rt)
        lines.append(f"  {rt}  ({display})")
        lines.append(f"    Source types: {sources}")
        lines.append(f"    Target types: {targets}")
    return "\n".join(lines)


def _build_entity_list(entity_names: list[str]) -> str:
    """Format entity names as a bulleted list for the prompt."""
    if not entity_names:
        return "  (no entities provided)"
    return "\n".join(f"  - {name}" for name in sorted(entity_names))


_SYSTEM_PROMPT = """\
You are an expert in archaeological and historical relationship extraction. \
Your task is to identify typed relationships between known entities in a text \
passage about Virginia archaeology and Native peoples.

You MUST follow these rules:
1. Only extract relationships that are explicitly stated or strongly implied \
by the text. Do NOT infer relationships not supported by the text.
2. Every relationship must use one of the valid relationship types listed below.
3. Head and tail entity types must match the source/target constraints for the \
relationship type.
4. Head entities must come from the provided entity list. Tail entities should \
also come from the entity list when possible, but for property-type relationships \
(P45_CONSISTS_OF, P101_HAD_AS_GENERAL_USE) the tail can be a free-text value.
5. Return valid JSON only — no markdown fences, no commentary.
6. Assign a confidence score (0.0-1.0) to each relationship:
   - 1.0 = explicitly stated ("The Powhatan lived along the James River")
   - 0.7-0.9 = strongly implied by context
   - 0.5-0.6 = reasonably inferred but not directly stated
   - Below 0.5 = do not include"""

_USER_PROMPT_TEMPLATE = """\
Extract relationships from the following text section.

## Valid Relationship Types and Constraints

{constraints}

## Valid Entity Types

{entity_types}

## Known Entities (from prior NER step)

{entity_list}

## Text Section

{section_text}

## Instructions

Return a JSON array of relationship objects. Each object must have:
- "head_name": source entity name (from the known entities list)
- "head_type": Neo4j label of the source entity (from valid entity types)
- "relation_type": one of the valid relationship types above
- "tail_name": target entity name (from known entities, or free text for property relations)
- "tail_type": Neo4j label of the target entity (from valid entity types, or empty string for property relations)
- "confidence": float 0.0-1.0

Return an empty array [] if no valid relationships are found.
Return ONLY the JSON array — no explanation, no markdown fences."""


def _build_user_prompt(
    section_text: str,
    entity_names: list[str],
) -> str:
    """Assemble the user prompt for a single section."""
    entity_type_lines = "\n".join(
        f"  {label}: {desc}" for label, desc in ENTITY_TYPES.items()
    )
    return _USER_PROMPT_TEMPLATE.format(
        constraints=_build_constraint_description(),
        entity_types=entity_type_lines,
        entity_list=_build_entity_list(entity_names),
        section_text=section_text,
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_relation(
    raw: dict, entity_name_set: set[str]
) -> ExtractedRelation | None:
    """Validate a single raw relation dict against the SHACL constraints.

    Returns an ExtractedRelation if valid, None otherwise.
    """
    try:
        head_name = str(raw.get("head_name", "")).strip()
        head_type = str(raw.get("head_type", "")).strip()
        relation_type = str(raw.get("relation_type", "")).strip()
        tail_name = str(raw.get("tail_name", "")).strip()
        tail_type = str(raw.get("tail_type", "")).strip()
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        logger.debug("Skipping relation with unparseable fields: %s", raw)
        return None

    # Must have head and tail names
    if not head_name or not tail_name:
        logger.debug("Skipping relation with missing head/tail name: %s", raw)
        return None

    # Relation type must be extractable
    if relation_type not in EXTRACTABLE_RELATION_TYPES:
        logger.debug("Skipping relation with invalid type %r", relation_type)
        return None

    # Confidence floor
    if confidence < 0.5:
        logger.debug(
            "Skipping low-confidence relation (%.2f): %s -> %s",
            confidence,
            head_name,
            tail_name,
        )
        return None

    # Validate head type against constraints
    constraint = RELATIONSHIP_CONSTRAINTS.get(relation_type)
    if constraint:
        if head_type not in constraint["source"]:
            logger.debug(
                "Head type %r not valid for %s (expected %s)",
                head_type,
                relation_type,
                constraint["source"],
            )
            return None

        # For property relations, target type validation is relaxed
        if relation_type not in _PROPERTY_RELATION_TYPES:
            if constraint["target"] and tail_type not in constraint["target"]:
                logger.debug(
                    "Tail type %r not valid for %s (expected %s)",
                    tail_type,
                    relation_type,
                    constraint["target"],
                )
                return None

    # Head should be a known entity
    if head_name not in entity_name_set:
        # Try case-insensitive match
        match = next(
            (n for n in entity_name_set if n.lower() == head_name.lower()),
            None,
        )
        if match:
            head_name = match
        else:
            logger.debug("Head entity %r not in entity registry", head_name)
            return None

    # Tail should be known for non-property relations
    if relation_type not in _PROPERTY_RELATION_TYPES:
        if tail_name not in entity_name_set:
            match = next(
                (n for n in entity_name_set if n.lower() == tail_name.lower()),
                None,
            )
            if match:
                tail_name = match
            else:
                logger.debug("Tail entity %r not in entity registry", tail_name)
                return None

    return ExtractedRelation(
        head_name=head_name,
        head_type=head_type,
        relation_type=relation_type,
        tail_name=tail_name,
        tail_type=tail_type,
        source_section="",  # filled by caller
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Section-level extraction
# ---------------------------------------------------------------------------


async def extract_relations_from_section(
    client: ThrottledClient,
    section_text: str,
    entity_names: list[str],
    section_id: str,
    model: str,
    semaphore: asyncio.Semaphore | None = None,
) -> list[ExtractedRelation]:
    """Extract relationships from a single document section.

    Args:
        client: Anthropic async client.
        section_text: The section text to extract from.
        entity_names: Known entity names from the NER step.
        section_id: Identifier for this section (for provenance).
        model: Anthropic model name.
        semaphore: Optional concurrency limiter.

    Returns:
        List of validated ExtractedRelation objects.
    """
    user_prompt = _build_user_prompt(section_text, entity_names)
    entity_name_set = set(entity_names)

    async def _call() -> list[ExtractedRelation]:
        for attempt in range(3):
            try:
                response = await client.create(
                    model=model,
                    max_tokens=4096,
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                result_text = response.content[0].text.strip()

                # Strip markdown code fences if the model wraps output
                if result_text.startswith("```"):
                    lines = result_text.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip().startswith("```"):
                        lines = lines[:-1]
                    result_text = "\n".join(lines)

                raw_relations = json.loads(result_text)
                if not isinstance(raw_relations, list):
                    logger.warning(
                        "Section %s: expected JSON array, got %s",
                        section_id,
                        type(raw_relations).__name__,
                    )
                    return []

                relations: list[ExtractedRelation] = []
                for raw in raw_relations:
                    rel = _validate_relation(raw, entity_name_set)
                    if rel is not None:
                        rel.source_section = section_id
                        relations.append(rel)

                logger.info(
                    "Section %s: extracted %d relations (%d raw, %d valid)",
                    section_id,
                    len(relations),
                    len(raw_relations),
                    len(relations),
                )
                return relations

            except json.JSONDecodeError as exc:
                logger.warning(
                    "Section %s attempt %d: JSON parse error: %s",
                    section_id,
                    attempt + 1,
                    exc,
                )
                if attempt < 2:
                    await asyncio.sleep(2)
            except Exception as exc:
                logger.warning(
                    "Section %s attempt %d: %s",
                    section_id,
                    attempt + 1,
                    exc,
                )
                if attempt < 2:
                    await asyncio.sleep(2)
                else:
                    logger.error("Section %s: failed after 3 attempts", section_id)

        return []

    if semaphore is not None:
        async with semaphore:
            return await _call()
    return await _call()


# ---------------------------------------------------------------------------
# Document-level extraction
# ---------------------------------------------------------------------------


def _split_into_sections(
    text: str, min_chars: int = 3000, max_chars: int = 5000
) -> list[tuple[str, str]]:
    """Split markdown text into sections suitable for relation extraction.

    Splits on heading boundaries (## or ###). Merges small sections up to
    min_chars. Sections exceeding max_chars are kept whole — the LLM can
    handle them.

    Returns:
        List of (section_id_suffix, section_text) tuples.
    """
    import re

    heading_re = re.compile(r"^(#{2,3})\s+(.+)", re.MULTILINE)
    parts = heading_re.split(text)

    # Build (heading, body) pairs
    raw_sections: list[tuple[str, str]] = []
    preamble = parts[0].strip()
    if preamble:
        raw_sections.append(("preamble", preamble))

    i = 1
    while i + 2 < len(parts):
        title = parts[i + 1].strip()
        body = parts[i + 2].strip()
        section_text = f"## {title}\n\n{body}" if body else f"## {title}"
        raw_sections.append((title, section_text))
        i += 3

    # Merge small sections
    merged: list[tuple[str, str]] = []
    for title, body in raw_sections:
        if merged and len(merged[-1][1]) + len(body) < min_chars:
            prev_title, prev_body = merged[-1]
            merged[-1] = (prev_title, f"{prev_body}\n\n{body}")
        else:
            merged.append((title, body))

    # Generate stable section IDs
    result: list[tuple[str, str]] = []
    for idx, (title, body) in enumerate(merged):
        section_id = f"sec-{idx:03d}-{_slugify(title)}"
        result.append((section_id, body))

    return result


def _slugify(text: str, max_len: int = 40) -> str:
    """Create a URL-safe slug from text."""
    import re

    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:max_len]


async def extract_relations_from_document(
    md_path: Path,
    entities: list[ExtractedEntity],
    output_path: Path | None = None,
    model: str | None = None,
    max_concurrent: int = 2,
) -> list[ExtractedRelation]:
    """Extract relationships from an entire markdown document.

    Args:
        md_path: Path to the cleaned markdown file.
        entities: Entity list from the NER step. Each entity is a dict with
            at least a "name" key (and optionally "aliases").
        output_path: If provided, saves incrementally after each section.
        model: Anthropic model name. Defaults to NER_MODEL from config.
        max_concurrent: Maximum concurrent API requests.

    Returns:
        All validated ExtractedRelation objects from the document.
    """
    if model is None:
        model = NER_MODEL

    text = md_path.read_text(encoding="utf-8")
    doc_name = md_path.stem
    sections = split_by_pages(text, min_chars=3000)

    # Build entity name list including aliases
    entity_names: list[str] = []
    seen: set[str] = set()
    for ent in entities or []:
        name = ent.name
        logger.info("Entity is %s", name)
        if name and name not in seen:
            entity_names.append(name)
            seen.add(name)
        for alias in ent.aliases or []:
            if alias and alias not in seen:
                entity_names.append(alias)
                seen.add(alias)

    logger.info(
        "Document %s: %d sections, %d entity names",
        doc_name,
        len(sections),
        len(entity_names),
    )

    client = ThrottledClient(anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY))
    semaphore = asyncio.Semaphore(max_concurrent)
    start_time = time.time()
    all_relations: list[ExtractedRelation] = []

    for section_id, section_text in sections:
        batch = await extract_relations_from_section(
            client=client,
            section_text=section_text,
            entity_names=entity_names,
            section_id=f"{doc_name}/{section_id}",
            model=model,
            semaphore=semaphore,
        )
        all_relations.extend(batch)
        if output_path:
            _save_relations(all_relations, output_path)

    elapsed = time.time() - start_time
    logger.info(
        "Document %s: extracted %d relations in %.1fs",
        doc_name,
        len(all_relations),
        elapsed,
    )

    return all_relations


# ---------------------------------------------------------------------------
# Multi-document synchronous wrapper
# ---------------------------------------------------------------------------


def extract_all_relations(
    md_dir: Path,
    all_entities: dict[str, list[ExtractedEntity]],
    model: str | None = None,
) -> dict[str, list[ExtractedRelation]]:
    """Extract relationships from all markdown documents in a directory.

    This is the synchronous entry point that orchestrates async extraction
    and saves intermediate results.

    Args:
        md_dir: Directory containing cleaned markdown files.
        all_entities: Mapping of document stem name to entity list (from NER).
            Each entity is a dict with at least "name" and optionally "aliases".
        model: Anthropic model name override.

    Returns:
        Mapping of document stem name to list of ExtractedRelation objects.
    """
    output_dir = Path("data/relations")
    output_dir.mkdir(parents=True, exist_ok=True)

    md_files = sorted(md_dir.glob("*.md"))
    if not md_files:
        logger.warning("No markdown files found in %s", md_dir)
        return {}

    results: dict[str, list[ExtractedRelation]] = {}

    for md_path in md_files:
        doc_name = md_path.stem
        entities = all_entities.get(doc_name, [])

        if not entities:
            logger.warning(
                "No entities for document %s — skipping relation extraction",
                doc_name,
            )
            continue

        logger.info("Extracting relations from %s...", doc_name)
        logger.info("Model is %s", model)
        output_path = output_dir / f"{doc_name}.json"
        relations = asyncio.run(
            extract_relations_from_document(
                md_path, entities, output_path=output_path, model=model
            )
        )
        results[doc_name] = relations
        logger.info("Saved %d relations to %s", len(relations), output_path)

    return results


def _save_relations(
    relations: list[ExtractedRelation], path: Path, model: str | None = None
) -> None:
    """Serialize relations to JSON for intermediate storage."""
    from datetime import datetime, timezone

    output = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "model": model or NER_MODEL,
        "count": len(relations),
        "relations": [asdict(r) for r in relations],
    }
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")


def load_relations(path: Path) -> list[ExtractedRelation]:
    """Load previously saved relations from a JSON file."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    data = raw["relations"]
    return [
        ExtractedRelation(
            head_name=r["head_name"],
            head_type=r["head_type"],
            relation_type=r["relation_type"],
            tail_name=r["tail_name"],
            tail_type=r["tail_type"],
            source_section=r["source_section"],
            confidence=r["confidence"],
        )
        for r in data
    ]
