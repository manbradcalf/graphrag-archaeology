"""Embedding generation and vector index creation for Neo4j.

Uses sentence-transformers with nomic-embed-text-v2-moe (768-dim) to embed
Chunk text and entity descriptions, then stores embeddings as node properties
and creates Neo4j vector indexes for cosine similarity search.
"""

from __future__ import annotations

import time
from functools import lru_cache
from typing import TYPE_CHECKING

from sentence_transformers import SentenceTransformer

from src.config import EMBEDDING_DIM, EMBEDDING_MODEL
from src.schema import ENTITY_TYPES

if TYPE_CHECKING:
    from neo4j import Driver


# ---------------------------------------------------------------------------
# Nomic prefix conventions
# ---------------------------------------------------------------------------
_DOC_PREFIX = "search_document: "
_QUERY_PREFIX = "search_query: "


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    """Load and cache the sentence-transformer embedding model."""
    print(f"Loading embedding model: {EMBEDDING_MODEL}")
    model = SentenceTransformer(EMBEDDING_MODEL, trust_remote_code=True)
    print("Embedding model loaded.")
    return model


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------


def embed_texts(
    texts: list[str],
    batch_size: int = 128,
    *,
    prefix: str = _DOC_PREFIX,
) -> list[list[float]]:
    """Encode texts into embedding vectors.

    Args:
        texts: Raw text strings to embed.
        batch_size: Number of texts to encode per batch.
        prefix: Nomic-style prefix. Use ``_DOC_PREFIX`` for documents/chunks
            and ``_QUERY_PREFIX`` for user queries.

    Returns:
        List of float lists, one per input text (Neo4j-compatible format).
    """
    model = get_embedding_model()
    prefixed = [f"{prefix}{t}" for t in texts]

    all_embeddings: list[list[float]] = []
    total = len(prefixed)

    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        batch = prefixed[start:end]
        vectors = model.encode(batch, show_progress_bar=False)
        all_embeddings.extend(v.tolist() for v in vectors)
        print(f"  Embedded {end}/{total} texts")

    return all_embeddings


def embed_query(text: str) -> list[float]:
    """Embed a single query string with the query prefix.

    Convenience wrapper for search-time embedding.
    """
    return embed_texts([text], prefix=_QUERY_PREFIX)[0]


# ---------------------------------------------------------------------------
# Chunk embedding
# ---------------------------------------------------------------------------


def embed_chunks(driver: Driver, batch_size: int = 128) -> int:
    """Embed all Chunk nodes that lack an ``embedding`` property.

    Args:
        driver: Neo4j driver instance.
        batch_size: Number of chunks to process per batch.

    Returns:
        Number of chunks embedded.
    """
    print("Fetching chunks without embeddings...")
    records, _, _ = driver.execute_query(
        "MATCH (c:Chunk) WHERE c.embedding IS NULL "
        "RETURN c.chunk_id AS chunk_id, c.text AS text"
    )
    if not records:
        print("All chunks already have embeddings.")
        return 0

    chunk_ids = [r["chunk_id"] for r in records]
    texts = [r["text"] for r in records]
    print(f"Embedding {len(texts)} chunks...")

    embeddings = embed_texts(texts, batch_size=batch_size)

    # Write back in batches using UNWIND
    written = 0
    for start in range(0, len(chunk_ids), batch_size):
        end = min(start + batch_size, len(chunk_ids))
        batch_data = [
            {"chunk_id": chunk_ids[i], "embedding": embeddings[i]}
            for i in range(start, end)
        ]
        driver.execute_query(
            "UNWIND $batch AS row "
            "MATCH (c:Chunk {chunk_id: row.chunk_id}) "
            "SET c.embedding = row.embedding",
            batch=batch_data,
        )
        written += len(batch_data)
        print(f"  Wrote embeddings for {written}/{len(chunk_ids)} chunks")

    return written


# ---------------------------------------------------------------------------
# Entity embedding
# ---------------------------------------------------------------------------


def _build_entity_description(label: str, prefLabel: str, note: str | None) -> str:
    """Build a description string for embedding an entity node."""
    human_type = ENTITY_TYPES.get(label, label)
    desc = f"{prefLabel} ({human_type})"
    if note:
        desc += f". {note}"
    return desc


