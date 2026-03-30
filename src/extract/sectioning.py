"""Page-based document sectioning.

Splits markdown with <!-- PAGE N --> markers into sections identified by
page number. Merges small pages and splits oversized ones at paragraph
boundaries so each section stays within a target size range.
"""

from __future__ import annotations

import re

_PAGE_MARKER_RE = re.compile(r"<!--\s*PAGE\s+(\d+)\s*-->", re.IGNORECASE)


def split_by_pages(
    text: str,
    min_chars: int = 1000,
    max_chars: int = 5000,
    target_chars: int = 3500,
) -> list[tuple[str, str]]:
    """Split page-marked markdown into (section_id, text) tuples.

    Args:
        text: Markdown with <!-- PAGE N --> markers from kreuzberg.
        min_chars: Pages shorter than this get merged with the next page.
        max_chars: Pages longer than this get split at paragraph boundaries.
        target_chars: Target size when splitting oversized pages.

    Returns:
        List of (section_id, section_text) tuples where section_id is
        like "page-1", "page-1-2" (merged), or "page-3_part0" (split).
    """
    markers = list(_PAGE_MARKER_RE.finditer(text))

    if not markers:
        # No page markers — treat whole text as one section
        return [("page-1", text.strip())]

    # Build raw (page_num, text) pairs
    raw_pages: list[tuple[int, str]] = []
    for i, m in enumerate(markers):
        page_num = int(m.group(1))
        start = m.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        page_text = text[start:end].strip()
        if page_text:
            raw_pages.append((page_num, page_text))

    if not raw_pages:
        return [("page-1", text.strip())]

    # Merge small pages, split large ones
    merged: list[tuple[str, str]] = []
    buf_id: str = ""
    buf_text: str = ""
    buf_start_page: int = 0

    for page_num, page_text in raw_pages:
        if buf_text:
            combined = buf_text + "\n\n" + page_text
            if len(combined) <= max_chars:
                buf_text = combined
                buf_id = f"page-{buf_start_page}-{page_num}"
                continue
            else:
                merged.append((buf_id, buf_text))
                buf_id = ""
                buf_text = ""

        if len(page_text) < min_chars:
            buf_start_page = page_num
            buf_id = f"page-{page_num}"
            buf_text = page_text
        elif len(page_text) > max_chars:
            subsections = _split_by_paragraphs(
                page_text, f"page-{page_num}", target_chars
            )
            merged.extend(subsections)
        else:
            merged.append((f"page-{page_num}", page_text))

    # Flush remaining buffer
    if buf_text:
        if merged:
            last_id, last_text = merged[-1]
            combined = last_text + "\n\n" + buf_text
            if len(combined) <= max_chars:
                merged[-1] = (last_id, combined)
            else:
                merged.append((buf_id, buf_text))
        else:
            merged.append((buf_id, buf_text))

    return merged


def _split_by_paragraphs(
    text: str,
    base_id: str,
    target_chars: int,
) -> list[tuple[str, str]]:
    """Split text into sections at paragraph boundaries."""
    paragraphs = re.split(r"\n\n+", text)
    sections: list[tuple[str, str]] = []
    current: list[str] = []
    current_len = 0
    idx = 0

    for para in paragraphs:
        para_len = len(para)
        if current and current_len + para_len > target_chars:
            sections.append((f"{base_id}_part{idx}", "\n\n".join(current)))
            idx += 1
            current = []
            current_len = 0
        current.append(para)
        current_len += para_len + 2

    if current:
        sections.append((f"{base_id}_part{idx}", "\n\n".join(current)))

    return sections
