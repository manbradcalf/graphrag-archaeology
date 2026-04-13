"""Naive RAG: vector search -> chunks -> Claude.

No graph traversal. Used as a comparison baseline against graph-enhanced
retrieval to demonstrate the value of the knowledge graph.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import anthropic

from src.config import ANTHROPIC_API_KEY
from src.graph.embed import embed_query
from src.rag.prompt import SYSTEM_PROMPT, assemble_prompt

if TYPE_CHECKING:
    from neo4j import Driver


async def query(driver: Driver, question: str, k: int = 10) -> dict:
    """Run a naive vector-only RAG query.

    1. Embed the question
    2. Vector search on chunk_embedding index (top-k)
    3. Assemble prompt with ranked chunks
    4. Claude generates answer with source citations

    Returns:
        Dict with answer, sources, and stats.
    """
    # 1. Embed
    query_embedding = embed_query(question)

    # 2. Vector search
    records, _, _ = driver.execute_query(
        "CALL db.index.vector.queryNodes('chunk_embedding', $k, $query_embedding) "
        "YIELD node, score "
        "RETURN node.text AS text, node.chunk_id AS chunk_id, "
        "       node.document_name AS source, score",
        k=k,
        query_embedding=query_embedding,
    )

    chunks = [
        {
            "text": r["text"],
            "chunk_id": r["chunk_id"],
            "source": r["source"],
            "score": r["score"],
        }
        for r in records
    ]

    # 3. Assemble prompt
    messages = assemble_prompt(query=question, chunks=chunks)

    # 4. Claude generates answer
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    answer = response.content[0].text

    return {
        "answer": answer,
        "sources": [
            {"chunk_id": c["chunk_id"], "source": c["source"], "score": c["score"]}
            for c in chunks
        ],
        "stats": {
            "retrieval_method": "naive_vector",
            "chunks_retrieved": len(chunks),
        },
    }
