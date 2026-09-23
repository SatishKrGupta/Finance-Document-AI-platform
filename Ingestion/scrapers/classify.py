"""
classify.py

Classifies each PDF in a folder as "scanned" (image-only, needs OCR) or
"digital" (already has a text layer). This is the triage step before
deciding which documents go through the OCR pipeline vs. straight to
chunking/embedding.

Usage:
    python classify.py --input data/raw/pdfs --out data/raw/classification.json
"""

import argparse
import json
from pathlib import Path

import fitz  # PyMuPDF

# Below this many extracted characters (averaged across pages), a PDF is
# treated as scanned — a handful of stray characters can appear even in
# image-only PDFs (e.g. a digital stamp/watermark), so we don't use zero.
CHARS_PER_PAGE_THRESHOLD = 20


def classify_pdf(path: Path) -> dict:
    try:
        doc = fitz.open(path)
        page_count = len(doc)
        if page_count == 0:
            return {"file": path.name, "status": "empty", "page_count": 0}

        total_chars = sum(len(page.get_text()) for page in doc)
        avg_chars_per_page = total_chars / page_count

        status = (
            "digital" if avg_chars_per_page >= CHARS_PER_PAGE_THRESHOLD
            else "scanned"
        )

        return {
            "file": path.name,
            "status": status,
            "page_count": page_count,
            "avg_chars_per_page": round(avg_chars_per_page, 1),
        }
    except Exception as e:
        return {"file": path.name, "status": "error", "error": str(e)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input", default="data/raw/pdfs",
        help="Folder containing PDFs to classify"
    )
    parser.add_argument(
        "--out", default="data/raw/classification.json",
        help="Output JSON path for classification results"
    )
    args = parser.parse_args()

    input_dir = Path(args.input)
    pdf_files = sorted(input_dir.glob("*.pdf"))

    if not pdf_files:
        print(f"No PDFs found in {input_dir}")
        return

    results = [classify_pdf(p) for p in pdf_files]

    scanned = sum(1 for r in results if r["status"] == "scanned")
    digital = sum(1 for r in results if r["status"] == "digital")
    errors = sum(1 for r in results if r["status"] == "error")
    empty = sum(1 for r in results if r["status"] == "empty")

    print(f"Total: {len(results)}")
    print(f"  Scanned (needs OCR): {scanned}")
    print(f"  Digital (has text):  {digital}")
    print(f"  Empty:               {empty}")
    print(f"  Errors:              {errors}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Saved classification to {out_path}")


if __name__ == "__main__":
    main()