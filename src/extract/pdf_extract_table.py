from kreuzberg import extract_file_sync, ExtractionConfig, PageConfig


def main() -> None:
    config = ExtractionConfig(
        pages=PageConfig(extract_pages=True, insert_page_markers=True),
        include_document_structure=True,
    )
    result = extract_file_sync(
        "pdfs/The-Archaeology-Of-Virginias-First-Peoples.pdf", config=config
    )

    print(result)

    content: str = result.content

    table_count: int = len(result.tables)
    metadata: dict = result.metadata

    print(f"Content length: {len(content)} characters")
    print(f"Tables: {table_count}")
    print(f"Metadata keys: {list(metadata.keys())}")

    # # Access the document tree
    # if result.document:
    #     for node in result.document["nodes"]:
    #         node_type = node["content"]["node_type"]
    #         text = node["content"].get("text", "")
    #         print(f"[{node_type}] {text[:80]}")


main()
