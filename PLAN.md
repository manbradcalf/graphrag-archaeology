# Virginia Native Peoples GraphRAG — Implementation Plan

## Overview

A sample GraphRAG application demonstrating naive vs. graph-enhanced RAG over archaeological data about Native People of Virginia. Built as a portfolio piece showcasing best practices with open standards (CIDOC-CRM, SHACL) and a mostly-local stack.

## Source Data

- 3 PDFs (~40MB) in `pdfs/` covering Virginia archaeology
- SHACL schema in `shacl/virginia-archaeology.shacl.ttl` defining 9 CIDOC-CRM node types

## Tech Stack

| Component               | Tool                           | Local/API   |
| ----------------------- | ------------------------------ | ----------- |
| PDF extraction          | Kreuzberg                      | Local       |
| NER                     | GLiNER2                        | Local       |
| Relationship extraction | GLiNER2 + Claude               | Local + API |
| Embeddings              | nomic-embed-text-v2-moe (768d) | Local       |
| Graph DB                | Neo4j (with vector indexes)    | Local       |
| Graph validation        | graphlint (`~/code/graphlint`) | Local       |
| Chat/LLM                | Claude                         | API         |

## Graph Schema (from SHACL)

9 node types derived from CIDOC-CRM, validated by graphlint:

| Neo4j Label           | What It Represents            | Required Props | Key Relationships                                              |
| --------------------- | ----------------------------- | -------------- | -------------------------------------------------------------- |
| `E27_Site`            | Archaeological site           | `prefLabel`    | → Place, → Group, → TimePeriod, → Document                     |
| `E74_Group`           | Tribe / nation / confederacy  | `prefLabel`    | → Place, → Group (parent), → TimePeriod                        |
| `E21_Person`          | Historical figure             | `prefLabel`    | → Group, → Document                                            |
| `E22_Man-Made_Object` | Artifact                      | `prefLabel`    | → Site, → TimePeriod, → Document                               |
| `E5_Event`            | Historical event              | `prefLabel`    | → Place/Site (min 1), → TimePeriod (exactly 1), → Person/Group |
| `E53_Place`           | Geographic location           | `prefLabel`    | → Place (parent)                                               |
| `E52_Time-Span`       | Cultural/chronological period | `prefLabel`    | (leaf node)                                                    |
| `E31_Document`        | Source publication            | `prefLabel`    | → Person (author), → TimePeriod                                |
| `S19_Encounter_Event` | Archaeological discovery      | —              | → Person, → Artifact, → Site, → TimePeriod                     |

Additional RAG infrastructure nodes (outside SHACL, intentionally):

- `Chunk` — text chunks with embeddings, linked via `MENTIONS` → entity nodes and `FROM_DOCUMENT` → Document

## File Structure

```
archaeology/
├── PLAN.md                  ← you are here
├── pyproject.toml
├── .env.example             # NEO4J_URI, ANTHROPIC_API_KEY
├── pdfs/
├── shacl/
│   ├── OpenArchaeo-Shapes.ttl        # original (reference)
│   └── virginia-archaeology.shacl.ttl # adapted schema
│
├── src/
│   ├── __init__.py
│   ├── config.py            # Central config: Neo4j creds, model names, paths
│   ├── schema.py            # SHACL-derived constants: GLiNER labels → CIDOC-CRM types
│   │
│   ├── extract/
│   │   ├── __init__.py
│   │   ├── pdf_extract.py   # Step 1: Kreuzberg → chunked text
│   │   ├── ner.py           # Step 2: GLiNER2 entity extraction
│   │   ├── relations.py     # Step 3: GLiNER2 + Claude relationship extraction
│   │   └── resolve.py       # Step 4: Entity resolution / dedup
│   │
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── load.py          # Step 5: Neo4j node/relationship creation
│   │   ├── embed.py         # Step 6: nomic embeddings + vector indexes
│   │   └── validate.py      # Step 7: graphlint SHACL validation
│   │
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── naive.py         # Naive RAG: vector search → chunks → Claude
│   │   ├── graph_rag.py     # Graph RAG: vector search → graph traversal → Claude
│   │   └── chat.py          # Claude chat interface with tool use
│   │
│   └── pipeline.py          # Orchestrator: run steps 1-7 end-to-end
│
├── app.py                   # Streamlit UI with naive/graph toggle
│
├── scripts/
│   ├── run_pipeline.py      # CLI: python scripts/run_pipeline.py
│   └── validate.py          # CLI: python scripts/validate.py
│
└── tests/
    ├── test_ner.py
    ├── test_resolve.py
    └── test_rag.py
```

## Implementation Steps

### Step 1 — Project Scaffolding

