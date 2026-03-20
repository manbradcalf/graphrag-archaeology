# Virginia Native Peoples — Knowledge Graph Explorer

## Overview

A knowledge graph exploration tool over archaeological data about Native Peoples of Virginia. Users browse and select entities as the primary search mechanism — the graph IS the product, not an invisible retrieval layer behind a chatbot. LLM synthesis is secondary and supportive: the LLM acts as a guide that navigates source material on behalf of the user, not an authority delivering answers.

This is a custom implementation that shares infrastructure with standard GraphRAG (Neo4j, chunks, embeddings) but inverts the interaction model: entity navigation first, text search second. A separate branch (`VectorCypherRetriever`) implements standard/vanilla GraphRAG — using Neo4j's VectorCypherRetriever pattern with a search-box-first interface — for comparison.

Built to show Upwork clients: "I can do what you're looking for." Showcases schema-first knowledge graph construction (CIDOC-CRM, SHACL), LLM-driven extraction, and an entity-first query UI.

## Source Data

- 2 PDFs in `data/pdf/`:
  - *History of the Valley of Virginia* (Kercheval, 1833) — 24MB
  - *The Archaeology of Virginia's First Peoples* — 16MB
- SHACL schema in `shacl/virginia-archaeology.shacl.ttl` defining 9 CIDOC-CRM node types

## Tech Stack

| Component               | Tool                           | Local/API   |
| ----------------------- | ------------------------------ | ----------- |
| PDF extraction          | Kreuzberg                      | Local       |
| OCR cleanup             | Regex pipeline + Claude        | Local + API |
| Chunking                | Custom markdown-aware splitter | Local       |
| NER + relationships     | Claude (SHACL-guided)          | API         |
| Entity resolution       | Exact + fuzzy + Claude (ambiguous) | Local + API |
| Embeddings              | nomic-embed-text-v2-moe (768d) | Local       |
| Graph DB + vector index | Neo4j 5.11+                    | Local       |
| Graph validation        | graphlint (`~/code/graphlint`) | Local       |
| Query LLM              | Claude                         | API         |
| Backend API             | FastAPI                        | Local       |
| UI                      | Custom HTML/CSS/JS             | Local       |

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

- `Chunk` — text chunks with vector embeddings, linked via `MENTIONS` → entity nodes and `FROM_DOCUMENT` → Document. Vector index on `embedding` property for semantic search.

## File Structure

```
archaeology/
├── PLAN.md                  ← you are here
├── pyproject.toml
├── .env.example             # NEO4J_URI, ANTHROPIC_API_KEY
├── data/
│   └── pdf/                 # source PDFs (2 documents)
├── shacl/
│   ├── OpenArchaeo-Shapes.ttl        # original (reference)
│   └── virginia-archaeology.shacl.ttl # adapted schema
│
├── src/
│   ├── __init__.py
│   ├── config.py            # Central config: Neo4j creds, model names, paths
│   ├── schema.py            # SHACL-derived constants: entity types, relationship types,
│   │                        #   and human-readable label mapping for UI display
│   │
│   ├── extract/
│   │   ├── __init__.py
│   │   ├── pdf_extract.py   # Step 2: Kreuzberg → markdown
│   │   ├── ocr_cleanup.py   # Step 2: Regex cleanup pipeline
│   │   ├── llm_cleanup.py   # Step 2: Claude cleanup for residual OCR artifacts
│   │   ├── chunker.py       # Step 3: Markdown-aware text chunking
│   │   ├── ner.py           # Step 4: Claude NER (SHACL-guided)
│   │   ├── relations.py     # Step 5: Claude relationship extraction
│   │   ├── resolve.py       # Step 6: Entity resolution / dedup
│   │   └── pipeline.py      # Orchestrator: run extraction steps end-to-end
│   │
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── load.py          # Steps 7-8: Chunk linking + Neo4j load
│   │   ├── embed.py         # Step 9: nomic embeddings + vector indexes
│   │   └── validate.py      # Step 10: graphlint SHACL validation
│   │
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── naive.py         # Naive RAG: vector search → chunks → Claude
│   │   ├── graph_rag.py     # Graph RAG: filters → subgraph → chunks → Claude
│   │   └── prompt.py        # Prompt template assembly
│   │
│   └── api.py               # FastAPI backend: /query, /entities, /health
│
├── ui/
│   ├── index.html           # Query UI with entity filters + search
│   └── architecture.html    # System architecture diagram
│
├── scripts/
│   ├── run_pipeline.py      # CLI: python scripts/run_pipeline.py
│   └── validate.py          # CLI: python scripts/validate.py
│
├── docker-compose.yml       # Neo4j + FastAPI for local deployment
│
└── tests/
    ├── test_ner.py
    ├── test_resolve.py
    └── test_rag.py
```

