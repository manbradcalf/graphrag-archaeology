from pathlib import Path

import pdfplumber
from kreuzberg import ExtractionConfig, OutputFormat, extract_file_sync


def extract_via_kreuzberg(pdf_path):
    config = ExtractionConfig(
        output_format=OutputFormat.MARKDOWN,
        include_document_structure=True,
    )
    result = extract_file_sync(Path(pdf_path), config=config)
    return result.content


def extract(pdf_path):
    pages_text = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            pages_text.append(page.extract_text())

    return "\n\n".join(pages_text)


def extract_two_column(pdf_path, column_split=0.5):
    pages_text = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            width = page.width
            mid = width * column_split

            left = page.crop((0, 0, mid, page.height))
            right = page.crop((mid, 0, width, page.height))

            left_text = left.extract_text() or ""
            right_text = right.extract_text() or ""

            pages_text.append(left_text + "\n\n" + right_text)

    return "\n\n".join(pages_text)
