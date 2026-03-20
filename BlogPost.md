# Synthesizing the Historical and Archaeological Record of Pre-Contact Native Americans in the Shenandoah Valley for RAG Ingestion
## The Problem

The history of native people in the Shenandoah Valley before European contact is rich.   

However, a cursory Google search or LLM query is likely to mention that it was, at the time of contact, anywhere from empty, abandoned, or sparsely populated at the time of European contact. While this may have been true at the time, it obscures a rich history going back 15,000 years, when central Pennsylvania was still under the Laurentide Ice Sheet. 

So while we're taught the names of all Virginian presidents, two of their houses, and the year Columbus sailed the ocean blue...we're leaving roughly 6 "Jesus's lifetimes agos" worth of history on the cutting room floor. 

This gap has enthralled me ever since I discovered it.  

So how can we learn more?

## The Solution

A knowledge graph explorer built from PDF sources — entity-first search, not a chatbot.


## PDF Extraction & Cleanup: Pipeline vs. Agent

We compared two approaches to cleaning OCR-extracted markdown from a PowerPoint-turned-PDF ([Native American Ceramics Powerpoint 9-24.pdf](data/pdf/Native%20American%20Ceramics%20Powerpoint%209-24.pdf)):

1. **Self-service pipeline** (`uv run python main.py`) — kreuzberg extraction + regex-based OCR cleanup
2. **pdf-extract-cleaner agent** — a Claude Code subagent (Sonnet) that reads, reasons about, and rewrites the file

| | **Pipeline** (regex only) | **Agent** (Sonnet) |
|---|---|---|
| **Size** | 631 lines / 19 KB | 301 lines / 12 KB |
| **Time** | ~5 seconds | ~3 minutes |
| **Cost** | Free | ~$0.10 Sonnet tokens |
| **Run-together words** | Left as-is: `"AmericanCeramics"`, `"Identificationand"` | Fixed: `"American Ceramics"`, `"Identification and"` |
| **Auto-generated alt text** | Left in: `"A brown and white rock Description automatically generated"` | Removed all ~50 instances |
| **Image filenames / Windows paths** | Left in | Removed |
| **Embedded image refs** | Removed (>50 block) | Removed |
| **Heading hierarchy** | Kept raw OCR: everything is `##` | Normalized: `#` for parts, `##` for sections, `###` for subsections |
| **Text flow** | Fragmented slides: one phrase per heading | Merged into flowing prose paragraphs |
| **Degree symbol** | Left as `800o Celsius` | Fixed to `800° Celsius` |
| **URLs** | Floating on their own lines | Inline parenthetical references |
| **Reading experience** | Feels like OCR output — choppy, noisy | Feels like a study guide — clean, structured |

**Takeaway:** The agent is dramatically better for PowerPoint-turned-PDFs, where the "artifacts" aren't OCR errors but structural noise (alt text, filenames, fragmented slides). The agent understands content and merges slide fragments into coherent paragraphs — something regex can never do. For RAG, the agent version produces much better embeddings since each chunk is semantically dense rather than full of noise.

The pipeline remains the right default for book-style PDFs (like the 1833 Kercheval history), where OCR errors are character-level and regex handles them well. Presentation sources benefit from an agent pass.

### Test 2: Book-style OCR — History of the Valley of Virginia (1833)

To confirm, we ran the same comparison on [historyofvalleyo00inkerc.pdf](data/pdf/historyofvalleyo00inkerc.pdf) — a 23MB digitized 1833 book, straight Tesseract OCR with no slideshow artifacts.

