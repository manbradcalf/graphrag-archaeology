"""Claude-based Named Entity Recognition guided by the SHACL schema.

Extracts entities from cleaned markdown documents using Claude, with the
CIDOC-CRM entity types as extraction targets. Operates at section level
(not per-chunk) so the LLM has enough context for coreference resolution.

Usage:
    # Async — single document
    entities = await extract_entities_from_document(Path("data/md/doc.md"))

    # Sync — all documents in a directory
    all_entities = extract_all_entities(Path("data/md"))
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import anthropic

from src.config import ANTHROPIC_API_KEY, DATA_DIR, MD_DIR, NER_MODEL
from src.extract.sectioning import split_by_pages
from src.schema import ENTITY_TYPES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ExtractedEntity:
    """A single entity extracted from a document section."""

    name: str  # canonical name
    entity_type: str  # Neo4j label from ENTITY_TYPES (e.g. "E74_Group")
    aliases: list[str] = field(default_factory=list)  # alternative names/spellings
    description: str = ""  # brief description from source context
    source_section: str = ""  # section identifier this was extracted from
    confidence: float = 1.0  # 0.0-1.0

    def __post_init__(self) -> None:
        if self.entity_type not in ENTITY_TYPES:
            raise ValueError(
                f"Unknown entity type {self.entity_type!r}. "
                f"Valid types: {list(ENTITY_TYPES.keys())}"
            )
        self.confidence = max(0.0, min(1.0, self.confidence))


# ---------------------------------------------------------------------------
# Extractable entity types — the 7 types NER targets (not Document or
# DiscoveryEvent, which come from metadata and relationship extraction)
# ---------------------------------------------------------------------------

NER_ENTITY_TYPES: dict[str, str] = {
    k: v
    for k, v in ENTITY_TYPES.items()
    if k not in ("E31_Document", "S19_Encounter_Event")
}

# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert entity extraction system for Virginia archaeology and early American history. \
Extract ALL named entities from the provided text section, classifying each into one of the \
CIDOC-CRM entity types listed below.

## Entity Types

E27_Site — Archaeological Site
  Examples: Cactus Hill, Thunderbird Site, Williamsburg Colonial Site, Flint Run Complex

E74_Group — Cultural Group (tribe, nation, confederacy, or ethnic/cultural group)
  Examples: Powhatan Confederacy, Monacan, Siouan peoples, Iroquois, Shawnee, Tuscarora

E21_Person — Historical Figure (named individual)
  Examples: John Smith, Wahunsenacah, Samuel Kercheval, Thomas Jefferson

E22_Man-Made_Object — Artifact (tools, weapons, pottery, structures, or artifact types)
  Examples: Clovis point, ceramic vessel, projectile point, stone gorget, longhouse

E5_Event — Historical Event (battle, migration, treaty, encounter, settlement)
  Examples: Battle of Point Pleasant, Jamestown settlement, Bacon's Rebellion

E53_Place — Geographic Location (river, valley, mountain, region, county, town)
  Examples: Shenandoah Valley, James River, Chesapeake Bay, Blue Ridge Mountains, Augusta County

E52_Time-Span — Cultural or Chronological Period
  Examples: Paleoindian Period, Late Woodland Period, Contact Era, Archaic Period, ca. 1200-1600 CE

## Instructions

1. Extract EVERY named entity, even those mentioned only once. Be thorough — do not skip minor references.
2. For each entity, provide:
   - "name": The canonical name (use the most complete form found in the text)
   - "type": One of the entity type codes above (e.g. "E27_Site", "E74_Group")
   - "aliases": List of alternative names, abbreviations, or spellings found in the text
   - "description": A brief (1-2 sentence) description based on what the text says about this entity
   - "confidence": A float 0.0-1.0 indicating extraction confidence (1.0 = clearly named, 0.5 = inferred from context)
3. For the 1833 Kercheval text, OCR artifacts may mangle names — extract your best guess and note uncertainty via lower confidence.
4. If a generic term refers to a specific entity (e.g. "the confederacy" clearly referring to the Powhatan Confederacy), extract it with the specific canonical name.
5. Do NOT extract:
   - Generic concepts (e.g. "agriculture", "warfare") unless they name a specific entity
   - Modern references (e.g. "the University of Virginia") unless historically relevant
   - The document or publication itself

Respond with JSON only."""

