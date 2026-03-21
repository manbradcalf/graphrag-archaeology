---
name: LLM as guide not authority
description: In RAG systems, present the LLM as a guide that helps users navigate source material, not as an authority that delivers answers. This shapes UI design, prompt engineering, and how citations are presented.
type: feedback
---

The LLM should be presented as a guide, not an authority. The temptation in RAG setups is to treat the LLM like an authority figure delivering definitive answers.

**Why:** Frontier models blend parametric knowledge (training data) with retrieved context — this is a documented architectural problem ("knowledge conflict," see ReDeEP ICLR 2025). Presenting the LLM as authoritative hides this limitation. Presenting it as a guide that surfaces and synthesizes source material puts the user in the verification seat, which is both more honest and more useful.

**How to apply:** UI should foreground the source chunks (with page numbers, highlights, document names) and present the LLM's synthesis as a navigational aid. Per-sentence citations, entity highlight toggles, and "here's what we found" framing over "here's the answer" framing. This applies to prompt design, UI copy, and how the system is described to clients.
