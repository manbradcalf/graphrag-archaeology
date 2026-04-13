"""FastAPI backend: /query, /entities, /health.

Serves the query API and static frontend UI.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import neo4j
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import NEO4J_DATABASE, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USERNAME
from src.rag import graph_rag, naive
from src.schema import ENTITY_CATEGORIES, ENTITY_TYPES

# ---------------------------------------------------------------------------
# Neo4j driver lifecycle
# ---------------------------------------------------------------------------

_driver: neo4j.Driver | None = None


def _get_driver() -> neo4j.Driver:
    global _driver
    if _driver is None:
        _driver = neo4j.GraphDatabase.driver(
            NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD)
        )
    return _driver


@asynccontextmanager
async def lifespan(app: FastAPI):
    _get_driver()
    yield
    if _driver is not None:
        _driver.close()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="ArchaeoGraph Virginia", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    filters: list[str] | None = None
    question: str | None = None
    k: int = 10
    mode: str = "graph"  # "graph" or "naive"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    """Basic health check — verifies Neo4j connectivity."""
    driver = _get_driver()
    try:
        driver.execute_query(
            "RETURN 1 AS ok", database_=NEO4J_DATABASE
        )
        return {"status": "healthy", "neo4j": "connected"}
    except Exception as e:
        return {"status": "degraded", "neo4j": str(e)}


@app.get("/entities")
async def entities():
    """Return all entities grouped by category with mention counts.

    Each entity includes its entity_id, name, type, and the number of
    chunks that mention it (for the sidebar count badges).
    """
    driver = _get_driver()

    # Build a UNION query across all entity types
    union_clauses = []
    for label in ENTITY_TYPES:
        escaped = f"`{label}`" if "-" in label else label
        union_clauses.append(
            f"MATCH (n:{escaped}) "
            f"OPTIONAL MATCH (c:Chunk)-[:MENTIONS]->(n) "
            f"WITH n, count(c) AS mention_count "
            f"RETURN n.entity_id AS entity_id, n.name AS name, "
            f"       '{label}' AS label, mention_count"
        )
    query = " UNION ALL ".join(union_clauses)
    records, _, _ = driver.execute_query(query, database_=NEO4J_DATABASE)

    # Group into categories
    label_to_category = {}
    for cat, labels in ENTITY_CATEGORIES.items():
        for lbl in labels:
            label_to_category[lbl] = cat

    categories: dict[str, list[dict]] = {cat: [] for cat in ENTITY_CATEGORIES}
    for r in records:
        cat = label_to_category.get(r["label"], "Other")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append({
            "entity_id": r["entity_id"],
            "name": r["name"],
            "type": ENTITY_TYPES.get(r["label"], r["label"]),
            "mention_count": r["mention_count"],
        })

    # Sort each category by mention count descending
    for cat in categories:
        categories[cat].sort(key=lambda e: e["mention_count"], reverse=True)

    return {"categories": categories}


@app.post("/query")
async def query(request: QueryRequest):
    """Accept query, route to appropriate retrieval path.

    If mode is "naive", runs vector-only search for comparison.
    If mode is "graph" (default), routes to graph_rag which selects
    Path A/B/C based on the presence of filters and/or question.
    """
    driver = _get_driver()

    if request.mode == "naive":
        if not request.question:
            return {
                "answer": "Naive RAG requires a text query.",
                "sources": [],
                "stats": {"retrieval_method": "naive_vector"},
            }
        return await naive.query(driver, request.question, k=request.k)

    return await graph_rag.query(
        driver,
        filters=request.filters,
        question=request.question,
        k=request.k,
    )


# ---------------------------------------------------------------------------
# Static UI (mount last so API routes take precedence)
# ---------------------------------------------------------------------------

_ui_dir = Path(__file__).resolve().parent.parent / "ui"
if _ui_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_ui_dir), html=True), name="ui")