USER_PROMPT_TEMPLATE = """\
Extract all named entities from this text section. Return a JSON array of objects, \
each with keys: "name", "type", "aliases", "description", "confidence".

Section: {section_id}

Text:
{section_text}"""

# ---------------------------------------------------------------------------
# Section splitting
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,4})\s+", re.MULTILINE)


def split_into_sections(
    text: str,
    min_chars: int = 1000,
    max_chars: int = 5000,
    target_chars: int = 3500,
) -> list[tuple[str, str]]:
    """Split markdown text into sections for NER processing.

    Uses heading boundaries as primary split points. Merges small sections
    with the next one and splits oversized sections at paragraph boundaries.

    Args:
        text: Full markdown document text.
        min_chars: Minimum section size — smaller sections get merged forward.
        max_chars: Maximum section size — larger sections get split.
        target_chars: Target size when splitting oversized sections.

    Returns:
        List of (section_id, section_text) tuples. section_id is derived
        from the heading text or a positional index.
    """
    # Find all heading positions
    headings: list[tuple[int, str]] = []
    for m in _HEADING_RE.finditer(text):
        line_end = text.find("\n", m.start())
        if line_end == -1:
            line_end = len(text)
        heading_text = text[m.start() : line_end].strip().lstrip("#").strip()
        headings.append((m.start(), heading_text))

    if not headings:
        # No headings — split at paragraph boundaries
        return _split_by_paragraphs(text, "section", target_chars, max_chars)

    # Build raw sections from heading boundaries
    raw_sections: list[tuple[str, str]] = []
    for i, (pos, heading) in enumerate(headings):
        end = headings[i + 1][0] if i + 1 < len(headings) else len(text)
        section_text = text[pos:end].strip()
        if section_text:
            raw_sections.append((heading, section_text))

    # Include any text before the first heading
    if headings[0][0] > 0:
        preamble = text[: headings[0][0]].strip()
        if preamble:
            raw_sections.insert(0, ("preamble", preamble))

    # Merge small sections, split large ones
    merged: list[tuple[str, str]] = []
    buffer_id = ""
    buffer_text = ""

    for section_id, section_text in raw_sections:
        if buffer_text:
            combined = buffer_text + "\n\n" + section_text
            if len(combined) <= max_chars:
                buffer_text = combined
                # Keep the first heading as the section ID
                continue
            else:
                # Flush buffer as its own section
                merged.append((buffer_id, buffer_text))
                buffer_id = ""
                buffer_text = ""

        if len(section_text) < min_chars:
            buffer_id = section_id
            buffer_text = section_text
        elif len(section_text) > max_chars:
            # Split oversized section at paragraph boundaries
            subsections = _split_by_paragraphs(
                section_text, section_id, target_chars, max_chars
            )
            merged.extend(subsections)
        else:
            merged.append((section_id, section_text))

    # Flush any remaining buffer
    if buffer_text:
        if merged:
            # Append to last section if it won't exceed max
            last_id, last_text = merged[-1]
            combined = last_text + "\n\n" + buffer_text
            if len(combined) <= max_chars:
                merged[-1] = (last_id, combined)
            else:
                merged.append((buffer_id, buffer_text))
        else:
            merged.append((buffer_id, buffer_text))

    return merged


def _split_by_paragraphs(
    text: str,
    base_id: str,
    target_chars: int,
    max_chars: int,
) -> list[tuple[str, str]]:
    """Split text into sections at paragraph boundaries."""
    paragraphs = re.split(r"\n\n+", text)
    sections: list[tuple[str, str]] = []
    current: list[str] = []
    current_len = 0
    idx = 0

    for para in paragraphs:
        para_len = len(para)
        if current and current_len + para_len > target_chars:
            sections.append((f"{base_id}_part{idx}", "\n\n".join(current)))
            idx += 1
            current = []
            current_len = 0
        current.append(para)
        current_len += para_len + 2  # +2 for the \n\n separator

    if current:
        sections.append((f"{base_id}_part{idx}", "\n\n".join(current)))

    return sections


# ---------------------------------------------------------------------------
# Single-section extraction
# ---------------------------------------------------------------------------


