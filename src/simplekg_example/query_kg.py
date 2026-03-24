"""Query the archaeology knowledge graph using vector similarity search.

Usage:
    uv run python src/query_kg.py "What forts were built in western Virginia?"
"""

from __future__ import annotations

import sys

import neo4j
from neo4j_graphrag.embeddings import SentenceTransformerEmbeddings
from neo4j_graphrag.retrievers import VectorRetriever

from config import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USERNAME,
)

INDEX_NAME = "chunk_embedding_index"


def ensure_vector_index(driver: neo4j.Driver) -> None:
    """Create the vector index if it doesn't exist."""
    with driver.session(database="neo4j") as session:
        session.run(
            "CREATE VECTOR INDEX $name IF NOT EXISTS "
            "FOR (c:Chunk) ON (c.embedding) "
            "OPTIONS {indexConfig: {`vector.dimensions`: $dim, `vector.similarity_function`: 'cosine'}}",
            name=INDEX_NAME,
            dim=EMBEDDING_DIM,
        )
    print(f"Vector index '{INDEX_NAME}' ready.")


def main() -> None:
    query = (
        " ".join(sys.argv[1:])
        if len(sys.argv) > 1
        else "What archaeological sites exist?"
    )

    driver = neo4j.GraphDatabase.driver(
        NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD)
    )
    driver.verify_connectivity()

    ensure_vector_index(driver)

    embedder = SentenceTransformerEmbeddings(
        model=EMBEDDING_MODEL, trust_remote_code=True
    )

    retriever = VectorRetriever(
        driver=driver,
        index_name=INDEX_NAME,
        embedder=embedder,
        neo4j_database="neo4j",
        return_properties=["text"],
    )

    print(f"\nQuery: {query}\n")
    results = retriever.search(query_text=query, top_k=20)

    for i, item in enumerate(results.items, 1):
        text = item.content
        score = item.metadata.get("score", "?")
        node_id = item.metadata.get("id", "?")
        labels = item.metadata.get("labels")
        print(f"--- Result {i} (score: {score:.4f})-")
        print(f"--- Labels {labels}")
        print(f"--- ID: {node_id:})")
        print(f"{text}...")
        print()

    driver.close()


if __name__ == "__main__":
    main()
