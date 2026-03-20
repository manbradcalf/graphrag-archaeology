"""Entity resolution and deduplication across documents.

Takes per-document entity lists from NER (Step 4) and produces a
deduplicated canonical entity registry with stable IDs, aliases, and
merged descriptions.

Resolution tiers:
  1. Exact match (case-insensitive, articles stripped)
  2. Fuzzy match within same entity type (SequenceMatcher ratio > 0.85)
  3. Ambiguous candidates flagged but not auto-merged (manual or LLM review)

No external dependencies beyond stdlib (difflib, re, json).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher
from pathlib import Path

from src.schema import ENTITY_TYPES

# ---------------------------------------------------------------------------
# Type prefix mapping: Neo4j label → slug prefix
# ---------------------------------------------------------------------------

_TYPE_PREFIX: dict[str, str] = {
    "E27_Site": "site",
    "E74_Group": "group",
    "E21_Person": "person",
    "E22_Man-Made_Object": "artifact",
    "E5_Event": "event",
    "E53_Place": "place",
    "E52_Time-Span": "period",
    "E31_Document": "doc",
    "S19_Encounter_Event": "discovery",
}

# Articles and short stopwords to strip when normalizing for matching
_STRIP_ARTICLES = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)

# Characters to replace when slugifying
_SLUG_INVALID = re.compile(r"[^a-z0-9]+")
_SLUG_MULTI_HYPHEN = re.compile(r"-{2,}")

# Fuzzy match threshold (SequenceMatcher ratio)
FUZZY_THRESHOLD: float = 0.85


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CanonicalEntity:
    """A deduplicated entity with a stable ID, canonical name, and aliases."""

    entity_id: str  # slugified: "{type_prefix}-{slugified-name}"
    name: str  # canonical (most common or longest form)
    entity_type: str  # Neo4j label, e.g. "E74_Group"
    aliases: list[str] = field(default_factory=list)
    description: str = ""  # merged description from all sources
    sources: list[str] = field(default_factory=list)  # document names


@dataclass
class AmbiguousCandidate:
    """A pair of entities that fuzzy-matched but below auto-merge confidence."""

    entity_a: str
    entity_b: str
    entity_type: str
    similarity: float
    reason: str = "Below auto-merge threshold; needs manual review"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize(name: str) -> str:
    """Lowercase, strip articles, collapse whitespace."""
    s = name.strip().lower()
    s = _STRIP_ARTICLES.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _slugify(name: str) -> str:
    """Convert a name to a URL/ID-safe slug."""
    s = name.strip().lower()
    s = _SLUG_INVALID.sub("-", s)
    s = _SLUG_MULTI_HYPHEN.sub("-", s)
    return s.strip("-")


def make_entity_id(entity_type: str, name: str) -> str:
    """Build a stable entity ID: ``{type_prefix}-{slugified-name}``.

    Examples
    --------
    >>> make_entity_id("E74_Group", "Powhatan Confederacy")
    'group-powhatan-confederacy'
    >>> make_entity_id("E27_Site", "Cactus Hill")
    'site-cactus-hill'
    """
    prefix = _TYPE_PREFIX.get(entity_type, entity_type.lower())
    slug = _slugify(name)
    return f"{prefix}-{slug}"


def _merge_descriptions(*descriptions: str) -> str:
    """Combine multiple descriptions, deduplicating sentences."""
    seen: set[str] = set()
    parts: list[str] = []
    for desc in descriptions:
        if not desc:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", desc.strip()):
            normalized = sentence.strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                parts.append(sentence.strip())
    return " ".join(parts)


def _pick_canonical_name(names: list[str]) -> str:
    """Choose the best canonical name from a list of variants.

    Prefers the longest form (usually most specific), breaking ties
    alphabetically for determinism.
    """
    return sorted(names, key=lambda n: (-len(n), n))[0]


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def resolve_entities(
    all_entities: dict[str, list[dict]],
) -> tuple[list[CanonicalEntity], list[AmbiguousCandidate]]:
    """Deduplicate entities across documents.

    Parameters
    ----------
    all_entities
        Mapping of ``{document_name: [entity_dict, ...]}`` where each
        entity dict has at minimum ``name``, ``type``, and optionally
        ``aliases``, ``description``, ``confidence``.

    Returns
    -------
    canonical_entities
        Deduplicated list of :class:`CanonicalEntity`.
    ambiguous
        Pairs that were close but not auto-merged, for manual review.
    """
    # Group raw entities by type first — resolution only happens within type
    by_type: dict[str, list[dict]] = {}
    for doc_name, entities in all_entities.items():
        for ent in entities:
            etype = ent.get("type", "")
            if etype not in by_type:
                by_type[etype] = []
            # Attach source document for provenance
            by_type[etype].append({**ent, "_source": doc_name})

    canonical: list[CanonicalEntity] = []
    ambiguous: list[AmbiguousCandidate] = []

    for etype, entities in by_type.items():
        type_canonical, type_ambiguous = _resolve_within_type(etype, entities)
        canonical.extend(type_canonical)
        ambiguous.extend(type_ambiguous)

    return canonical, ambiguous


def _resolve_within_type(
    entity_type: str,
    entities: list[dict],
) -> tuple[list[CanonicalEntity], list[AmbiguousCandidate]]:
    """Resolve entities of a single type using Tier 1 + Tier 2 matching."""

    # Each cluster is a list of raw entity dicts that refer to the same thing
    clusters: list[list[dict]] = []
    # Normalized name → cluster index for Tier 1 lookup
    norm_to_cluster: dict[str, int] = {}

    # --- Tier 1: Exact match (case-insensitive, articles stripped) ----------
    for ent in entities:
        names = [ent["name"]] + ent.get("aliases", [])
        matched_cluster: int | None = None

        for name in names:
            norm = _normalize(name)
            if norm in norm_to_cluster:
                matched_cluster = norm_to_cluster[norm]
                break

        if matched_cluster is not None:
            clusters[matched_cluster].append(ent)
            # Register any new normalized names from this entity
            for name in names:
                norm_to_cluster[_normalize(name)] = matched_cluster
        else:
            # Start a new cluster
            idx = len(clusters)
            clusters.append([ent])
            for name in names:
                norm_to_cluster[_normalize(name)] = idx

    # --- Tier 2: Fuzzy match between remaining clusters --------------------
    ambiguous: list[AmbiguousCandidate] = []
    merged: set[int] = set()  # cluster indices that got merged into another

    cluster_names: list[str] = []
    for cluster in clusters:
        # Use the canonical candidate name for fuzzy comparison
        all_names = []
        for ent in cluster:
            all_names.append(ent["name"])
            all_names.extend(ent.get("aliases", []))
        cluster_names.append(_pick_canonical_name(all_names))

    for i in range(len(clusters)):
        if i in merged:
            continue
        for j in range(i + 1, len(clusters)):
            if j in merged:
                continue

            ratio = SequenceMatcher(
                None,
                _normalize(cluster_names[i]),
                _normalize(cluster_names[j]),
            ).ratio()

            if ratio >= FUZZY_THRESHOLD:
                # Auto-merge: fold cluster j into cluster i
                clusters[i].extend(clusters[j])
                merged.add(j)
                # Update name mapping
                for ent in clusters[j]:
                    for name in [ent["name"]] + ent.get("aliases", []):
                        norm_to_cluster[_normalize(name)] = i
            elif ratio >= FUZZY_THRESHOLD - 0.10:
                # Close but not confident — flag for review (Tier 3)
                ambiguous.append(
                    AmbiguousCandidate(
                        entity_a=cluster_names[i],
                        entity_b=cluster_names[j],
                        entity_type=entity_type,
                        similarity=round(ratio, 3),
                    )
                )

    # --- Build CanonicalEntity from each surviving cluster -----------------
    canonical: list[CanonicalEntity] = []

    for i, cluster in enumerate(clusters):
        if i in merged:
            continue

        all_names: list[str] = []
        descriptions: list[str] = []
        sources: set[str] = set()

        for ent in cluster:
            all_names.append(ent["name"])
            all_names.extend(ent.get("aliases", []))
            if ent.get("description"):
                descriptions.append(ent["description"])
            if ent.get("_source"):
                sources.add(ent["_source"])

        canon_name = _pick_canonical_name(all_names)

        # Deduplicate aliases (case-insensitive), exclude canonical name
        seen_lower: set[str] = {canon_name.lower()}
        unique_aliases: list[str] = []
        for name in all_names:
            if name.lower() not in seen_lower:
                seen_lower.add(name.lower())
                unique_aliases.append(name)

        canonical.append(
            CanonicalEntity(
                entity_id=make_entity_id(entity_type, canon_name),
                name=canon_name,
                entity_type=entity_type,
                aliases=unique_aliases,
                description=_merge_descriptions(*descriptions),
                sources=sorted(sources),
            )
        )

    return canonical, ambiguous


# ---------------------------------------------------------------------------
# Alias map (for chunk-entity linking in Step 7)
# ---------------------------------------------------------------------------


def build_alias_map(entities: list[CanonicalEntity]) -> dict[str, str]:
    """Build a lookup from every known name/alias to its entity ID.

    Returns
    -------
    dict
        ``{lowercase_name_or_alias: entity_id}`` for all canonical names
        and aliases. Used by chunk-entity linking for string matching.
    """
    alias_map: dict[str, str] = {}
    for ent in entities:
        alias_map[ent.name.lower()] = ent.entity_id
        for alias in ent.aliases:
            key = alias.lower()
            # First entity to claim an alias wins; log collisions
            if key not in alias_map:
                alias_map[key] = ent.entity_id
    return alias_map


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save_entity_registry(
    entities: list[CanonicalEntity],
    output_path: Path,
    ambiguous: list[AmbiguousCandidate] | None = None,
) -> None:
    """Save the canonical entity list (and optional ambiguous pairs) to JSON.

    Parameters
    ----------
    entities
        Resolved canonical entities.
    output_path
        Path to write the JSON file.
    ambiguous
        Optional list of ambiguous candidate pairs flagged for review.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict = {
        "entity_count": len(entities),
        "entities": [asdict(e) for e in entities],
    }
    if ambiguous:
        payload["ambiguous_candidates"] = [asdict(a) for a in ambiguous]

    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def load_entity_registry(input_path: Path) -> list[CanonicalEntity]:
    """Load a previously saved entity registry from JSON.

    Parameters
    ----------
    input_path
        Path to the JSON file written by :func:`save_entity_registry`.

    Returns
    -------
    list[CanonicalEntity]
    """
    data = json.loads(input_path.read_text())
    return [
        CanonicalEntity(**ent)
        for ent in data["entities"]
    ]
