---
name: Digitized 19th-century book OCR patterns
description: Artifacts and cleanup strategies for digitized historical books (1800s) processed by Tesseract OCR in this project
type: project
---

Digitized 19th-century books processed through kreuzberg/Tesseract OCR from Internet Archive scans produce a distinctive set of artifacts. Documented from "A History of the Valley of Virginia" (Kercheval, 1833).

**Why:** These are multi-column, double-page spread PDFs. Tesseract reads across both columns and page headers simultaneously, mixing running headers and footnotes into the body text.

**How to apply:** When cleaning these files, expect and remove:

1. **Scan cover noise** — The first 10–15 lines are library catalog OCR noise from the book cover/scan metadata (barcodes, catalog numbers, Internet Archive digitization lines). Remove entirely.

2. **Running page headers as ## headings** — Every page has a running header like "INTRODUCTION." (left page) and "xv" or "33" (right page). Tesseract extracts these as standalone lines, often wrapped in ## by kreuzberg. Two formats appear:
   - `## CHAPTER TITLE. 33`  (page number suffix)
   - `## CHAPTER TITLE. xv`  (roman numeral suffix)
   - `vi INTRODUCTION.`  (roman numeral prefix, no ##)
   - `32 INDIAN WARS.`  (arabic prefix, no ##)
   - `CHAPTER TITLE. 33`  (no prefix, standalone)
   All must be removed.

3. **Massive embedded image block at end** — kreuzberg appends all page scan images at the bottom as `![Image N (page P)](embedded:pP_iN)` references, one per image, ~830+ items (two images per page for a 400-page book). Remove the entire block starting from `![Image 0 (page 1)](embedded:p1_i0)`.

4. **OCR ligature/character errors in ALL-CAPS headings** — Tesseract struggles with large decorative caps: `lv` → `V`, `I` → `l`, `K` → `K`, `G` → `G` etc. Common patterns seen:
   - `VAIvLEY` / `VALIvEY` / `VAEEEY` → `VALLEY`
   - `SETTlvEMENT` / `SETTI.KMENT` → `SETTLEMENT`
   - `REI.IGION` / `REUGION` → `RELIGION`
   - `CHAPTKR` → `CHAPTER`
   - `THK` → `THE`
   - `OP` for `OF` in headings

5. **Spurious ## headings from OCR noise** — Some decorative printer's marks and stray characters get extracted and wrapped in ##: `## JduL`, `## JuaL`, `## H`, `## 'f`, `## ^;^®=^`, `## H/^-`. These are ornamental flourishes (printer's flowers) between sections, not content.

6. **Long-s typography** — The book uses 18th-century typography with `f` for `ſ` (long s). This appears in words like `fatisfaction`, `fervice`, `fubject`. These are authentic period typography, NOT errors — do not "fix" them. The author writes in standard 19th-century style but quotes earlier 18th-century documents that use the long-s.

7. **Paragraph fragmentation** — OCR reads across two-column layout, causing mid-sentence line breaks. These appear as isolated sentence fragments. Difficult to auto-fix without risking content corruption; leave for manual review or accept as is.

8. **Footnote markers** — The book uses *, †, ‡, §, ¶, ‖ for footnotes. Tesseract renders these as *, f, X, §, %, il etc. Footnote content appears mixed into body paragraphs. These are authentic document features; preserve as-is.

**Effective strategy:**
- Two-pass cleanup: (1) structural noise removal (cover, running headers, image block), (2) heading OCR fixes.
- Use Python script for systematic header removal — there are 100–200 running headers in a 400-page book.
- Do NOT attempt to auto-rejoin paragraphs — the risk of incorrect merges is too high.
- Preserved file size reduction: removing image block alone saves ~1700 lines (17% of total).
