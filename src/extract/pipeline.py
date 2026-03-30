"""
PDF extraction and cleanup pipeline.

Extracts PDFs to markdown via kreuzberg, applies regex-based OCR cleanup,
and optionally runs LLM-based cleanup via Claude Haiku.
"""

import asyncio
from pathlib import Path

from src.extract.ocr_cleanup import clean_ocr_text
from src.extract.pdf_extract import extract_two_column


def extract_all(
    pdf_dir: Path = Path("data/pdf"),
    output_dir: Path = Path("data/md"),
    *,
    skip_existing: bool = True,
    regex_cleanup: bool = True,
    cleanup: bool = False,
) -> list[Path]:
    """Extract all PDFs in a directory to cleaned markdown.

    Args:
        pdf_dir: Directory containing PDF files.
        output_dir: Directory to write markdown output.
        skip_existing: Skip PDFs that already have output files.
        regex_cleanup: Apply general OCR regex cleanup.
        cleanup: Apply LLM-based cleanup (costs money).

    Returns:
        List of output file paths that were written.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {pdf_dir}")
        return []

    print(f"Found {len(pdfs)} PDFs in {pdf_dir}")
    outputs: list[Path] = []

    for pdf_path in pdfs:
        output_path = output_dir / pdf_path.with_suffix(".md").name

        if skip_existing and output_path.exists():
            print(f"  Skipping {pdf_path.name} (already extracted)")
            continue

        print(f"  Extracting {pdf_path.name}...")
        try:
            text = extract_two_column(pdf_path)
        except Exception as e:
            print(f"  ERROR extracting {pdf_path.name}: {e}")
            continue

        if regex_cleanup:
            text = clean_ocr_text(text)

        if cleanup:
            # Write intermediate file first, then run LLM cleanup on it
            output_path.write_text(text, encoding="utf-8")
            try:
                from src.extract.cleanup import cleanup_file

                asyncio.run(cleanup_file(output_path))
            except Exception as e:
                print(f"  WARNING: LLM cleanup failed for {pdf_path.name}: {e}")
                # The regex-cleaned version is already written, so we continue
        else:
            output_path.write_text(text, encoding="utf-8")

        print(f"  Wrote {output_path}")
        outputs.append(output_path)

    print(f"\nDone. Extracted {len(outputs)} new files.")
    return outputs