- [x] `pyproject.toml` with dependencies
- [x] `.env.example`
- [x] `src/config.py` — load env vars, define paths
- [x] `src/schema.py` — GLiNER label → CIDOC-CRM mapping, relationship type constants

Dependencies:

```
kreuzberg>=4.0
gliner2>=1.2
neo4j>=5.20
anthropic>=0.40
sentence-transformers>=3.0
streamlit>=1.40
python-dotenv>=1.0
graphlint (local: ~/code/graphlint)
```

### Step 2 — PDF Extraction (Kreuzberg)

- [ ] `src/extract/pdf_extract.py`
- [ ] Use Kreuzberg's structure-aware extraction, not naive char-limit chunking:
  - **Markdown output** (default) — preserves headings, lists, table structure in text
  - **Document structure tree** (`include_document_structure=True`) — hierarchical sections/headings/paragraphs
  - **Page extraction** (`PageConfig(extract_pages=True)`) — per-page content, tables, images
  - **Semantic chunking** (`ChunkingConfig`) — Rust-based `semantic-text-splitter` that respects markdown structure (headings, paragraphs, code blocks) as split boundaries. Splits by paragraph first, then sentence, then word as fallback. NOT a dumb char-limit splitter.
- [ ] Chunking config: `max_chars=2000` (generous, since the splitter finds natural boundaries), `max_overlap=200`
- [ ] Each chunk automatically gets `first_page` / `last_page` metadata from Kreuzberg
- [ ] Track provenance: `(document_name, first_page, last_page, chunk_index)`
- [ ] Output: list of `TextChunk` dataclass objects with stable IDs
- [ ] Consider also using element-based extraction (`ResultFormat.ElementBased`) to get typed elements (title, narrative text, table) with bounding boxes — useful if we want to weight headings differently during NER

### Step 3 — Entity Extraction (GLiNER2)

- [ ] `src/extract/ner.py`
- [ ] GLiNER2 label set tuned for this domain:
  - "archaeological site" → `E27_Site`
  - "tribe" / "nation" / "confederacy" → `E74_Group`
  - "person" → `E21_Person`
  - "artifact" / "tool" / "weapon" → `E22_Man-Made_Object`
  - "event" → `E5_Event`
  - "river" / "valley" / "region" / "mountain" → `E53_Place`
  - "time period" / "cultural period" → `E52_Time-Span`
- [ ] Run on each chunk, collect `ExtractedEntity(text, schema_label, source_chunk_id, confidence)`
- [ ] Inspect results on a sample before running full extraction — tune labels if needed

### Step 4 — Relationship Extraction (GLiNER2 + Claude)

- [ ] `src/extract/relations.py`
- [ ] GLiNER2 relation extraction first (explicit relationships)
- [ ] Claude second pass on chunks with entities but few/no relations (implicit relationships)
- [ ] Claude prompt returns structured JSON matching SHACL relationship types
- [ ] Output: `ExtractedRelation(head_text, head_label, relation_type, tail_text, tail_label, source_chunk_id, confidence)`
- [ ] Also extract `E31_Document` entities (the 3 PDFs + any cited references)

SHACL-derived relationship types for extraction:

```
P53_HAS_FORMER_OR_CURRENT_LOCATION  (Site/Group → Place)
HAS_CULTURAL_AFFILIATION            (Site → Group)
P107I_IS_CURRENT_OR_FORMER_MEMBER_OF (Person/Group → Group)
P4_HAS_TIME-SPAN                    (Site/Artifact/Event → TimePeriod)
P8_TOOK_PLACE_ON_OR_WITHIN          (Event → Place/Site)
P11_HAD_PARTICIPANT                  (Event → Person/Group)
O19_HAS_FOUND_OBJECT                (DiscoveryEvent → Artifact)
P14_CARRIED_OUT_BY                  (DiscoveryEvent/Document → Person)
P70I_IS_DOCUMENTED_IN               (* → Document)
P89_FALLS_WITHIN                    (Place → Place)
P45_CONSISTS_OF                     (Artifact material, stored as property)
P101_HAD_AS_GENERAL_USE             (Artifact function, stored as property)
```

### Step 5 — Entity Resolution

- [ ] `src/extract/resolve.py`
- [ ] Tier 1: Exact match (case-insensitive, strip articles)
- [ ] Tier 2: Fuzzy match within same schema type (Levenshtein > 0.85)
- [ ] Tier 3: Claude for ambiguous cases (batch candidates, ask "are these the same?")
- [ ] Output: canonical `Entity` table + alias mapping
- [ ] Entity IDs: slugified, e.g., `site-cactus-hill`, `group-powhatan-confederacy`

### Step 6 — Graph Loading (Neo4j)

