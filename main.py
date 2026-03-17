from src.extract.pdf_extract import extract_two_column
from pathlib import Path


def main():
    pdf_path = Path("data/The-Archaeology-of-Virginias-First-Peoples.pdf")
    output_path = pdf_path.with_suffix(".md")
    text = extract_two_column(pdf_path, column_split=0.49)
    output_path.write_text(text)
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
