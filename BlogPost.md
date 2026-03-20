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