- [ ] `src/graph/load.py`
- [ ] `MERGE` nodes on `entity_id` for idempotency
- [ ] Property names match graphlint expectations: `prefLabel`, `P3_has_note`, `P2_has_type`, etc.
- [ ] Create `Chunk` nodes with `text`, `document_name`, `page_start`, `page_end`
- [ ] Create `MENTIONS` relationships: `(Chunk)-[:MENTIONS]->(entity)`
- [ ] Create `FROM_DOCUMENT` relationships: `(Chunk)-[:FROM_DOCUMENT]->(Document)`
- [ ] Neo4j 5.11+ required (for vector indexes)

### Step 7 — Embedding Generation

- [ ] `src/graph/embed.py`
- [ ] Model: `nomic-ai/nomic-embed-text-v2-moe` via sentence-transformers (768 dimensions)
- [ ] Embed chunk text → store as `embedding` property on `Chunk` nodes
- [ ] Embed entity descriptions (`"{prefLabel} ({type}). {note}"`) → store on entity nodes
- [ ] Create vector indexes:

  ```cypher
  CREATE VECTOR INDEX chunk_embedding FOR (c:Chunk)
  ON (c.embedding) OPTIONS {indexConfig: {
    `vector.dimensions`: 768,
    `vector.similarity_function`: 'cosine'
  }}
  ```

- [ ] Batch encode (128 at a time)

### Step 8 — Graph Validation (graphlint)

- [ ] `src/graph/validate.py`
- [ ] Load SHACL, parse with graphlint, execute against Neo4j
- [ ] Domain nodes should pass all 60 checks
- [ ] Strict mode flags `Chunk`/`MENTIONS`/`FROM_DOCUMENT` as undeclared — expected and intentional
- [ ] Save validation report for display in UI

### Step 9 — RAG Query Pipeline

- [ ] `src/rag/naive.py` — Vector-only retrieval

  ```cypher
  CALL db.index.vector.queryNodes('chunk_embedding', $k, $query_embedding)
  YIELD node, score
  RETURN node.text AS text, node.document_name AS source, score
  ```

- [ ] `src/rag/graph_rag.py` — Vector + graph traversal

  ```cypher
  -- Find chunks via vector search
  CALL db.index.vector.queryNodes('chunk_embedding', $k, $query_embedding)
  YIELD node AS chunk, score WHERE score > $threshold
  -- Traverse to entities and their 1-2 hop neighborhood
  MATCH (chunk)-[:MENTIONS]->(entity)
  OPTIONAL MATCH (entity)-[r]->(related)
  RETURN chunk.text, entity.prefLabel, type(r), related.prefLabel, score
  ```

- [ ] `src/rag/chat.py` — Claude with system prompt explaining the domain; receives retrieved context from either mode

### Step 10 — Streamlit UI

- [ ] `app.py`
- [ ] Sidebar: naive/graph toggle, graph stats (node counts, relationship counts)
- [ ] Main: chat interface with Claude
- [ ] Expandable panels: show retrieved context (chunks + graph paths) per response
- [ ] "Schema Compliance" tab: graphlint validation report
- [ ] Pre-loaded example questions:
  - "What archaeological evidence supports pre-Clovis habitation in Virginia?"
  - "Which tribes were part of the Powhatan Confederacy and where were they located?"
  - "What artifacts were found at sites in the Shenandoah Valley?"

## Key Design Decisions

**GLiNER2 + Claude hybrid** — GLiNER handles bulk NER locally for free. Claude only runs on chunks needing relationship extraction or entity disambiguation. Shows understanding of cost/quality tradeoffs.

**Chunk nodes outside SHACL** — Clean separation between domain ontology (CIDOC-CRM, validated) and RAG infrastructure (application concern). graphlint's strict mode catching these as warnings is a feature, not a bug.

**SHACL-driven schema** — The graph structure is derived from a W3C standard, not hand-rolled. graphlint validates conformance. This is the differentiator vs. typical GraphRAG demos.

**Naive vs. graph toggle** — The whole point of the demo. Graph RAG should visibly outperform on multi-hop questions ("Which tribes were connected to the Powhatan Confederacy and what sites are associated with them?") while naive RAG handles simple factual lookups fine.

## Risks to Watch

| Risk                                              | Mitigation                                                         |
| ------------------------------------------------- | ------------------------------------------------------------------ |
| GLiNER2 misses domain-specific entities           | Tune label set; inspect sample output before full run              |
| Entity resolution false merges                    | Conservative thresholds; small corpus makes manual review feasible |
| Neo4j labels with hyphens (`E22_Man-Made_Object`) | graphlint handles backtick escaping; verify in load.py             |
| PDF extraction quality (tables, figures)          | Kreuzberg handles well; filter non-text chunks                     |
