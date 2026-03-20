"""Neo4j graph loader for the Virginia archaeology knowledge graph.

Loads canonical entities, relationships, and text chunks into Neo4j.
Uses MERGE for idempotent entity loading and UNWIND for batch operations.
Property names match SHACL/graphlint expectations (prefLabel, P3_has_note, etc.).

Steps 7-8 of the pipeline:
  - Entity and relationship loading
  - Chunk node creation
  - Chunk-entity linking (MENTIONS)
  - Chunk-document linking (FROM_DOCUMENT)
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import asdict

import neo4j

from src.config import NEO4J_DATABASE, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USERNAME
from src.extract.chunker import TextChunk
from src.extract.relations import ExtractedRelation
from src.extract.resolve import CanonicalEntity
from src.schema import ENTITY_TYPES

logger = logging.getLogger(__name__)

# Relationship types that should be stored as node properties rather than edges.
_PROPERTY_RELATION_TYPES = {"P45_CONSISTS_OF", "P101_HAD_AS_GENERAL_USE"}

# Map property-type relations to the Neo4j property name (matching SHACL).
_PROPERTY_RELATION_TO_PROP = {
    "P45_CONSISTS_OF": "P45_consists_of",
    "P101_HAD_AS_GENERAL_USE": "P101_had_as_general_use",
}

# Neo4j labels that contain hyphens and need backtick escaping.
_LABELS_NEEDING_ESCAPE = {"E22_Man-Made_Object", "E52_Time-Span"}


def _escape_label(label: str) -> str:
    """Backtick-escape a Neo4j label if it contains special characters."""
    if label in _LABELS_NEEDING_ESCAPE or "-" in label:
        return f"`{label}`"
    return label


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def get_driver() -> neo4j.Driver:
    """Create a Neo4j driver from config values.

    Returns a driver instance. Caller is responsible for closing it.
    """
    driver = neo4j.GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
    )
    # Verify connectivity
    driver.verify_connectivity()
    logger.info("Connected to Neo4j at %s", NEO4J_URI)
    return driver


# ---------------------------------------------------------------------------
# Clear database
# ---------------------------------------------------------------------------


def clear_database(driver: neo4j.Driver) -> None:
    """Delete all nodes and relationships. Asks for confirmation via stdin."""
    confirm = input(
        "This will DELETE ALL nodes and relationships in the database. "
        "Type 'yes' to confirm: "
    )
    if confirm.strip().lower() != "yes":
        print("Aborted.")
        return

    with driver.session(database=NEO4J_DATABASE) as session:
        # Use CALL {} IN TRANSACTIONS for large databases
        result = session.run(
            "MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS"
        )
        summary = result.consume()
        logger.info("Database cleared.")
        print("Database cleared.")


# ---------------------------------------------------------------------------
# Entity loading
# ---------------------------------------------------------------------------


def load_entities(driver: neo4j.Driver, entities: list[CanonicalEntity]) -> None:
    """MERGE entity nodes into Neo4j, batched by entity type.

    Each entity gets:
      - Neo4j label from entity_type (e.g., E27_Site, E74_Group)
      - Properties: entity_id, prefLabel, P3_has_note, aliases
      - P2_has_type where applicable (Groups, Events, Places, Documents)

    Uses UNWIND for batch loading. MERGE on entity_id for idempotency.
    """
    # Group entities by type for separate Cypher statements (labels can't be
    # parameterized in Cypher, so we generate one statement per entity type).
    by_type: dict[str, list[dict]] = defaultdict(list)
    for ent in entities:
        props = {
            "entity_id": ent.entity_id,
            "prefLabel": ent.name,
            "P3_has_note": ent.description or "",
            "aliases": ent.aliases or [],
        }
        by_type[ent.entity_type].append(props)

    with driver.session(database=NEO4J_DATABASE) as session:
        for entity_type, batch in by_type.items():
            label = _escape_label(entity_type)
            cypher = (
                f"UNWIND $batch AS props "
                f"MERGE (n:{label} {{entity_id: props.entity_id}}) "
                f"SET n.prefLabel = props.prefLabel, "
                f"    n.P3_has_note = props.P3_has_note, "
                f"    n.aliases = props.aliases"
            )
            session.run(cypher, batch=batch)
            logger.info(
                "Loaded %d %s entities", len(batch), entity_type
            )

    # Create a uniqueness constraint on entity_id for each domain label
    _ensure_entity_constraints(driver)
    logger.info("Loaded %d entities total", len(entities))


def _ensure_entity_constraints(driver: neo4j.Driver) -> None:
    """Create uniqueness constraints on entity_id for each entity type label."""
    with driver.session(database=NEO4J_DATABASE) as session:
        for label in ENTITY_TYPES:
            constraint_name = f"unique_{label.lower().replace('-', '_')}_entity_id"
            escaped = _escape_label(label)
            try:
                session.run(
                    f"CREATE CONSTRAINT {constraint_name} IF NOT EXISTS "
                    f"FOR (n:{escaped}) REQUIRE n.entity_id IS UNIQUE"
                )
            except Exception as exc:
                # Constraint may already exist or label may have issues
                logger.debug(
                    "Constraint creation for %s: %s", label, exc
                )


# ---------------------------------------------------------------------------
# Relationship loading
# ---------------------------------------------------------------------------


def load_relationships(
    driver: neo4j.Driver,
    relations: list[ExtractedRelation],
    entities: list[CanonicalEntity],
) -> None:
    """Create relationships between entity nodes.

    - Matches source/target entities by name (case-insensitive) against
      the canonical entity list to resolve entity_id values.
    - Property-type relations (P45_CONSISTS_OF, P101_HAD_AS_GENERAL_USE) are
      set as node properties instead of creating edges.
    - Non-property relations are batched by relationship type for efficient
      loading via UNWIND.
    """
    # Build name -> entity_id lookup (case-insensitive)
    name_to_id: dict[str, str] = {}
    id_to_type: dict[str, str] = {}
    for ent in entities:
        name_to_id[ent.name.lower()] = ent.entity_id
        id_to_type[ent.entity_id] = ent.entity_type
        for alias in ent.aliases:
            if alias.lower() not in name_to_id:
                name_to_id[alias.lower()] = ent.entity_id

    # Separate property-type vs. edge-type relations
    property_updates: dict[str, list[tuple[str, str]]] = defaultdict(list)
    edge_batches: dict[str, list[dict]] = defaultdict(list)

    skipped = 0
    for rel in relations:
        head_id = name_to_id.get(rel.head_name.lower())
        if not head_id:
            logger.debug("Skipping relation: head %r not found", rel.head_name)
            skipped += 1
            continue

        if rel.relation_type in _PROPERTY_RELATION_TYPES:
            prop_name = _PROPERTY_RELATION_TO_PROP[rel.relation_type]
            property_updates[prop_name].append((head_id, rel.tail_name))
            continue

        tail_id = name_to_id.get(rel.tail_name.lower())
        if not tail_id:
            logger.debug("Skipping relation: tail %r not found", rel.tail_name)
            skipped += 1
            continue

        edge_batches[rel.relation_type].append({
            "head_id": head_id,
            "tail_id": tail_id,
            "confidence": rel.confidence,
            "source_section": rel.source_section,
        })

    # --- Apply property-type relations as node properties ---
    with driver.session(database=NEO4J_DATABASE) as session:
        for prop_name, updates in property_updates.items():
            for entity_id, value in updates:
                # Append to a list property (artifacts can have multiple materials)
                session.run(
                    "MATCH (n {entity_id: $eid}) "
                    "SET n.`" + prop_name + "` = "
                    "CASE WHEN n.`" + prop_name + "` IS NULL THEN $val "
                    "ELSE n.`" + prop_name + "` + ', ' + $val END",
                    eid=entity_id,
                    val=value,
                )
            logger.info("Set %d %s property values", len(updates), prop_name)

    # --- Create edge-type relationships ---
    # Each relationship type gets its own UNWIND statement since relationship
    # types cannot be parameterized in standard Cypher.
    with driver.session(database=NEO4J_DATABASE) as session:
        for rel_type, batch in edge_batches.items():
            # Relationship types are uppercase identifiers from our schema,
            # safe for direct interpolation (validated against RELATIONSHIP_TYPES).
            cypher = (
                "UNWIND $batch AS r "
                "MATCH (h {entity_id: r.head_id}) "
                "MATCH (t {entity_id: r.tail_id}) "
                f"MERGE (h)-[rel:{rel_type}]->(t) "
                "SET rel.confidence = r.confidence, "
                "    rel.source_section = r.source_section"
            )
            session.run(cypher, batch=batch)
            logger.info(
                "Created %d %s relationships", len(batch), rel_type
            )

    total_edges = sum(len(b) for b in edge_batches.values())
    total_props = sum(len(u) for u in property_updates.values())
    logger.info(
        "Loaded %d edge relationships, %d property values (%d skipped)",
        total_edges,
        total_props,
        skipped,
    )


# ---------------------------------------------------------------------------
# Chunk loading
# ---------------------------------------------------------------------------


def load_chunks(driver: neo4j.Driver, chunks: list[TextChunk]) -> None:
    """CREATE Chunk nodes in Neo4j.

    Properties: chunk_id, text, document_name, section_heading, chunk_index.
    No embedding yet (that is Step 9).
    """
    batch = [
        {
            "chunk_id": c.chunk_id,
            "text": c.text,
            "document_name": c.document_name,
            "section_heading": c.section_heading,
            "chunk_index": c.chunk_index,
        }
        for c in chunks
    ]

    with driver.session(database=NEO4J_DATABASE) as session:
        session.run(
            "UNWIND $batch AS props "
            "MERGE (c:Chunk {chunk_id: props.chunk_id}) "
            "SET c.text = props.text, "
            "    c.document_name = props.document_name, "
            "    c.section_heading = props.section_heading, "
            "    c.chunk_index = props.chunk_index",
            batch=batch,
        )

    logger.info("Loaded %d Chunk nodes", len(batch))


# ---------------------------------------------------------------------------
# Chunk-entity linking (MENTIONS)
# ---------------------------------------------------------------------------


def link_chunks_to_entities(
    driver: neo4j.Driver,
    chunks: list[TextChunk],
    alias_map: dict[str, str],
) -> None:
    """Create MENTIONS relationships from Chunk nodes to entity nodes.

    For each chunk, checks which canonical entity names/aliases appear in
    the chunk text (case-insensitive string matching). Creates
    ``(Chunk)-[:MENTIONS]->(entity)`` for each match.

    Args:
        driver: Neo4j driver.
        chunks: Text chunks to link.
        alias_map: Mapping of ``{lowercase_alias: entity_id}`` from
            :func:`src.extract.resolve.build_alias_map`.
    """
    # Sort aliases longest-first so longer names match before shorter substrings.
    # Pre-compile a regex pattern per alias for word-boundary matching.
    sorted_aliases = sorted(alias_map.keys(), key=len, reverse=True)

    # Build regex patterns — use word boundaries to avoid partial matches
    # (e.g., "James" shouldn't match inside "Jamestown" unless "Jamestown"
    # is also an alias). Cache compiled patterns.
    alias_patterns: list[tuple[str, re.Pattern[str], str]] = []
    for alias in sorted_aliases:
        # Skip very short aliases (1-2 chars) that would produce false positives
        if len(alias) <= 2:
            continue
        try:
            pattern = re.compile(r"\b" + re.escape(alias) + r"\b", re.IGNORECASE)
            alias_patterns.append((alias, pattern, alias_map[alias]))
        except re.error:
            logger.debug("Could not compile regex for alias: %r", alias)

    # Find mentions for each chunk
    mention_pairs: list[dict] = []
    seen: set[tuple[str, str]] = set()  # dedupe (chunk_id, entity_id)

    for chunk in chunks:
        text_lower = chunk.text.lower()
        for alias, pattern, entity_id in alias_patterns:
            # Quick pre-check before regex
            if alias not in text_lower:
                continue
            if pattern.search(chunk.text):
                key = (chunk.chunk_id, entity_id)
                if key not in seen:
                    seen.add(key)
                    mention_pairs.append({
                        "chunk_id": chunk.chunk_id,
                        "entity_id": entity_id,
                    })

    # Batch create MENTIONS relationships
    if mention_pairs:
        with driver.session(database=NEO4J_DATABASE) as session:
            session.run(
                "UNWIND $batch AS pair "
                "MATCH (c:Chunk {chunk_id: pair.chunk_id}) "
                "MATCH (e {entity_id: pair.entity_id}) "
                "MERGE (c)-[:MENTIONS]->(e)",
                batch=mention_pairs,
            )

    logger.info(
        "Created %d MENTIONS relationships across %d chunks",
        len(mention_pairs),
        len(chunks),
    )


# ---------------------------------------------------------------------------
# Chunk-document linking (FROM_DOCUMENT)
# ---------------------------------------------------------------------------


def link_chunks_to_documents(
    driver: neo4j.Driver,
    chunks: list[TextChunk],
) -> None:
    """Create FROM_DOCUMENT relationships from Chunk nodes to Document nodes.

    If a Document node matching the chunk's document_name does not exist,
    it is created with prefLabel set to document_name.
    """
    # Collect unique document names
    doc_names = sorted({c.document_name for c in chunks})

    with driver.session(database=NEO4J_DATABASE) as session:
        # Ensure Document nodes exist
        for doc_name in doc_names:
            session.run(
                "MERGE (d:E31_Document {prefLabel: $name}) "
                "ON CREATE SET d.entity_id = 'doc-' + $name",
                name=doc_name,
            )

        # Create FROM_DOCUMENT relationships
        batch = [
            {"chunk_id": c.chunk_id, "doc_name": c.document_name}
            for c in chunks
        ]
        session.run(
            "UNWIND $batch AS pair "
            "MATCH (c:Chunk {chunk_id: pair.chunk_id}) "
            "MATCH (d:E31_Document {prefLabel: pair.doc_name}) "
            "MERGE (c)-[:FROM_DOCUMENT]->(d)",
            batch=batch,
        )

    logger.info(
        "Created FROM_DOCUMENT links for %d chunks to %d documents",
        len(chunks),
        len(doc_names),
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def load_all(
    entities: list[CanonicalEntity],
    relations: list[ExtractedRelation],
    chunks: list[TextChunk],
    alias_map: dict[str, str],
) -> None:
    """Load the full knowledge graph into Neo4j.

    Calls all loading functions in order:
      1. Entity nodes
      2. Entity relationships
      3. Chunk nodes
      4. Chunk -> entity MENTIONS links
      5. Chunk -> document FROM_DOCUMENT links

    Args:
        entities: Canonical entities from entity resolution.
        relations: Extracted relationships between entities.
        chunks: Text chunks from the chunker.
        alias_map: Alias -> entity_id mapping from
            :func:`src.extract.resolve.build_alias_map`.
    """
    driver = get_driver()

    try:
        print("[1/5] Loading entity nodes...")
        load_entities(driver, entities)

        print("[2/5] Loading relationships...")
        load_relationships(driver, relations, entities)

        print("[3/5] Loading chunk nodes...")
        load_chunks(driver, chunks)

        print("[4/5] Linking chunks to entities (MENTIONS)...")
        link_chunks_to_entities(driver, chunks, alias_map)

        print("[5/5] Linking chunks to documents (FROM_DOCUMENT)...")
        link_chunks_to_documents(driver, chunks)

        # Print summary
        with driver.session(database=NEO4J_DATABASE) as session:
            result = session.run(
                "MATCH (n) RETURN count(n) AS nodes "
                "UNION ALL "
                "MATCH ()-[r]->() RETURN count(r) AS nodes"
            )
            counts = [record["nodes"] for record in result]
            print(f"\nGraph loaded: {counts[0]} nodes, {counts[1]} relationships")

    finally:
        driver.close()
        logger.info("Neo4j driver closed")
