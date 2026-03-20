# ArchaeoGraph Virginia

A knowledge graph explorer for Virginia archaeology — entity-first search over CIDOC-CRM-modeled archaeological data with optional LLM synthesis.

## Approach

This is NOT standard GraphRAG (where a graph invisibly enhances retrieval for a chatbot). The graph is the interface — users browse entities, explore connections, and see source evidence directly. A standard VectorCypherRetriever implementation lives on the `VectorCypherRetriever` branch for comparison.

## Tech Stack

Neo4j, Claude, SHACL/CIDOC-CRM, Nomic embeddings

## Documentation

See `PLAN.md` for full implementation details.

## Data

Supply your own PDFs in `data/pdf/`.
