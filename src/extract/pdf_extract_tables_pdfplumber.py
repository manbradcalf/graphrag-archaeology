import pdfplumber


TABLE_SETTINGS = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
    "min_words_vertical": 3,
    "min_words_horizontal": 1,
    "text_x_tolerance": 3,
    "text_y_tolerance": 3,
    "snap_x_tolerance": 5,
    "snap_y_tolerance": 5,
    "join_x_tolerance": 5,
    "join_y_tolerance": 5,
}


def merge_multiline_rows(table: list[list[str]]) -> list[list[str]]:
    """Merge rows where first cell is empty (continuation of previous row)."""
    merged = []
    for row in table:
        if merged and (not row[0] or row[0].strip() == ""):
            for i, cell in enumerate(row):
                if cell and cell.strip():
                    prev = merged[-1][i] or ""
                    merged[-1][i] = f"{prev} {cell.strip()}" if prev else cell.strip()
        else:
            merged.append([c.strip() if c else "" for c in row])
    return merged


def main() -> None:
    pdf_path = "../../pdfs/The-Archaeology-Of-Virginias-First-Peoples.pdf"

    with pdfplumber.open(pdf_path) as pdf:
        print(f"Total pages: {len(pdf.pages)}")

        table_count = 0
        for page in pdf.pages:
            tables = page.extract_tables(TABLE_SETTINGS)
            if not tables:
                continue

            for table in tables:
                page.to_image().debug_tablefinder(TABLE_SETTINGS).save("debug.png")

                table = merge_multiline_rows(table)
                table_count += 1
                print(f"\n--- Table {table_count} (page {page.page_number}) ---")
                for row in table:
                    cells = [cell if cell else "" for cell in row]
                    print(" | ".join(cells))

        print(f"\nTotal tables found: {table_count}")


main()
