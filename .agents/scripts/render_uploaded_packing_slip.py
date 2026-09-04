from pathlib import Path

import fitz


SOURCE = Path("attached_assets/Nashua_United_Packing_Slips_Sorted_Consolidated_1788534167096.pdf")
OUTPUT_DIR = Path(".agents/outputs/nashua-packing-slip-preview")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    document = fitz.open(SOURCE)
    for page_index in (0, min(1, document.page_count - 1), document.page_count - 1):
        page = document[page_index]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        pixmap.save(OUTPUT_DIR / f"page-{page_index + 1}.png")
    print(f"Rendered 3 preview pages from {document.page_count} PDF pages.")
    document.close()


if __name__ == "__main__":
    main()