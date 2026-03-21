---
name: PowerPoint-to-PDF extraction patterns
description: Artifacts and cleanup strategies specific to PowerPoint-turned-PDF files processed by Tesseract OCR in this project
type: project
---

PowerPoint-turned-PDF files processed through kreuzberg/Tesseract OCR produce a distinctive set of artifacts that require aggressive cleanup.

**Why:** PowerPoint slide decks are not linear documents — they have floating text boxes, image captions, speaker notes, and visual labels that OCR extracts in reading order alongside body text. The result is heavy interleaving of "real" content with slide decoration.

**How to apply:** When cleaning these files, expect and remove:

1. **Merged heading words** — PowerPoint text box text often runs together without spaces (e.g., "AmericanCeramics", "Identificationand"). Always split on obvious word boundaries.

2. **Image filename artifacts** — OCR picks up image file names embedded in slide layouts (e.g., "cord marked 4", "firing 1", "dogbane7 Dogbane10", "holmes notes holmes"). These are OCR'd filenames used as image references inside the PPT, not content.

3. **Auto-generated alt-text lines** — Microsoft 365 adds auto-alt-text to images; Tesseract extracts these as body text (e.g., "A brown and white rock Description automatically generated with medium confidence"). Remove all such lines — they are not document content.

4. **Windows file paths** — Slides may contain embedded `C:\Users\...\filename.jpg` paths from the original author's machine. Remove these.

5. **Wikipedia-style image filename strings** — OCR picks up URL-encoded Wikipedia image names used in slides (e.g., `180px-Chenopodiumberlandieri`, `180px-Iva_annua_%28USDA%29`). These are image labels, not text content.

6. **Duplicate content from table extraction** — The extractor sometimes produces both a broken table version and a clean bullet-list version of the same content. The table is usually more broken; the list version is more faithful. Keep whichever is cleaner.

7. **Massive embedded image block at end** — Tesseract/kreuzberg appends all extracted `embedded:` image references at the bottom in a large block (100–170 items is typical). These reference unrenderable embedded blobs. Remove the entire block.

8. **`°` rendered as `o`** — Degree symbols in temperatures (e.g., `800o Celsius`) should be restored to `800° Celsius`.

9. **Slide section labels as h2/h3** — Many `##` headings are just slide visual labels (image captions), not actual section headings. Distinguish content headings from visual decorators by context.

10. **Bare URLs as standalone lines** — URLs from slide hyperlinks appear as isolated lines; convert to inline references or list items rather than floating lines.

**Effective strategy:** Treat this as a two-pass cleanup. First pass: remove all noise (alt-text lines, file paths, image filename tokens, embedded image block). Second pass: reconstruct structure (fix merged words, normalize headings, restore lists, clean tables).
