import asyncio
from kreuzberg import extract_file, ExtractionConfig, PageConfig


async def main() -> None:
    config = ExtractionConfig(
        pages=PageConfig(extract_pages=True, insert_page_markers=True)
    )
    result = await extract_file(
        "pdfs/The-Archaeology-Of-Virginias-First-Peoples.pdf", config=config
    )

    import re

    target = 97
    pages = re.split(r"<!-- PAGE (\d+) -->", result.content)
    # pages alternates: [pre-first-marker, "1", page1_text, "2", page2_text, ...]
    for i in range(1, len(pages), 2):
        if int(pages[i]) == target:
            print(f"--- Page {target} ---")
            print(pages[i + 1].strip())
            break
    else:
        print(f"Page {target} not found")


asyncio.run(main())