## Implementation Steps

### Step 1 — Project Scaffolding

- [x] `pyproject.toml` with dependencies
- [ ] `.env.example`
- [ ] `src/config.py` — load env vars, define paths
- [ ] `src/schema.py` — entity type and relationship type constants from SHACL, plus human-readable label mapping (see Step 12)
- [x] SHACL schema (`virginia-archaeology.shacl.ttl`)
- [x] UI mockup (`ui/index.html`) — entity filter sidebar, sample queries, mock responses

Dependencies:

```
kreuzberg>=4.0
neo4j>=5.20
anthropic>=0.40
sentence-transformers>=3.0
python-dotenv>=1.0
fastapi>=0.110
uvicorn>=0.30
graphlint (local: ~/code/graphlint)
```

### Step 2 — PDF Extraction + Cleanup

- [ ] `src/extract/pdf_extract.py` — Kreuzberg extraction to markdown
  - Markdown output preserving headings, lists, table structure
  - Page extraction for provenance tracking
- [ ] `src/extract/ocr_cleanup.py` — Regex pipeline for systematic OCR errors
- [ ] `src/extract/llm_cleanup.py` — Claude pass for residual artifacts regex can't catch
- [ ] Output: clean markdown per document in `data/md/`

### Step 3 — Text Chunking

