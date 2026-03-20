"""
General regex-based OCR cleanup for text extracted from scanned documents.

These patterns fix common Tesseract/OCR artifacts that appear across many
documents. Document-specific fixes do NOT belong here.
"""

import re


def clean_ocr_text(text: str) -> str:
    """Apply general OCR cleanup patterns to extracted text.

    Fixes common artifacts from Tesseract OCR including control characters,
    trailing image blocks, running page headers, page numbers, and character
    misreads that occur across many scanned documents.

    Args:
        text: Raw markdown text extracted from a scanned PDF.

    Returns:
        Cleaned text with common OCR artifacts removed.
    """
    # 1. Remove control characters (keep \n, \t)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    # 2. Remove trailing image reference blocks (only large blocks, >50 refs)
    #    Pattern: ![Image N (page P)](embedded:...)
    first_img = text.find('\n![Image ')
    if first_img > 0:
        img_block = text[first_img:]
        img_count = len(re.findall(r'!\[Image \d+', img_block))
        if img_count > 50:
            text = text[:first_img].rstrip() + '\n'

    # 3. Remove running page headers
    # Pattern A: ## SECTION NAME. roman_numeral (e.g., "## INTRODUCTION. xii")
    text = re.sub(
        r'\n## [A-Z][A-Z .]+\. {1,3}[xivlXIVL]+\n',
        '\n',
        text,
    )
    # Pattern B: arabic_numeral SECTION NAME. (e.g., "32 INDIAN WARS.")
    text = re.sub(
        r'\n\d{1,3} [A-Z][A-Z\' ]+\.\n',
        '\n',
        text,
    )
    # Pattern C: ## SECTION NAME. arabic_numeral (e.g., "## INDIAN WARS. 33")
    text = re.sub(
        r'\n## [A-Z][A-Z\' ]+\. \d{1,3}\n',
        '\n',
        text,
    )

    # 4. Remove standalone page numbers (line is just 1-3 digits)
    text = re.sub(r'(?m)^\d{1,3}\.?\s*$', '', text)

    # 5. Remove standalone roman numeral running heads
    #    e.g., "vi INTRODUCTION." or "xii PREFACE."
    text = re.sub(r'(?m)^[xivlXIVL]{1,6} [A-Z]+\.\s*$', '', text)
    text = re.sub(r'(?m)^[xivlXIVL]{1,6} [A-Z]+ [A-Z]+\.\s*$', '', text)

    # 6. Fix v/ -> w (OCR of 'w' in italic/old type)
    text = text.replace('v/', 'w')

    # 7. Fix vv -> w, Vv -> W
    text = text.replace('Vv', 'W')
    text = text.replace('vv', 'w')

    # 8. Fix \' -> ' (backslash-apostrophe artifact)
    text = text.replace("\\'", "'")

    # 9. Fix backslash-hyphen mid-word: remove \- between lowercase letters
    text = re.sub(r'([a-z])\\\-([a-z])', r'\1\2', text)
    # Broader variant with optional spaces
    text = re.sub(r'([A-Za-z])\s*\\\s*-\s*([A-Za-z])', r'\1\2', text)

    # 10. Fix -yy word endings -> -y (safe for English: -yy is almost never correct)
    text = re.sub(r'([a-zA-Z])yy\b', r'\1y', text)

    # 11. Normalize whitespace
    # Remove trailing spaces on lines
    text = re.sub(r'[ \t]+\n', '\n', text)
    # Collapse more than 2 consecutive blank lines to 2
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    # Ensure file ends with single newline
    text = text.rstrip('\n') + '\n'

    return text