def embed_entities(driver: Driver, batch_size: int = 128) -> int:
    """Embed entity nodes (all SHACL types) that lack an ``embedding`` property.

    Builds a description string from ``prefLabel``, type, and ``P3_has_note``
    for each entity, then stores the embedding vector on the node.

    Args:
        driver: Neo4j driver instance.
        batch_size: Number of entities to process per batch.

    Returns:
        Number of entities embedded.
    """
    entity_labels = list(ENTITY_TYPES.keys())

    # Build a UNION query across all entity types
    union_clauses = []
    for label in entity_labels:
        # Backtick-escape labels that contain hyphens
        escaped = f"`{label}`" if "-" in label else label
        union_clauses.append(
            f"MATCH (n:{escaped}) WHERE n.embedding IS NULL "
            f"RETURN n.entity_id AS entity_id, n.prefLabel AS prefLabel, "
            f"n.P3_has_note AS note, '{label}' AS label"
        )
    query = " UNION ALL ".join(union_clauses)

    print("Fetching entities without embeddings...")
    records, _, _ = driver.execute_query(query)
    if not records:
        print("All entities already have embeddings.")
        return 0

    entity_ids = [r["entity_id"] for r in records]
    descriptions = [
        _build_entity_description(r["label"], r["prefLabel"], r["note"])
        for r in records
    ]
    print(f"Embedding {len(descriptions)} entities...")

    embeddings = embed_texts(descriptions, batch_size=batch_size)

    # Write back in batches
    written = 0
    for start in range(0, len(entity_ids), batch_size):
        end = min(start + batch_size, len(entity_ids))
        batch_data = [
            {"entity_id": entity_ids[i], "embedding": embeddings[i]}
            for i in range(start, end)
        ]
        # Use a label-agnostic match on entity_id (unique across all types)
        driver.execute_query(
            "UNWIND $batch AS row "
            "MATCH (n {entity_id: row.entity_id}) "
            "SET n.embedding = row.embedding",
            batch=batch_data,
        )
        written += len(batch_data)
        print(f"  Wrote embeddings for {written}/{len(entity_ids)} entities")

    return written


# ---------------------------------------------------------------------------
# Vector index creation
# ---------------------------------------------------------------------------


def create_vector_indexes(driver: Driver) -> None:
    """Create Neo4j vector indexes on Chunk and entity embedding properties.

    Uses ``IF NOT EXISTS`` so this is safe to call repeatedly.
    """
    print("Creating vector indexes...")

    driver.execute_query(
        "CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS "
        "FOR (c:Chunk) ON (c.embedding) "
        "OPTIONS {indexConfig: {"
        f"  `vector.dimensions`: {EMBEDDING_DIM},"
        "  `vector.similarity_function`: 'cosine'"
        "}}"
    )
    print("  Created chunk_embedding index.")

    # Entity embedding index — entities span multiple labels, so we create
    # one index per SHACL type that is likely to be searched.
    for label in ENTITY_TYPES:
        escaped = f"`{label}`" if "-" in label else label
        index_name = f"{label.lower()}_embedding"
        driver.execute_query(
            f"CREATE VECTOR INDEX {index_name} IF NOT EXISTS "
            f"FOR (n:{escaped}) ON (n.embedding) "
            "OPTIONS {indexConfig: {"
            f"  `vector.dimensions`: {EMBEDDING_DIM},"
            "  `vector.similarity_function`: 'cosine'"
            "}}"
        )
        print(f"  Created {index_name} index.")

    print("Vector indexes ready.")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def embed_all(driver: Driver) -> None:
    """Run the full embedding pipeline: indexes, chunks, entities.

    Prints progress and timing for each stage.
    """
    t0 = time.perf_counter()

    create_vector_indexes(driver)

    t1 = time.perf_counter()
    n_chunks = embed_chunks(driver)
    t2 = time.perf_counter()
    print(f"Chunk embedding: {n_chunks} chunks in {t2 - t1:.1f}s")

    n_entities = embed_entities(driver)
    t3 = time.perf_counter()
    print(f"Entity embedding: {n_entities} entities in {t3 - t2:.1f}s")

    print(f"Embedding pipeline complete in {t3 - t0:.1f}s total.")
