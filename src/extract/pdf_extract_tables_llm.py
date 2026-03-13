import base64
import io
import json
import time

import anthropic
import pdfplumber


def page_to_base64(page: pdfplumber.pdf.Page, resolution: int = 150) -> tuple[str, str]:
    img = page.to_image(resolution=resolution)
    buffer = io.BytesIO()
    img.original.save(buffer, format="JPEG")
    return base64.standard_b64encode(buffer.getvalue()).decode("utf-8"), "image/jpeg"


PROMPT = """Extract all tables from this PDF page as JSON.

For each table, return:
- "title": the table caption/title if visible
- "headers": list of column header strings
- "rows": list of rows, each row is a list of cell strings

Merge multi-line cells into single strings (e.g. a date with its calibration on the next line).

If there are no tables on this page, return an empty list.

Return ONLY valid JSON, no markdown fences. Format: [{"title": "...", "headers": [...], "rows": [[...], ...]}, ...]"""


def extract_tables_from_page(
    client: anthropic.Anthropic, image_b64: str, media_type: str
) -> list[dict]:
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
    )
    text = response.content[0].text
    return json.loads(text)


def main() -> None:
    pdf_path = "pdfs/The-Archaeology-Of-Virginias-First-Peoples.pdf"
    client = anthropic.Anthropic()

    with pdfplumber.open(pdf_path) as pdf:
        print(f"Total pages: {len(pdf.pages)}")

        all_tables = []
        for page in pdf.pages:
            print(f"Processing page {page.page_number}...", end=" ", flush=True)

            try:
                image_b64, media_type = page_to_base64(page)
                tables = extract_tables_from_page(client, image_b64, media_type)
            except (anthropic.APIError, json.JSONDecodeError) as e:
                print(f"error: {e}")
                time.sleep(2)
                continue

            if tables:
                print(f"found {len(tables)} table(s)")
                for table in tables:
                    table["page"] = page.page_number
                    all_tables.append(table)

                    print(f"  -> {table.get('title', 'Untitled')}")
                    for header in table.get("headers", []):
                        print(f"     {header}", end=" | ")
                    print()
                    for row in table.get("rows", [])[:3]:
                        print(f"     {row}")
                    if len(table.get("rows", [])) > 3:
                        print(f"     ... ({len(table['rows'])} rows total)")
            else:
                print("no tables")

        print(f"\nTotal tables found: {len(all_tables)}")

        output_path = "extracted_tables.json"
        with open(output_path, "w") as f:
            json.dump(all_tables, f, indent=2)
        print(f"Saved to {output_path}")


main()
