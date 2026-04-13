"""Entity-first retrieval: filters -> subgraph -> chunks -> Claude.

Three retrieval paths depending on user input:
  - Path A (filters only): graph traversal via MENTIONS edges, no vector search
  - Path B (text only): vector search, no graph traversal
  - Path C (filters + text): both, merged with relevance boosting
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import anthropic

from src.config import ANTHROPIC_API_KEY
from src.graph.embed import embed_query
from src.rag.prompt import SYSTEM_PROMPT, assemble_prompt
from src.schema import ENTITY_TYPES, RELATIONSHIP_DISPLAY_LABELS

if TYPE_CHECKING:
    from neo4j import Driver


# ---------------------------------------------------------------------------
# Graph traversal helpers (shared by Path A and Path C)
# ---------------------------------------------------------------------------


def _get_entity_details(driver: Driver, entity_ids: list[str]) -> list[dict]:
    """Fetch entity metadata for the selected entity IDs."""
    records, _, _ = driver.execute_query(
        "MATCH (n) WHERE n.entity_id IN $ids "
        "RETURN n.entity_id AS entity_id, n.name AS name, "
        "       labels(n)[0] AS label",
        ids=entity_ids,
    )
    results = []
    for r in records:
        label = r["label"]
        results.append({
            "entity_id": r["entity_id"],
            "name": r["name"],
            "type": ENTITY_TYPES.get(label, label),
            "label": label,
        })
    return results


def _get_subgraph_triples(
    driver: Driver, entity_ids: list[str], max_hops: int = 2
) -> list[tuple[str, str, str]]:
    """Retrieve triples in the 1-2 hop neighborhood of selected entities."""
    records, _, _ = driver.execute_query(
        "MATCH (n)-[r]->(m) "
        "WHERE n.entity_id IN $ids "
        "  AND NOT type(r) IN ['MENTIONS', 'FROM_DOCUMENT'] "
        "RETURN n.name AS source, type(r) AS rel, m.name AS target "
        "UNION "
        "MATCH (n)-[r1]->(mid)-[r2]->(m) "
        "WHERE n.entity_id IN $ids AND $max_hops >= 2 "
        "  AND NOT type(r1) IN ['MENTIONS', 'FROM_DOCUMENT'] "
        "  AND NOT type(r2) IN ['MENTIONS', 'FROM_DOCUMENT'] "
        "RETURN mid.name AS source, type(r2) AS rel, m.name AS target",
        ids=entity_ids,
        max_hops=max_hops,
    )
    seen = set()
    triples = []
    for r in records:
        key = (r["source"], r["rel"], r["target"])
        if key not in seen:
            seen.add(key)
            triples.append(key)
    return triples


def _find_paths_between(
    driver: Driver, entity_ids: list[str], max_length: int = 3
) -> str:
    """Check for paths between selected entities (up to max_length hops).

    Returns a human-readable connection status string.
    """
    if len(entity_ids) < 2:
        return "Single entity selected — no path check needed."

    records, _, _ = driver.execute_query(
        "UNWIND $ids AS id1 "
        "UNWIND $ids AS id2 "
        "WITH id1, id2 WHERE id1 < id2 "
        "MATCH (a {entity_id: id1}), (b {entity_id: id2}) "
        "OPTIONAL MATCH path = shortestPath((a)-[*..3]-(b)) "
        "WHERE ALL(r IN relationships(path) WHERE NOT type(r) IN ['MENTIONS', 'FROM_DOCUMENT']) "
        "RETURN a.name AS from_entity, b.name AS to_entity, "
        "       CASE WHEN path IS NOT NULL THEN length(path) ELSE -1 END AS hops, "
        "       CASE WHEN path IS NOT NULL THEN "
        "         [r IN relationships(path) | type(r)] ELSE [] END AS rel_types",
        ids=entity_ids,
    )

    lines = []
    for r in records:
        if r["hops"] == -1:
            lines.append(f"No connection found between {r['from_entity']} and {r['to_entity']} (within {max_length} hops)")
        else:
            rels = " -> ".join(
                RELATIONSHIP_DISPLAY_LABELS.get(rt, rt) for rt in r["rel_types"]
            )
            lines.append(f"{r['from_entity']} -> {r['to_entity']}: connected in {r['hops']} hop(s) via [{rels}]")

    return "\n".join(lines) if lines else "Path check completed — no pairs to evaluate."


def _get_graph_chunks(
    driver: Driver, entity_ids: list[str], k: int = 10
) -> list[dict]:
    """Retrieve chunks via MENTIONS edges, ranked by entity coverage."""
    records, _, _ = driver.execute_query(
        "MATCH (c:Chunk)-[:MENTIONS]->(e) "
        "WHERE e.entity_id IN $ids "
        "WITH c, count(DISTINCT e) AS entity_count, "
        "     collect(DISTINCT e.name) AS mentioned_entities "
        "RETURN c.text AS text, c.chunk_id AS chunk_id, "
        "       c.document_name AS source, entity_count, mentioned_entities "
        "ORDER BY entity_count DESC "
        "LIMIT $k",
        ids=entity_ids,
        k=k,
    )
    return [
        {
            "text": r["text"],
            "chunk_id": r["chunk_id"],
            "source": r["source"],
            "entity_count": r["entity_count"],
            "mentioned_entities": r["mentioned_entities"],
        }
        for r in records
    ]


# ---------------------------------------------------------------------------
# Vector search helper (shared by Path B and Path C)
# ---------------------------------------------------------------------------


def _vector_search(
    driver: Driver, question: str, k: int = 10
) -> list[dict]:
    """Run vector similarity search on the chunk embedding index."""
    query_embedding = embed_query(question)

    records, _, _ = driver.execute_query(
        "CALL db.index.vector.queryNodes('chunk_embedding', $k, $query_embedding) "
        "YIELD node, score "
        "RETURN node.text AS text, node.chunk_id AS chunk_id, "
        "       node.document_name AS source, score",
        k=k,
        query_embedding=query_embedding,
    )
    return [
        {
            "text": r["text"],
            "chunk_id": r["chunk_id"],
            "source": r["source"],
            "score": r["score"],
        }
        for r in records
    ]


# ---------------------------------------------------------------------------
# Merge logic (Path C)
# ---------------------------------------------------------------------------


def _merge_chunks(
    graph_chunks: list[dict],
    vector_chunks: list[dict],
    k: int = 10,
    boost: float = 0.3,
) -> list[dict]:
    """Merge graph-retrieved and vector-retrieved chunks with relevance boosting.

    Chunks appearing in both sets get a score boost. Graph-only chunks are
    scored by entity coverage (normalized). Vector-only chunks keep their
    cosine similarity score.
    """
    # Index by chunk_id
    by_id: dict[str, dict] = {}

    # Normalize graph scores: entity_count / max_entity_count
    max_ec = max((c.get("entity_count", 1) for c in graph_chunks), default=1)
    for c in graph_chunks:
        graph_score = c.get("entity_count", 1) / max_ec
        by_id[c["chunk_id"]] = {
            **c,
            "score": graph_score,
            "origin": "graph",
        }

    # Merge vector results
    for c in vector_chunks:
        cid = c["chunk_id"]
        if cid in by_id:
            # Appears in both — boost
            existing = by_id[cid]
            existing["score"] = existing["score"] + c["score"] + boost
            existing["origin"] = "both"
        else:
            by_id[cid] = {
                **c,
                "origin": "vector",
            }

    # Sort by score descending, take top k
    merged = sorted(by_id.values(), key=lambda x: x.get("score", 0), reverse=True)
    return merged[:k]


# ---------------------------------------------------------------------------
# Path implementations
# ---------------------------------------------------------------------------


async def _path_a(driver: Driver, entity_ids: list[str], k: int) -> dict:
    """Path A: Filters only — graph traversal, no vector search."""
    entities = _get_entity_details(driver, entity_ids)
    triples = _get_subgraph_triples(driver, entity_ids)
    connection_status = _find_paths_between(driver, entity_ids)
    chunks = _get_graph_chunks(driver, entity_ids, k=k)

    # Attach triples to their source entities
    for entity in entities:
        entity["triples"] = [
            t for t in triples if t[0] == entity["name"]
        ]

    messages = assemble_prompt(
        selected_entities=entities,
        chunks=chunks,
        connection_status=connection_status,
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    return {
        "answer": response.content[0].text,
        "sources": [
            {"chunk_id": c["chunk_id"], "source": c["source"], "mentioned_entities": c.get("mentioned_entities", [])}
            for c in chunks
        ],
        "evidence_triples": [
            {"subject": s, "relationship": r, "object": o} for s, r, o in triples
        ],
        "connection_status": connection_status,
        "stats": {
            "retrieval_method": "graph_traversal",
            "path": "A",
            "entities_selected": len(entity_ids),
            "triples_retrieved": len(triples),
            "chunks_retrieved": len(chunks),
        },
    }


async def _path_b(driver: Driver, question: str, k: int) -> dict:
    """Path B: Text only — vector search, no graph traversal."""
    chunks = _vector_search(driver, question, k=k)

    messages = assemble_prompt(query=question, chunks=chunks)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    return {
        "answer": response.content[0].text,
        "sources": [
            {"chunk_id": c["chunk_id"], "source": c["source"], "score": c["score"]}
            for c in chunks
        ],
        "stats": {
            "retrieval_method": "vector_search",
            "path": "B",
            "chunks_retrieved": len(chunks),
        },
    }


async def _path_c(
    driver: Driver, entity_ids: list[str], question: str, k: int
) -> dict:
    """Path C: Filters + text — graph traversal merged with vector search."""
    # Graph side (same as Path A)
    entities = _get_entity_details(driver, entity_ids)
    triples = _get_subgraph_triples(driver, entity_ids)
    connection_status = _find_paths_between(driver, entity_ids)
    graph_chunks = _get_graph_chunks(driver, entity_ids, k=k)

    # Vector side
    vector_chunks = _vector_search(driver, question, k=k)

    # Merge
    merged_chunks = _merge_chunks(graph_chunks, vector_chunks, k=k)

    # Attach triples to their source entities
    for entity in entities:
        entity["triples"] = [
            t for t in triples if t[0] == entity["name"]
        ]

    messages = assemble_prompt(
        query=question,
        selected_entities=entities,
        chunks=merged_chunks,
        connection_status=connection_status,
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    # Categorize sources by origin
    sources = []
    for c in merged_chunks:
        entry = {"chunk_id": c["chunk_id"], "source": c["source"]}
        if "score" in c:
            entry["score"] = c["score"]
        if "origin" in c:
            entry["origin"] = c["origin"]
        if "mentioned_entities" in c:
            entry["mentioned_entities"] = c["mentioned_entities"]
        sources.append(entry)

    return {
        "answer": response.content[0].text,
        "sources": sources,
        "evidence_triples": [
            {"subject": s, "relationship": r, "object": o} for s, r, o in triples
        ],
        "connection_status": connection_status,
        "stats": {
            "retrieval_method": "hybrid_graph_vector",
            "path": "C",
            "entities_selected": len(entity_ids),
            "triples_retrieved": len(triples),
            "graph_chunks": len(graph_chunks),
            "vector_chunks": len(vector_chunks),
            "merged_chunks": len(merged_chunks),
        },
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def query(
    driver: Driver,
    filters: list[str] | None = None,
    question: str | None = None,
    k: int = 10,
) -> dict:
    """Run an entity-first graph retrieval query.

    Routes to the appropriate path based on inputs:
      - filters only -> Path A (graph traversal)
      - question only -> Path B (vector search)
      - both -> Path C (hybrid merge)

    Args:
        driver: Neo4j driver instance.
        filters: List of entity_ids selected by the user.
        question: Optional text query.
        k: Number of chunks to retrieve.

    Returns:
        Dict with answer, sources, evidence_triples, stats, connection_status.
    """
    has_filters = bool(filters)
    has_question = bool(question and question.strip())

    if has_filters and has_question:
        return await _path_c(driver, filters, question, k)
    elif has_filters:
        return await _path_a(driver, filters, k)
    elif has_question:
        return await _path_b(driver, question, k)
    else:
        return {
            "answer": "Please select entities from the sidebar or enter a text query.",
            "sources": [],
            "stats": {"retrieval_method": "none", "path": "none"},
        }
