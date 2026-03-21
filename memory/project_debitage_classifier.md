---
name: debitage_classifier
description: Separate project to build a multi-label vision classifier for lithic debitage from photos, based on a Unifacial Debitage Decision Matrix
type: project
---

User has a separate repo and a domain expert for building a multi-label vision classifier for lithic artifact (debitage) analysis. Based on a Unifacial Debitage Decision Matrix with ~20 codes (SHT, PNT, BIF, FLA, UFL, UBL, etc.).

Key insight from discussion: this is NOT a top-down taxonomy — attributes are classified in parallel. A single artifact photo can be simultaneously FLA + TAL + EWN + PAT. This makes it a multi-label classification problem (sigmoid per label, not softmax).

**Why:** User has access to a domain expert and labeled training data (or will). Separate from the archaeology GraphRAG project.

**How to apply:** When user mentions debitage, lithic classification, or the separate classifier repo, reference this context. Don't conflate with the GraphRAG project.

**TODO for user:** Add ViT vs CNN comparison notes to the debitage classifier repo (user couldn't locate the repo as of 2026-03-20). Key points: ViT uses patch-based attention (global from layer 1), CNN uses local filter stacking (bottom-up). For small datasets (~50 per category), CNNs may be more data-efficient. Sigmoid output (not softmax) for multi-label. Remind user when they find the repo.