async def extract_entities_from_section(
    client: anthropic.AsyncAnthropic,
    section_text: str,
    section_id: str,
    model: str,
    semaphore: asyncio.Semaphore | None = None,
) -> list[ExtractedEntity]:
    """Extract entities from a single document section using Claude.

    Args:
        client: Async Anthropic client.
        section_text: The text of the section to process.
        section_id: Identifier for this section (used in source_section).
        model: Anthropic model name (e.g. "claude-sonnet-4-20250514").
        semaphore: Optional semaphore for rate limiting.

    Returns:
        List of ExtractedEntity objects found in the section.
    """
    if not section_text.strip():
        return []

    user_message = USER_PROMPT_TEMPLATE.format(
        section_id=section_id,
        section_text=section_text,
    )

    async def _call() -> list[ExtractedEntity]:
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_message},
                # JSON prefill trick — start assistant response with [
                # to ensure Claude returns a JSON array
                {"role": "assistant", "content": "["},
            ],
        )
        raw_text = "[" + response.content[0].text
        # Strip trailing markdown fences if present
        raw_text = raw_text.strip()
        if raw_text.endswith("```"):
            raw_text = raw_text[: raw_text.rfind("```")].strip()

        return _parse_entities(raw_text, section_id)

    if semaphore is not None:
        async with semaphore:
            return await _call_with_retries(_call, section_id)
    else:
        return await _call_with_retries(_call, section_id)


async def _call_with_retries(
    call_fn,
    section_id: str,
    max_retries: int = 3,
) -> list[ExtractedEntity]:
    """Execute an async call with exponential backoff retries."""
    for attempt in range(max_retries):
        try:
            return await call_fn()
        except anthropic.RateLimitError:
            wait = 2 ** (attempt + 1)
            logger.warning(
                "Rate limited on section %r, waiting %ds...", section_id, wait
            )
            await asyncio.sleep(wait)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(
                "Parse error on section %r (attempt %d/%d): %s",
                section_id,
                attempt + 1,
                max_retries,
                e,
            )
            if attempt == max_retries - 1:
                logger.error(
                    "Failed to parse entities from section %r after %d attempts",
                    section_id,
                    max_retries,
                )
                return []
            await asyncio.sleep(1)
        except Exception as e:
            logger.warning(
                "Error on section %r (attempt %d/%d): %s",
                section_id,
                attempt + 1,
                max_retries,
                e,
            )
            if attempt == max_retries - 1:
                logger.error(
                    "Failed section %r after %d attempts: %s",
                    section_id,
                    max_retries,
                    e,
                )
                return []
            await asyncio.sleep(2**attempt)

    return []


def _parse_entities(raw_json: str, section_id: str) -> list[ExtractedEntity]:
    """Parse Claude's JSON response into ExtractedEntity objects.

    Handles minor JSON quirks: trailing commas, incomplete arrays.
    """
    # Attempt to fix trailing commas before closing brackets
    cleaned = re.sub(r",\s*([}\]])", r"\1", raw_json)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find the array within the response
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if match:
            data = json.loads(match.group())
        else:
            raise

    if not isinstance(data, list):
        data = [data]

    entities: list[ExtractedEntity] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        entity_type = item.get("type", "")
        # Normalize common variations
        if entity_type not in ENTITY_TYPES:
            # Try matching without prefix (e.g. "Site" -> "E27_Site")
            for key, label in ENTITY_TYPES.items():
                if entity_type == label or entity_type == key.split("_", 1)[-1]:
                    entity_type = key
                    break
            else:
                logger.warning(
                    "Skipping entity with unknown type %r: %s",
                    entity_type,
                    item.get("name", "?"),
                )
                continue

        # Skip Document and DiscoveryEvent — those come from other steps
        if entity_type in ("E31_Document", "S19_Encounter_Event"):
            continue

        name = item.get("name", "").strip()
        if not name:
            continue

        entities.append(
            ExtractedEntity(
                name=name,
                entity_type=entity_type,
                aliases=[a.strip() for a in item.get("aliases", []) if a.strip()],
                description=item.get("description", "").strip(),
                source_section=section_id,
                confidence=float(item.get("confidence", 1.0)),
            )
        )

    return entities


# ---------------------------------------------------------------------------
# Document-level extraction
# ---------------------------------------------------------------------------


