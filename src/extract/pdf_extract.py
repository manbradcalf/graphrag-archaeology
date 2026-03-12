import asyncio

from kreuzberg import ExtractionConfig, extract_file


async def main() -> None:
    config = ExtractionConfig(use_cache=True, enable_quality_processing=True)
    result = await extract_file(
        "pdfs/The-Historical-Archaeology-of-Virginia-From-Initial-Settlement-to-the-Present.pdf",
        config=config,
    )
    print(result.content)


asyncio.run(main())