- [ ] `src/extract/chunker.py` — custom markdown-aware splitter
  - Split on heading boundaries (##, ###) and paragraph breaks first; fall back to sentence boundaries only when a section exceeds `max_chars`
  - Target chunk size: ~1500-2000 chars with ~200 char overlap at paragraph boundaries
  - Never split mid-sentence; never split a heading from its first paragraph
  - Alternative: `langchain.text_splitter.MarkdownTextSplitter` if we want to avoid writing this from scratch, but a custom ~80-line splitter gives us full control and no heavy dependency
- [ ] Each chunk gets provenance: `(document_name, section_heading, first_page, last_page, chunk_index)`
- [ ] Output: list of `TextChunk` dataclass objects with stable IDs

### Step 4 — Entity Extraction (Claude, SHACL-guided)

- [ ] `src/extract/ner.py`
- [ ] **Document/section-level NER**, not per-chunk — LLM needs full context for coreference resolution
- [ ] Claude prompt provides the SHACL entity types as extraction targets:
  - `E27_Site` — archaeological sites (e.g., Cactus Hill, Thunderbird)
  - `E74_Group` — tribes, nations, confederacies (e.g., Powhatan, Monacan)
  - `E21_Person` — historical figures (e.g., John Smith, Wahunsenacah)
  - `E22_Man-Made_Object` — artifacts, tools, weapons (e.g., projectile points, ceramic vessels)
  - `E5_Event` — historical events (e.g., battles, migrations, encounters)
  - `E53_Place` — geographic locations (e.g., Shenandoah Valley, James River)
  - `E52_Time-Span` — cultural/chronological periods (e.g., Late Woodland, Contact Era)
- [ ] Claude returns structured JSON: `{name, type, aliases, description, confidence}` per entity
- [ ] Output: entity registry per document with canonical names, types, aliases, descriptions
- [ ] Inspect results on a sample section before running full extraction

Note: For a 2-document corpus (~50-100 sections), Claude-only NER is the pragmatic choice. The cost is a few dollars total, and it eliminates the complexity of maintaining a hybrid GLiNER2 + Claude pipeline with confidence thresholds and fallback logic. At scale (hundreds of documents), GLiNER2 for bulk first-pass NER with Claude as a fallback would be the right architecture — but that's over-engineering for a portfolio piece.

### Step 5 — Relationship Extraction (Claude)

- [ ] `src/extract/relations.py`
- [ ] Claude extracts relationships from each section, guided by the SHACL relationship type list
- [ ] Prompt provides entity registry (from Step 4) so Claude can reference canonical entity names
- [ ] Claude returns structured JSON matching SHACL relationship types
- [ ] Output: `ExtractedRelation(head_text, head_label, relation_type, tail_text, tail_label, source_section, confidence)`

Note: GLiNER/GLiNER2 is a NER model (token-level span classifier) — it does not do relation extraction. For 2 documents, Claude handles both NER and relationship extraction at negligible cost.

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

### Step 6 — Entity Resolution (cross-document)

- [ ] `src/extract/resolve.py`
- [ ] Tier 1: Exact match (case-insensitive, strip articles)
- [ ] Tier 2: Fuzzy match within same schema type (Levenshtein > 0.85)
- [ ] Tier 3: Claude for ambiguous cases (batch candidates, ask "are these the same?")
- [ ] Output: canonical `Entity` table + alias mapping
- [ ] Entity IDs: slugified, e.g., `site-cactus-hill`, `group-powhatan-confederacy`

### Step 7 — Chunk-Entity Linking

- [ ] Lives in `src/extract/pipeline.py` (linking step after entity resolution)
- [ ] After entity resolution, link chunks to canonical entities
- [ ] String/alias matching: for each chunk, check which canonical entity names or aliases appear
- [ ] Creates the `MENTIONS` edge list — no LLM needed, just matching against the entity registry
- [ ] Output: `(chunk_id, entity_id)` pairs, ready for graph loading

### Step 8 — Graph Loading (Neo4j)

- [ ] `src/graph/load.py`
- [ ] `MERGE` nodes on `entity_id` for idempotency
- [ ] Property names match graphlint expectations: `prefLabel`, `P3_has_note`, `P2_has_type`, etc.
- [ ] Create `Chunk` nodes with `text`, `document_name`, `section_heading`, `page_start`, `page_end`
- [ ] Create `MENTIONS` relationships: `(Chunk)-[:MENTIONS]->(entity)`
- [ ] Create `FROM_DOCUMENT` relationships: `(Chunk)-[:FROM_DOCUMENT]->(Document)`

### Step 9 — Embedding Generation

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

### Step 10 — Graph Validation (graphlint)

- [ ] `src/graph/validate.py`
- [ ] Load SHACL, parse with graphlint, execute against Neo4j
- [ ] Runs as a post-load check — data must be in Neo4j first (Steps 8-9) before validation can run
- [ ] Domain nodes should pass all shape checks
- [ ] Strict mode flags `Chunk`/`MENTIONS`/`FROM_DOCUMENT` as undeclared — expected and intentional
- [ ] Save validation report for display in UI

### Step 11 — Query Pipeline (Entity-First Retrieval)

Three retrieval paths that converge at the prompt template, selected based on what the user provides. Path A (entity filters) is the **primary path** — the one that makes this a knowledge graph explorer rather than a search box with a graph behind it. Path B is a convenience fallback for text-only queries. Path C combines both.

**Naive RAG** (`src/rag/naive.py`) — Vector-only retrieval (toggle comparison):

```cypher
CALL db.index.vector.queryNodes('chunk_embedding', $k, $query_embedding)
YIELD node, score
RETURN node.text AS text, node.document_name AS source, score
```

**Graph RAG** (`src/rag/graph_rag.py`) — Three retrieval paths (entity-first):

**Path A: Filters only — PRIMARY** (user selects entities, no text query)

Graph traversal only. No vector search.

1. Parse selected entity filters → node IDs
2. Subgraph retrieval: 1-2 hop neighborhood around selected entities
3. Path check: find paths between selected entities (≤3 hops). If no path, note "no connection found"
4. Retrieve chunks via `MENTIONS` edges: `MATCH (c:Chunk)-[:MENTIONS]->(e) WHERE e.entity_id IN $selected RETURN c`
5. Rank chunks by number of selected entities they mention (more = more relevant)
6. Assemble prompt with entity triples, paths, and chunks

**Path B: Text query only** (user types a question, no entity filters)

Vector search only. No graph traversal.

1. Embed user query
2. Vector search on full `chunk_embedding` index (top-k)
3. Assemble prompt with ranked chunks — same as naive RAG but through the graph_rag module for consistent response formatting

**Path C: Filters + text query** (user selects entities AND types a question)

Both graph traversal and vector search, merged.

1. **Graph side**: Subgraph retrieval around selected entities → extract entity triples and paths (same as Path A steps 1-3)
2. **Vector side**: Embed user query → vector search on full chunk index (top-k)
3. **Merge**: Union graph-retrieved chunks (via MENTIONS) with vector-retrieved chunks. Chunks that appear in both get a boost. Deduplicate.
4. Assemble prompt with entity context (triples, paths, connection status) AND semantically ranked chunks

**Prompt assembly** (`src/rag/prompt.py`) — shared across all paths:

```
You are a research assistant for Virginia archaeology. Answer based ONLY
on the provided knowledge graph context and source text.

## User Query
{query}

## Selected Entities
{selected_entities}

## Retrieved Context
{for each entity}
### Entity: {entity.name} ({entity.type})
Graph connections:
{entity.triples}
Source chunks:
{entity.chunks}
{end for}

## Connection Status
{connection_status}

## Instructions
Answer the user's query using the retrieved context above. Ground your
response in the graph connections and source text provided. When entities
are connected, explain the relationship using the graph paths as evidence.
When no connection exists, say so directly — do not infer or fabricate
relationships not supported by the graph. If the query cannot be answered
from the available context, say so. Cite sources using [1], [2] notation.
```

### Step 12 — UI (Knowledge Graph Explorer)

The UI is designed as a knowledge graph explorer, not a chatbot. The sidebar entity filters are the primary UX — the main way users interact with the system. The search bar is complementary, not central.

- [ ] `ui/index.html` — already mocked up, needs backend wiring
- [ ] Entity filter sidebar with 7 categories (matching SHACL):
  - Peoples & Cultures, Persons, Sites, Places, Events, Time Periods, Artifact Types
  - Counts from Neo4j: count = number of chunks that mention this entity, i.e., `size((n)<-[:MENTIONS]-())`. This tells the user how much source material exists for each entity.
  - Click to filter — acts as primary search mechanism, no typing required
- [ ] Search bar — complementary to filters, can combine text query + entity selection
- [ ] Auto-generated natural language summary of selected filters as search bar placeholder
- [ ] Results display:
  - Synthesized answer with `[1], [2]` source citations
  - Source cards with document title, section, quoted text
  - "Knowledge Graph Connections Used" — entity-relationship-entity triples
  - Traversal stats: nodes, relationships, sources
  - Connection status: explicit "no path found" when entities don't connect
- [ ] Naive vs. Graph RAG toggle — shows the difference side by side
- [ ] Sample query chips for immediate engagement
- [ ] Schema compliance tab — graphlint validation report

Note: The current UI mockup uses Microsoft GraphRAG terminology in its sample data ("Global Search — Community Summaries", "Local Search — Entity Neighborhoods"). Our system does not implement community detection. Update mock data labels to match our actual retrieval strategies: "Graph Retrieval" (for filter-based graph traversal) and "Vector Search" (for text-query semantic search).

**Relationship label mapping**: `src/schema.py` should include a `RELATIONSHIP_DISPLAY_LABELS` dict that maps CIDOC-CRM relationship types to human-readable labels for the UI. Examples:

```python
RELATIONSHIP_DISPLAY_LABELS = {
    "P53_HAS_FORMER_OR_CURRENT_LOCATION": "located in",
    "HAS_CULTURAL_AFFILIATION": "affiliated with",
    "P107I_IS_CURRENT_OR_FORMER_MEMBER_OF": "member of",
    "P4_HAS_TIME-SPAN": "dated to",
    "P8_TOOK_PLACE_ON_OR_WITHIN": "took place in",
    "P11_HAD_PARTICIPANT": "involved",
    "O19_HAS_FOUND_OBJECT": "found",
    "P14_CARRIED_OUT_BY": "carried out by",
    "P70I_IS_DOCUMENTED_IN": "documented in",
    "P89_FALLS_WITHIN": "within",
}
```

The UI uses these labels when displaying evidence triples (e.g., "Cactus Hill — located in — Shenandoah Valley" instead of "P53_HAS_FORMER_OR_CURRENT_LOCATION").

### Step 13 — Backend API (FastAPI)

- [ ] `src/api.py`
- [ ] Framework: FastAPI

Routes:

- `GET /health` — basic health check, returns `{status: "ok", neo4j_connected: bool}`
- `GET /entities` — return all entities grouped by type with mention counts:
  ```json
  {
    "Peoples & Cultures": [{"name": "Monacan", "entity_id": "group-monacan", "count": 34}, ...],
    "Events": [{"name": "Battle of Bloody Run", "entity_id": "event-battle-bloody-run", "count": 5}, ...],
    ...
  }
  ```
- `POST /query` — accept request, route to appropriate retrieval path:
  ```json
  // Request
  {"filters": ["group-monacan", "place-shenandoah-valley"], "query": "optional text"}

  // Response
  {
    "answer": "...",
    "sources": [{"num": 1, "title": "...", "section": "...", "chunk": "..."}],
    "evidence_triples": [["Monacan", "located in", "Shenandoah Valley"]],
    "stats": {"nodes_traversed": 12, "relationships_traversed": 18, "sources_used": 3},
    "connection_status": "Connected via 2-hop path through E53_Place:Shenandoah Valley",
    "retrieval_path": "filters_and_text"
  }
  ```
  The `filters` and `query` fields determine which retrieval path runs (see Step 11): filters-only, text-only, or both.
- [ ] Static frontend served from `/ui` alongside the API
- [ ] CORS configured for local development

### Step 14 — Deployment

For a portfolio piece with 2 documents, the practical deployment target is **local with Docker Compose**:

- [ ] `docker-compose.yml` with two services:
  - `neo4j` — official Neo4j image with APOC plugin, volume-mounted data
  - `api` — FastAPI app serving backend + static UI
- [ ] README with clear "run locally" instructions:
  1. `cp .env.example .env` and fill in `ANTHROPIC_API_KEY`
  2. `docker compose up`
  3. Open `http://localhost:8000`
- [ ] Pre-built graph option: include a Neo4j database dump so reviewers can skip the extraction pipeline and go straight to querying
- [ ] Recorded demo video or screenshots for people who don't want to set up Neo4j locally
- [ ] If live hosting is desired: Neo4j Aura Free tier (limited but sufficient for 2 docs), or a small VPS running Docker Compose. Be aware Neo4j hosting is not cheap — Aura Pro starts at ~$65/month. For a portfolio piece, a demo video is more practical than paying for hosting.

## Key Design Decisions

**Schema-first extraction** — SHACL shapes define the ontology before any text is processed. NER and relationship extraction are guided by the schema, not the other way around. This produces a cleaner graph and demonstrates methodology a client can trust with their own data.

**Claude-only extraction (pragmatic for corpus size)** — For 2 documents (~50-100 sections), Claude handles NER, relationship extraction, and ambiguous entity resolution at a total cost of a few dollars. This eliminates the complexity of maintaining a hybrid local/API pipeline with confidence thresholds and fallback logic. At scale (hundreds+ of documents), the right architecture would be GLiNER2 for bulk first-pass NER with Claude as a fallback for low-confidence sections — but that's over-engineering for this corpus size. The plan is structured so that `ner.py` and `relations.py` could be swapped to a hybrid approach later without changing downstream steps.

**Document-level NER, chunk-level linking** — NER runs at document/section level for full coreference context. Chunk-entity linking happens after entity resolution via string matching (Step 7, in `pipeline.py`). This avoids the per-chunk NER problem where "they migrated south" loses its referent.

**Chunk nodes outside SHACL** — Clean separation between domain ontology (CIDOC-CRM, validated) and RAG infrastructure (application concern). graphlint's strict mode catching these as warnings is a feature, not a bug.

**Three retrieval paths, not one** — The query pipeline distinguishes filters-only, text-only, and filters+text because they have fundamentally different retrieval mechanics. Filters-only uses graph traversal and MENTIONS edges (no vector search needed). Text-only uses vector search (no graph traversal needed). Combined uses both and merges results. A single linear pipeline would either do unnecessary work or miss relevant context depending on the query type. A standard VectorCypherRetriever implementation exists on the `VectorCypherRetriever` branch for comparison — it collapses all three paths into a single search-box-first flow.

**Entity filters as primary search (not standard GraphRAG)** — This project is NOT GraphRAG in the standard sense. Standard GraphRAG (e.g., Neo4j's VectorCypherRetriever pattern, Microsoft's community-summary approach) uses the graph to enhance retrieval for a search-box-first interface — the graph is invisible infrastructure. This project inverts that: the graph IS the interface. Users explore entities directly by browsing and clicking; the LLM guides them through source material rather than delivering authoritative answers. The UI sidebar isn't decoration — clicking entities IS searching. The graph scopes retrieval, filters determine which part of the graph to traverse, and chunks are retrieved via MENTIONS edges.

**Honest connection status** — When selected entities have no graph path between them, the system says so explicitly and doesn't fabricate a relationship. The graph does the connection check; the LLM respects the result. This is the portfolio differentiator.

**Naive vs. graph toggle** — Kept from the original plan. Graph RAG should visibly outperform on multi-hop questions while naive RAG handles simple factual lookups fine. The toggle makes the value proposition undeniable.

**SHACL validation as a feature** — graphlint validates the graph against the schema. The compliance report is visible in the UI. This shows rigor that typical GraphRAG demos lack.

## Future UI Enhancements (out of scope for v1)

These are deferred until the pipeline is working end-to-end:

- **"Double Check" button** — opt-in verification pass. When clicked, sends each cited claim + its source chunk to Haiku: "does this chunk support this claim?" Returns SUPPORTED / PARTIAL / UNSUPPORTED. Results shown as badges on each citation. Keeps verification cost out of the default query path.
- **Citation verification badges** — green (supported), yellow (partial), gray (uncited inference) on each `[1], [2]` reference, powered by the Double Check pass above
- **Entity highlight toggle** — lights up entity names in both the answer text and the source chunk text, so the user can visually trace the throughline from source to synthesis
- **Interactive citation hovers** — clicking a `[1]` superscript in the answer text shows the source chunk inline, not just in the SOURCES section below

## Risks to Watch

| Risk                                              | Mitigation                                                         |
| ------------------------------------------------- | ------------------------------------------------------------------ |
| Claude NER misses domain-specific entities         | SHACL type list in prompt guides extraction; inspect sample output before full run; iterate on prompt |
| Claude extraction cost exceeds expectations        | ~50-100 sections x 2 calls (NER + relations) = ~200 API calls. Budget ~$5. Monitor token usage. |
| Entity resolution false merges                    | Conservative thresholds; small corpus makes manual review feasible |
| Neo4j labels with hyphens (`E22_Man-Made_Object`) | graphlint handles backtick escaping; verify in load.py             |
| PDF extraction quality (OCR artifacts)            | Two-stage cleanup: regex pipeline + Claude for residuals           |
| Filters-only retrieval returns too many chunks    | Limit to top-N chunks ranked by number of selected entities mentioned; paginate if needed |
| Text-only retrieval misses graph context          | Expected — that's the point of the naive vs. graph toggle comparison |
| LLM fabricates connections despite prompt          | Connection status is structural (graph path check), not LLM judgment |
| Neo4j hosting cost for live demo                  | Default to Docker Compose local; demo video as fallback; Aura Free for lightweight live version |
