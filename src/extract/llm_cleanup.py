"""
LLM-based OCR cleanup using Claude Haiku.

Sends overlapping chunks to the API for fixing run-together words,
page-break truncation, and stray OCR punctuation.
"""

import asyncio
import os
import shutil
import time
from pathlib import Path

import anthropic

SYSTEM_PROMPT = """\
You are an OCR post-processing assistant. Fix remaining OCR artifacts in text \
extracted from scanned documents.

Rules:
1. DO NOT rewrite or paraphrase. Preserve original spelling, grammar, \
capitalization, and style exactly as intended by the original author.
2. Fix ONLY:
   - Run-together words (e.g. "informedthe" → "informed the")
   - Stray OCR punctuation (^, *, random dots within words)
   - Truncated words at page breaks (only if repair is certain)
3. Preserve all markdown formatting (headers, blank lines, etc.) exactly.
4. Return ONLY the corrected text. No commentary, no explanations, no wrapping."""

USER_PROMPT_TEMPLATE = """\
Fix OCR artifacts in this chunk. Return ONLY the corrected text, nothing else.

```
{chunk_text}
```"""


def _get_api_key() -> str:
    """Get the Anthropic API key from environment variables."""
    # Try dotenv if available
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY_SF_PM")
    if not key:
        raise RuntimeError(
            "No API key found. Set ANTHROPIC_API_KEY or ANTHROPIC_API_KEY_SF_PM."
        )
    return key


def _split_into_chunks(
    lines: list[str], chunk_size: int, overlap: int
) -> list[tuple[int, int]]:
    """Return (start, end) index pairs for overlapping chunks."""
    chunks = []
    i = 0
    while i < len(lines):
        end = min(i + chunk_size, len(lines))
        chunks.append((i, end))
        i += chunk_size - overlap
        if i >= len(lines):
            break
    return chunks


async def _process_chunk(
    client: anthropic.AsyncAnthropic,
    lines: list[str],
    start: int,
    end: int,
    chunk_idx: int,
    total: int,
    semaphore: asyncio.Semaphore,
    model: str,
) -> tuple[int, list[str]]:
    """Send a chunk to the API and return cleaned lines."""
    chunk_text = "\n".join(lines[start:end])

    async with semaphore:
        print(f"  LLM chunk {chunk_idx + 1}/{total} (lines {start + 1}-{end})...")
        for attempt in range(3):
            try:
                response = await client.messages.create(
                    model=model,
                    max_tokens=8192,
                    system=SYSTEM_PROMPT,
                    messages=[
                        {
                            "role": "user",
                            "content": USER_PROMPT_TEMPLATE.format(
                                chunk_text=chunk_text
                            ),
                        }
                    ],
                )
                result_text = response.content[0].text
                # Strip markdown code fences if the model wraps the output
                if result_text.startswith("```"):
                    result_lines = result_text.split("\n")
                    if result_lines[0].startswith("```"):
                        result_lines = result_lines[1:]
                    if result_lines and result_lines[-1].strip().startswith("```"):
                        result_lines = result_lines[:-1]
                    result_text = "\n".join(result_lines)

                cleaned_lines = result_text.split("\n")
                return chunk_idx, cleaned_lines
            except anthropic.RateLimitError:
                wait = 2 ** (attempt + 1)
                print(f"  Rate limited on chunk {chunk_idx + 1}, waiting {wait}s...")
                await asyncio.sleep(wait)
            except Exception as e:
                if attempt < 2:
                    print(f"  Error on chunk {chunk_idx + 1}: {e}, retrying...")
                    await asyncio.sleep(2)
                else:
                    print(f"  Failed chunk {chunk_idx + 1} after 3 attempts: {e}")
                    return chunk_idx, lines[start:end]

    # Fallback: return original
    return chunk_idx, lines[start:end]


def _reassemble(
    chunk_ranges: list[tuple[int, int]],
    cleaned_chunks: dict[int, list[str]],
    chunk_size: int,
    overlap: int,
) -> list[str]:
    """Reassemble cleaned chunks, using non-overlapping portions."""
    result: list[str] = []
    for i, (_start, _end) in enumerate(chunk_ranges):
        chunk_lines = cleaned_chunks[i]

        if i == 0:
            if i + 1 < len(chunk_ranges):
                take = min(len(chunk_lines), chunk_size - overlap)
                result.extend(chunk_lines[:take])
            else:
                result.extend(chunk_lines)
        elif i == len(chunk_ranges) - 1:
            skip = overlap if len(chunk_lines) > overlap else 0
            result.extend(chunk_lines[skip:])
        else:
            skip = overlap
            take = chunk_size - overlap
            if len(chunk_lines) > skip:
                result.extend(chunk_lines[skip : skip + take])
            else:
                result.extend(chunk_lines[min(skip, len(chunk_lines)):])

    return result


async def llm_cleanup_file(
    input_path: Path,
    output_path: Path | None = None,
    *,
    model: str = "claude-haiku-4-5-20251001",
    chunk_size: int = 100,
    overlap: int = 5,
    max_concurrent: int = 10,
    backup: bool = True,
) -> Path:
    """Run LLM-based OCR cleanup on a markdown file.

    Args:
        input_path: Path to the markdown file to clean.
        output_path: Where to write output. Defaults to overwriting input.
        model: Anthropic model to use.
        chunk_size: Lines per chunk sent to the API.
        overlap: Lines of overlap between chunks.
        max_concurrent: Max parallel API requests.
        backup: Whether to create a .bak backup before overwriting.

    Returns:
        Path to the output file.
    """
    if output_path is None:
        output_path = input_path

    api_key = _get_api_key()
    start_time = time.time()

    text = input_path.read_text(encoding="utf-8")
    original_lines = text.split("\n")
    print(f"  LLM cleanup: {len(original_lines)} lines ({len(text):,} chars)")

    if backup and output_path == input_path:
        backup_path = input_path.with_suffix(".md.bak")
        shutil.copy2(input_path, backup_path)

    chunk_ranges = _split_into_chunks(original_lines, chunk_size, overlap)
    print(f"  Split into {len(chunk_ranges)} chunks")

    client = anthropic.AsyncAnthropic(api_key=api_key)
    semaphore = asyncio.Semaphore(max_concurrent)

    tasks = [
        _process_chunk(
            client, original_lines, start, end, i, len(chunk_ranges), semaphore, model
        )
        for i, (start, end) in enumerate(chunk_ranges)
    ]

    results = await asyncio.gather(*tasks)
    cleaned_chunks = {idx: lines for idx, lines in results}

    cleaned_lines = _reassemble(chunk_ranges, cleaned_chunks, chunk_size, overlap)
    cleaned_text = "\n".join(cleaned_lines)

    output_path.write_text(cleaned_text, encoding="utf-8")

    elapsed = time.time() - start_time
    print(f"  LLM cleanup done in {elapsed:.1f}s ({len(cleaned_text):,} chars)")

    return output_path
