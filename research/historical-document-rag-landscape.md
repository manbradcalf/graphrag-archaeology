# RAG/GraphRAG from Historical Documents: Landscape Research

*Compiled March 20, 2026*

## Is this a crowded space?

No — but it is active and growing fast. The niche of taking historical/scanned documents through OCR and into structured knowledge graphs or RAG systems sits at the intersection of several fields (digital humanities, NLP, cultural heritage informatics, knowledge engineering) that are each maturing independently. Very few projects or teams are doing the full end-to-end pipeline (scan → OCR → post-correction → entity extraction → knowledge graph → RAG/chatbot). Most work addresses one or two stages.

## Academic Research (2024-2026)

### Closest Matches

- **ATR4CH** (arXiv 2511.10354) — "Knowledge Graphs Generation from Cultural Heritage Texts: Combining LLMs and Ontological Engineering." Five-step methodology using Claude Sonnet, Llama 3.3, and GPT-4o-mini. Achieves 0.96-0.99 F1 on metadata extraction, 0.7-0.8 F1 on entity recognition. First systematic methodology for coordinating LLM-based extraction with CH ontologies. [Paper](https://arxiv.org/abs/2511.10354)

- **CIDOC CRM-Based KG Construction with LLMs** (MDPI Applied Sciences, 2025) — Integrates CIDOC-CRM v7.2 with GPT models to automatically extract structured triples, implemented in Neo4j. [Paper](https://www.mdpi.com/2076-3417/15/22/12063)

- **LLM-Driven CIDOC-CRM KG from Museum Archives** (IEEE 2025) — Case study on Museum Nasional in Jakarta. Single-stage in-context learning approach. [Paper](https://ieeexplore.ieee.org/abstract/document/11157312/)

### OCR + Historical Documents

- **Multimodal LLMs for Historical Documents** (arXiv 2504.00414) — Benchmarks Gemini 2.0 Flash and GPT-4o for OCR, post-correction, and NER on historical documents in a single pipeline. Gemini achieved 0.84% character error rate. Shows multimodal LLMs can potentially replace the traditional OCR→post-correction→NER chain with a single model call. [Paper](https://arxiv.org/abs/2504.00414)

- **OCR Post-Correction with LLMs: No Free Lunches** (arXiv 2502.01205) — Evaluating open-weight LLMs for OCR error correction on historical English and Finnish texts. Llama 2 achieved 54.51% reduction in character error rate vs. BART's 23.30%. [Paper](https://arxiv.org/html/2502.01205v1)

- **LLM Post-OCR Correction for Historical Newspapers** (ACL 2024, LT4HALA workshop) — Instruction-tuned Llama 2 on 19th century British newspaper articles. [Paper](https://aclanthology.org/2024.lt4hala-1.14/)

### Other Relevant Work

- **End-to-End Pipeline for 19th-Century Land Registry Tables** (TPDL 2025) — Deep learning extraction + Semantic Table Interpretation with domain ontology → knowledge graph from French land registry records. [Paper](https://link.springer.com/chapter/10.1007/978-3-032-05409-8_24)

- **Historical Dataset Construction from Archival Image Scans** (arXiv 2512.19675) — Multimodal LLMs on German patent records (1877-1918). [Paper](https://arxiv.org/html/2512.19675v1) / [GitHub](https://github.com/niclasgriesshaber/llm_patent_pipeline)

- **LLMs in Archaeology Survey** (MDPI Electronics, 2025) — Comprehensive review. Describes the field as "exploratory and fragmented" with "substantial potential." [Paper](https://www.mdpi.com/2079-9292/14/22/4507)

- **GPT-3 for Antiquities Trafficking KG** (PMC, 2023) — Extracts subject-predicate-object triples from newspaper articles about archaeological artifacts. [Paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC10445804/)

- **KG for Oral Historical Archives with LLM-RAG** (ACM ISDM 2024) — [Paper](https://dl.acm.org/doi/10.1145/3686397.3686420)

- **Archaeological Grey Literature NLP** — The Archaeology Data Service (ADS) has been doing NLP on grey literature for 12+ years using GATE toolkit with CIDOC-CRM and CRM-EH ontologies. Pre-LLM era. [Paper](https://www.researchgate.net/publication/235288597)

## Open Source Projects and Tools

| Project | Stars | What It Does | Gap |
|---------|-------|-------------|-----|
| **IBM Docling** | 30K+ | Document parsing (PDF, DOCX) using CV models | Not historical-document specific |
| **IBM Docling-Graph** | — | Transforms Docling output into validated KGs | General purpose, not cultural heritage |
| **Microsoft GraphRAG** | — | Dominant open-source GraphRAG framework | General purpose |
| **Impresso** | — | 200+ years of newspapers, NER, topic modeling, LLM post-correction | Newspaper-specific, not generalized |
| **Transkribus** | — | Leading historical HTR/OCR platform | Does NOT build knowledge graphs |
| **Recogito / Pelagios** | — | Annotation tool for historical place-names, linked data export | Mature but not LLM-powered |

Key gap: **Transkribus** is the dominant historical OCR platform but stops at transcription and basic NER. No knowledge graph construction.

## Companies / Commercial

- **Genealogy companies** (FamilySearch, Ancestry, MyHeritage) — biggest commercial players in historical document AI. MyHeritage released 3.4B records in Dec 2024 using AI. Proprietary, genealogy-focused, not general KGs.
- **NARA** — AI for semantic search pilot, 250M records digitized out of 13.5B pages. Not building knowledge graphs.
- **Transkribus (READ-COOP)** — Austrian cooperative. Dominant commercial platform for historical HTR/OCR.

## Relevant Conferences and Communities

| Conference | Focus | Next Edition |
|-----------|-------|-------------|
| **SemDH** (Semantic Digital Humanities) | KGs for humanities, historical text extraction, ontology adoption | Co-located with ESWC |
| **AI4LAM** (Fantastic Futures) | AI in libraries, archives, museums | 2025: British Library; 2026: Washington DC |
| **CHR** (Computational Humanities Research) | LLM applications for historical text | 2025: Luxembourg (Dec 9-12) |
| **DH** (Digital Humanities, ADHO) | Broad digital humanities | 2025: Lisbon; 2026: Daejeon |
| **LT4HALA** | Language technologies for historical/ancient languages | ACL workshop |
| **TPDL** | Theory and Practice of Digital Libraries | 2025: Tampere |
| **SWODCH** | Semantic Web for Cultural Heritage | Co-located with semantic web venues |
| **Europeana AI4Culture** | AI tools for cultural heritage data | Hackathons ongoing |

## Domain Status

| Domain | Maturity |
|--------|----------|
| **Archaeology** | Very fragmented. ADS has 12+ years of NLP with CIDOC-CRM but pre-LLM. No dominant RAG/KG solution. |
| **Genealogy** | Most commercialized. Focused on search/indexing, not knowledge graphs. |
| **Historical newspapers** | Most mature academic niche. Impresso is the flagship. |
| **Museum collections** | Active with CIDOC-CRM + LLM papers in 2025. |
| **Legal archives** | NARA doing AI search pilots. Not well-developed for historical records. |

## The Opportunity

What exists: good tools for individual stages. What's missing: **no one is assembling the full stack for historical/archaeological documents.** A well-executed open-source project combining OCR post-correction with ontology-guided knowledge graph construction for historical documents (especially archaeological grey literature) would be genuinely novel.