async def extract_entities_from_document(
    md_path: Path,
    model: str | None = None,
    max_concurrent: int = 5,
) -> list[ExtractedEntity]:
    """Extract entities from a full markdown document.

    Splits the document into sections at heading boundaries and processes
    each section concurrently with a rate-limiting semaphore.

    Args:
        md_path: Path to the cleaned markdown file.
        model: Anthropic model name. Defaults to config.NER_MODEL.
        max_concurrent: Maximum concurrent API requests.

    Returns:
        List of all extracted entities across all sections (not yet deduped).
    """
    model = model or NER_MODEL
    text = md_path.read_text(encoding="utf-8")
    doc_name = md_path.stem

    sections = split_by_pages(text)
    logger.info(
        "Extracting entities from %s: %d sections, %d chars",
        doc_name,
        len(sections),
        len(text),
    )

    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    semaphore = asyncio.Semaphore(max_concurrent)

    tasks = [
        extract_entities_from_section(
            client=client,
            section_text=section_text,
            section_id=f"{doc_name}/{section_id}",
            model=model,
            semaphore=semaphore,
        )
        for section_id, section_text in sections
    ]

    start_time = time.time()
    results = await asyncio.gather(*tasks)
    elapsed = time.time() - start_time

    all_entities: list[ExtractedEntity] = []
    for section_entities in results:
        all_entities.extend(section_entities)

    logger.info(
        "Extracted %d entities from %s in %.1fs (%d sections)",
        len(all_entities),
        doc_name,
        elapsed,
        len(sections),
    )

    return all_entities


# ---------------------------------------------------------------------------
# Batch extraction — all documents
# ---------------------------------------------------------------------------


def _save_entities(
    entities: list[ExtractedEntity],
    doc_name: str,
    output_dir: Path,
) -> Path:
    """Save extracted entities to a JSON file for intermediate inspection."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{doc_name}.json"
    data = [asdict(e) for e in entities]
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Saved %d entities to %s", len(entities), output_path)
    return output_path


def _load_entities(path: Path) -> list[ExtractedEntity]:
    """Load previously extracted entities from a JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        ExtractedEntity(
            name=item["name"],
            entity_type=item["entity_type"],
            aliases=item.get("aliases", []),
            description=item.get("description", ""),
            source_section=item.get("source_section", ""),
            confidence=item.get("confidence", 1.0),
        )
        for item in data
    ]


def extract_all_entities(
    md_dir: Path | None = None,
    model: str | None = None,
    max_concurrent: int = 5,
    force: bool = False,
) -> dict[str, list[ExtractedEntity]]:
    """Extract entities from all markdown documents in a directory.

    Synchronous wrapper around the async extraction pipeline. Saves
    intermediate results to data/entities/{doc_name}.json after each
    document so partial runs can be resumed.

    Args:
        md_dir: Directory containing cleaned .md files. Defaults to config.MD_DIR.
        model: Anthropic model name. Defaults to config.NER_MODEL.
        max_concurrent: Maximum concurrent API requests per document.
        force: If True, re-extract even if a cached JSON file exists.

    Returns:
        Dict mapping document name to list of extracted entities.
    """
    md_dir = md_dir or MD_DIR
    entities_dir = DATA_DIR / "entities"

    md_files = sorted(md_dir.glob("*.md"))
    if not md_files:
        logger.warning("No .md files found in %s", md_dir)
        return {}

    logger.info("Found %d markdown files in %s", len(md_files), md_dir)

    results: dict[str, list[ExtractedEntity]] = {}

    for md_path in md_files:
        doc_name = md_path.stem
        cached_path = entities_dir / f"{doc_name}.json"

        if not force and cached_path.exists():
            logger.info("Loading cached entities for %s", doc_name)
            results[doc_name] = _load_entities(cached_path)
            continue

        logger.info("Extracting entities from %s ...", doc_name)
        entities = asyncio.run(
            extract_entities_from_document(
                md_path,
                model=model,
                max_concurrent=max_concurrent,
            )
        )

        _save_entities(entities, doc_name, entities_dir)
        results[doc_name] = entities

    total = sum(len(v) for v in results.values())
    logger.info(
        "Entity extraction complete: %d entities from %d documents",
        total,
        len(results),
    )

    return results
