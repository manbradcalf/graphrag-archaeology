# ArchaeoGraph Virginia

A knowledge graph pipeline for Virginia archaeology — extracts structured entities and relationships from PDF documents using an ontology-driven schema (CIDOC-CRM), then loads them into Neo4j for exploration.

## What it does

Given a SHACL file derived from a provided ontology (in our case, CIDOC-CRM), the pipeline:

1. **PDF extraction** (kreuzberg) — extracts text from PDFs to markdown with page markers for provenance tracking
2. **Entity extraction** (Claude) — extracts typed entities guided by the SHACL-derived schema, with entity descriptions grounded in source text
3. **Relationship extraction** (Claude) — extracts typed relationships between extracted entities, validated against SHACL-defined constraints
4. **Entity resolution** (fuzzy matching) — deduplicates entities across documents using normalized name matching and SequenceMatcher, with ambiguous candidates flagged for manual review
5. **Graph loading** (Cypher + neo4j driver) — writes entities and relationships to a Neo4j database using MERGE for idempotency

The pipeline does **not** yet embed chunks or create vector indexes for semantic search.

## TODO

- Pre-validate Cypher queries against GraphLint using the same SHACL file
- Store text chunks as nodes with embeddings for hybrid graph + vector search
- Auto-generate SHACL files from an ontology
- Option to use Neo4j Graph Types rather than SHACL

## Tech Stack

Neo4j, Claude, kreuzberg, SHACL/CIDOC-CRM

## Usage

```bash
# Run the full pipeline
uv run python main.py

# Individual steps
uv run python main.py extract        # PDFs -> markdown
uv run python main.py ner            # entity extraction (costs money)
uv run python main.py relations      # relationship extraction (costs money)
uv run python main.py resolve        # entity resolution
uv run python main.py load           # load into Neo4j

# Options
uv run python main.py --force        # re-run even if cached output exists
uv run python main.py --llm-cleanup  # use Claude for OCR cleanup (costs money)
```

## Data

Supply your own PDFs in `data/pdf/`. The SHACL schema lives in `shacl/virginia-archaeology.shacl.ttl` and is translated to Python constants in `src/schema.py`.
