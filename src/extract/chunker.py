"""Markdown-aware text chunker for archaeological documents.

Splits cleaned markdown into overlapping chunks that respect document
structure: heading boundaries first, then paragraph boundaries, then
sentence boundaries as a last resort. Never splits mid-sentence or
separates a heading from its first paragraph.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Matches "## Heading" or "### Heading" at the start of a line.
_HEADING_RE = re.compile(r"^(#{2,3})\s+(.+)", re.MULTILINE)

# Sentence boundary: period followed by one or more spaces then an uppercase letter.
_SENTENCE_RE = re.compile(r"(?<=\.\s)(?=[A-Z])")


@dataclass
class TextChunk:
    chunk_id: str  # stable ID: "{doc_slug}-{chunk_index:04d}"
    text: str  # the chunk text
    document_name: str  # source document filename (without extension)
    section_heading: str  # nearest heading above this chunk
    chunk_index: int  # sequential index within the document


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, body) pairs.

    The first section may have an empty heading if the document starts
    with body text before any heading.
    """
    parts = _HEADING_RE.split(text)
    sections: list[tuple[str, str]] = []

    # parts[0] is always the text before the first regex match (preamble)
    preamble = parts[0].strip()
    if preamble:
        sections.append(("", preamble))

    # Each heading match produces 3 parts: level, title, then body until next heading
    i = 1
    while i + 2 < len(parts):
        _level = parts[i]
        title = parts[i + 1].strip()
        body = parts[i + 2].strip()
        sections.append((title, body))
        i += 3

    return sections


def _split_paragraphs(text: str) -> list[str]:
    """Split text on double-newline paragraph boundaries."""
    return [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]


def _split_sentences(text: str) -> list[str]:
    """Split text on sentence boundaries (". " followed by uppercase)."""
    parts = _SENTENCE_RE.split(text)
    return [s.strip() for s in parts if s.strip()]


def _merge_pieces(
    pieces: list[str],
    max_chars: int,
    overlap_chars: int,
    heading: str,
) -> list[str]:
    """Merge a list of text pieces into chunks respecting max_chars with overlap."""
    chunks: list[str] = []
    current = ""

    for piece in pieces:
        candidate = f"{current}\n\n{piece}".strip() if current else piece
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
                # Build overlap from the tail of the chunk just finished
                overlap = current[-overlap_chars:] if overlap_chars else ""
                # Start next chunk with overlap context
                current = f"{overlap}\n\n{piece}".strip() if overlap else piece
            else:
                # Single piece exceeds max_chars — try sentence splitting
                sentences = _split_sentences(piece)
                if len(sentences) > 1:
                    sub_chunks = _merge_pieces(sentences, max_chars, overlap_chars, heading)
                    chunks.extend(sub_chunks[:-1])
                    current = sub_chunks[-1] if sub_chunks else ""
                else:
                    # Irreducible large block — keep it whole rather than split mid-sentence
                    chunks.append(piece)
                    current = ""

    if current:
        chunks.append(current)

    return chunks


def _merge_small_sections(
    sections: list[tuple[str, str]], min_chars: int = 100
) -> list[tuple[str, str]]:
    """Merge tiny sections (OCR artifacts, bare headings) into neighbors.

    Sections shorter than min_chars are appended to the previous section,
    or prepended to the next if there is no previous.
    """
    if not sections:
        return sections
    merged: list[tuple[str, str]] = []
    for heading, body in sections:
        full = f"## {heading}\n\n{body}" if heading else body
        if len(full.strip()) < min_chars and merged:
            # Append to previous section's body
            prev_heading, prev_body = merged[-1]
            merged[-1] = (prev_heading, f"{prev_body}\n\n{full}".strip())
        else:
            merged.append((heading, body))
    # Final pass: if the first section is still tiny, merge into second
    if len(merged) > 1:
        first_full = f"## {merged[0][0]}\n\n{merged[0][1]}" if merged[0][0] else merged[0][1]
        if len(first_full.strip()) < min_chars:
            h2, b2 = merged[1]
            merged[1] = (h2, f"{first_full}\n\n{b2}".strip())
            merged = merged[1:]
    return merged


def chunk_document(
    text: str,
    document_name: str,
    max_chars: int = 1500,
    overlap_chars: int = 200,
    min_chunk_chars: int = 100,
) -> list[TextChunk]:
    """Chunk a markdown document into overlapping TextChunks.

    Algorithm:
        1. Split on heading boundaries (## and ###).
        2. Merge tiny sections (< min_chunk_chars) into neighbors.
        3. If a section fits within max_chars, emit it as one chunk.
        4. If a section exceeds max_chars, split on paragraph boundaries.
        5. If a paragraph still exceeds max_chars, split on sentence boundaries.
        6. Never split mid-sentence; never split a heading from its first paragraph.
        7. Overlap: when splitting within a section, prepend ~overlap_chars from
           the end of the previous chunk to the start of the next.
    """
    sections = _split_sections(text)
    sections = _merge_small_sections(sections, min_chunk_chars)
    chunks: list[TextChunk] = []

    for heading, body in sections:
        # Prefix the heading to the body so it stays with the first paragraph
        section_text = f"## {heading}\n\n{body}" if heading else body

        if len(section_text) <= max_chars:
            raw_chunks = [section_text]
        else:
            paragraphs = _split_paragraphs(body)
            # Attach heading to the first paragraph
            if heading and paragraphs:
                paragraphs[0] = f"## {heading}\n\n{paragraphs[0]}"
            raw_chunks = _merge_pieces(paragraphs, max_chars, overlap_chars, heading)

        for raw in raw_chunks:
            idx = len(chunks)
            chunks.append(
                TextChunk(
                    chunk_id=f"{document_name}-{idx:04d}",
                    text=raw,
                    document_name=document_name,
                    section_heading=heading,
                    chunk_index=idx,
                )
            )

    return chunks


def chunk_file(
    md_path: Path,
    max_chars: int = 1500,
    overlap_chars: int = 200,
) -> list[TextChunk]:
    """Read a markdown file and chunk it.

    Derives document_name from the filename stem (without extension).
    """
    text = md_path.read_text(encoding="utf-8")
    document_name = md_path.stem
    return chunk_document(text, document_name, max_chars, overlap_chars)
