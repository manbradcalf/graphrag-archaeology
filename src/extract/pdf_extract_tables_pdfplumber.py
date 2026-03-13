import pdfplumber


def main() -> None:
    pdf_path = "pdfs/The-Archaeology-Of-Virginias-First-Peoples.pdf"

    with pdfplumber.open(pdf_path) as pdf:
        print(f"Total pages: {len(pdf.pages)}")

        table_count = 0
        for page in pdf.pages:
            tables = page.extract_tables()
            if not tables:
                continue

            for table in tables:
                table_count += 1
                print(f"\n--- Table {table_count} (page {page.page_number}) ---")
                for row in table:
                    cells = [cell if cell else "" for cell in row]
                    print(" | ".join(cells))

        print(f"\nTotal tables found: {table_count}")


main()