| Artifact | **Pipeline** | **Agent** |
|---|---|---|
| **Lines** | 8,310 | 8,242 |
| **Size** | 1,021 KB | 1,018 KB |
| **Time** | < 1 second | ~7 minutes (53 tool calls) |
| **Cost** | Free | ~$0.50 Sonnet tokens |
| Garbled front matter (`C3ENEAL`, `Sh4ke`) | Left in | Removed |
| Title page (`l/alley of l/ir^ipia`) | Left in | Fixed → `Valley of Virginia` |
| `CHAPTKR` → `CHAPTER` | 4 remaining | 0 remaining |
| `v/` → `w` | 0 remaining | 29 remaining |
| `}` as `y` (337 instances) | Not fixed | Not fixed |
| Running page headers | Removed | Removed |
| Embedded image refs (1,663) | Removed | Removed |
| Heading hierarchy | Untouched | Title promoted to h1 |
| Spurious OCR headings | Left in | Removed |

**Takeaway:** On book-style PDFs, the gap narrows dramatically. Both approaches produce ~8,300-line files within 3KB of each other. The pipeline catches patterns the agent misses (`v/` → `w`) and vice versa (`CHAPTKR`, front matter). Neither fixes the deep OCR artifacts (`}` as `y`, `3'ou` for `you`).

For RAG embedding quality, the difference is negligible — both versions are equally usable. The pipeline wins on cost (free vs ~$0.50) and speed (instant vs 7 minutes), making it the clear choice for batch processing book-style scans. The agent adds value only for structural cleanup (heading hierarchy, front matter) which matters less for chunked retrieval.

### Why Neither Approach Fixed `}` as `y`

The most stubborn artifacts — `}` for `y` (337 instances), `3'ou` for `you`, `v/` for `w` — are *character-level substitutions* specific to how Tesseract misreads particular typefaces. The 1833 Kercheval book uses a decorative typeface where Tesseract consistently reads `y` as `}`, `w` as `v/`, and `y` as `3'`. These aren't random errors; they're systematic misreadings of specific glyphs.

The pipeline only catches these if someone has manually identified the pattern and added a regex rule (we did this for `v/` → `w` but not `}` → `y`). The agent never noticed the `}` pattern at all — it read the file in chunks looking for structural problems, and a `}` buried in running prose like `"countr}"` doesn't jump out the way a garbled heading does. You'd need to grep for it, which the agent didn't think to do.

This is a known problem in OCR research. There are resources for building systematic fixes:

- [**OCR-Character-Confusion**](https://github.com/shaneweisz/OCR-Character-Confusion) — generates Tesseract confusion matrices as spreadsheets by running OCR on known text in various fonts. Produces character→misread probability tables.
- [**Early-Modern-OCR/TesseractTraining**](https://github.com/Early-Modern-OCR/TesseractTraining) — training data from the Early Modern OCR Project (eMOP), built specifically for 16th–19th century typefaces including Blackletter and Roman/Italic fonts.
- [**arXiv OCR Ground Truth dataset**](https://readingtimemachine.github.io/projects/1-ocr-groundtruth-may2023) — large dataset with confusion matrices for character and word pairs from Tesseract output.
- [Tesseract issue #1545](https://github.com/tesseract-ocr/tesseract/issues/1545) documents the `ſ` (long s) → `f` confusion in historical books — the same class of problem.

Research shows ~50% of OCR errors are character substitutions, ~30% insertions/deletions, and ~10% spacing errors ([Afli et al., 2016](https://arxiv.org/pdf/1604.06225)). The state of the art for post-correction uses confusion matrices to generate correction candidates, then LLMs to pick the right one — though a [2025 paper](https://arxiv.org/html/2502.01205v1) titled *"OCR Error Post-Correction with LLMs: No Free Lunches"* shows this remains an open problem.

For our pipeline, the practical path forward is to generate a confusion matrix from our specific corpus (align OCR output against known-good text for a few pages), extract the high-frequency substitution pairs, and add them to `ocr_cleanup.py`. This would catch the `}` → `y` class of errors that both the pipeline and agent currently miss.

## Wait, Is This Even GraphRAG?

Midway through building, we stopped and asked: what are we actually making?

Standard GraphRAG — the kind you see in Neo4j tutorials and the `neo4j-graphrag-python` package — works like this: user types a question in a search box, the question gets embedded, vector search finds relevant chunks, a Cypher query fans out from those chunks into the entity graph to collect structured context, and the LLM generates an answer. The graph is invisible infrastructure that makes retrieval better. The user never sees it.

What we'd been designing was the opposite. Our UI puts entity browsing first — the sidebar isn't decoration around a search box, it IS the search. Users click on "Monacan" and "Shenandoah Valley" and the system traverses the graph to find connections, pulls relevant source chunks via MENTIONS edges, and shows the evidence. The LLM synthesizes a summary, but the graph connections and source cards are the real product.

This isn't RAG enhanced by a graph. It's a knowledge graph explorer with optional LLM summarization.

We decided to be honest about it:

- **`main` branch**: The entity-first knowledge graph explorer. The graph is the interface.
- **`VectorCypherRetriever` branch**: Standard vanilla GraphRAG for comparison. Search box first, graph invisible, answer is the product.

Same extraction pipeline, same CIDOC-CRM schema, same Neo4j storage — different interaction models on top.

## Building the Extraction Pipeline

With the identity crisis resolved, we built the full pipeline from PDF to populated graph. The architecture:

```
PDF → kreuzberg → regex OCR cleanup → (optional) LLM cleanup → clean markdown
    → chunker (markdown-aware, heading/paragraph boundaries)
    → Claude NER (SHACL-guided, section-level, not per-chunk)
    → Claude relationship extraction (same sections, entity list as context)
    → entity resolution (exact match → fuzzy match → flag ambiguous)
    → Neo4j loading (entities, relationships, chunks, MENTIONS links)
    → nomic embeddings + vector indexes
```

Some things we learned along the way:

### The cleanup question is a false choice

We initially skipped LLM cleanup (`--llm-cleanup`) for the extraction step, reasoning that the regex pipeline was "good enough" for book-style PDFs. Then we realized: the NER step sends every section to Sonnet anyway. If Sonnet has to read through OCR garbage (`}` for `y`, `3'ou` for `you`) while also extracting entities, we're paying Sonnet prices (~$3/M input) for cleanup work that Haiku could do for a tenth of the cost.

The explicit cleanup pass costs ~$1 total and produces cleaner input for every downstream step — NER, chunking, embeddings, and eventually the user-facing source cards. We made it the default.

### Chunking OCR'd documents is tricky

Our markdown-aware chunker splits on heading boundaries first, then paragraphs, then sentences. Simple enough — except OCR'd documents create hundreds of tiny spurious headings. The 1833 Kercheval book produced 298 sections, 297 under 100 characters, because Tesseract interpreted running headers and page artifacts as `##` headings.

First pass: 1,465 chunks for one document, mostly tiny fragments. Fix: merge sections under 100 characters into their neighbors before chunking. After: 1,228 and 1,009 chunks respectively, with reasonable size distributions.

We also found a bug where the chunker mishandled documents starting with `# ` (single hash) — the preamble detection assumed any text starting with `#` was a captured regex group, misaligning all subsequent section boundaries. One document went from 298 sections to 12 chunks (losing 99% of its content). The kind of bug you only catch by actually running the pipeline on real data.

### NER at scale hits rate limits

784 sections across 2 documents, 5 concurrent API calls to Sonnet. The rate limiter kicked in immediately — 429 responses with 20-38 second retry waits. The Anthropic SDK handles retries gracefully, but the throughput dropped to a crawl.

Worse: the pipeline saves results per-document, not per-section. If the process crashes mid-document, all completed sections for that document are lost. We're fixing this to save incrementally after the current run finishes.

### GLiNER2 vs. Sonnet for NER

For pure span detection (finding entity boundaries and classifying them), GLiNER2 would work fine and costs nothing. But our NER step does more than span detection:

- **Alias grouping**: recognizing that "the Powhatan", "Wahunsenacah's confederacy", and "Powhatan Confederacy" are the same entity
- **Contextual descriptions**: generating a brief description from surrounding text
- **Coreference resolution**: resolving "they migrated south" to a specific group
- **OCR recovery**: reading `"Pov/hatan"` as "Powhatan"

The $10 API cost is paying for structured enrichment, not just NER. At scale, the hybrid approach (GLiNER2 for bulk detection, Sonnet for enrichment of ambiguous cases) would be the right call. For 2 documents, Sonnet-only is simpler.

### NER results (partial)

The NER step finished — sort of. It extracted 5,249 entities from the First Peoples document, then ran out of API credits partway through Kercheval. Worse: the credit errors started *during* the first book, not between books. 120 out of 411 sections silently failed and returned empty entity lists. The pipeline reported "5,249 entities" like everything was fine, but we're missing ~29% of the extractions.

The silent failure is a design problem. Failed sections return `[]` and get merged into the results with no warning. The per-document save (not per-section) means there's no way to know which sections succeeded without checking the logs. Both of these need fixing before the next run.

What we did get shows the approach works. 5,249 raw entity mentions across 7 types:

| Type | Count |
|---|---|
| Places | 2,180 |
| Artifacts | 913 |
| Time Periods | 849 |
| Persons | 573 |
| Sites | 493 |
| Cultural Groups | 191 |
| Events | 50 |

The entity resolution challenge is real though. "Carole Nash" appears 11 times — 3 as "Carole Nash", 7 as just "Nash", plus a false near-match "Paul Inashima". Our fuzzy matcher (SequenceMatcher > 0.85) won't merge "Nash" with "Carole Nash" because the ratio is too low. We need a substring/component-name rule: if one name is a component of another and they share the same entity type, merge them.

### Azure Document Intelligence: maybe we overengineered this

While waiting for NER to finish, we ran a head-to-head comparison between our kreuzberg + OCR cleanup pipeline and Azure Document Intelligence on the same page of the 1833 Kercheval book. The results were humbling:

| Artifact | **Azure Doc Intelligence** | **Kreuzberg + OCR cleanup** |
|---|---|---|
| `}` as `y` | Fixed | Still broken (`part}^`, `la}'^`) |
| Run-together words | Clean spacing | Smashed (`traditionaryinformation`) |
| "Smith" | Correct | `Bmith` |
| Soft hyphens | Preserved naturally | Lost or mangled |
| Spurious headings | None | Two fake `#` headings mid-paragraph |
| Image refs | None | Two `![Image]` artifacts |

Azure produced clean, readable text from a page that Tesseract mangled. No regex cleanup needed. No LLM cleanup needed. One API call.

This raised a bigger question: why are we using markdown at all? The chunker and NER splitter were built to split on `##` headings, but those headings are just kreuzberg's output format — and for OCR'd documents, they're mostly garbage (`C3ENEAL.OGY COUUECTION`, `DEOICATIOjS.`). Plain text with paragraph breaks is sufficient for chunking, NER, and embeddings. The "markdown-aware chunker" was complexity we created by treating an output format as a feature.

We're adding Azure as an optional backend (`--backend cloud` vs `--backend local`). For historical scanned documents, it's the obvious choice. Kreuzberg stays as the default for offline/free usage.

### What's next

We ran out of API credits ($0 wallet, $100 limit — the limit is how much you *can* spend, not how much you *have*). Before adding funds and re-running:

1. Fix incremental saving — per-section, not per-document, so crashes don't lose progress
2. Track failed sections so we can re-run only what's missing instead of `--force` on everything
3. Add the substring name-matching rule to entity resolution
4. Add Azure Document Intelligence as an extraction backend option
5. Then: re-run NER, relationship extraction, entity resolution, Neo4j loading, embeddings

The pipeline is built. The modules are all there. We just need money in the wallet and data in the graph.