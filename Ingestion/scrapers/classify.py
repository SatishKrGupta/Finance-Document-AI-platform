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

# Many Indian government PDFs use legacy non-Unicode fonts (Kruti Dev,
# Chanakya, DevLys) where each glyph is mapped to an arbitrary character
# code and only renders correctly with the embedded font. Extracting the
# raw text gives garbage (often Armenian/Hebrew/other-script codepoints),
# NOT real Devanagari. A "digital" PDF with mostly-garbled text needs to
# be treated as if scanned — rasterize and OCR the rendered glyphs
# instead of trusting the broken text layer.
DEVANAGARI_RANGE = (0x0900, 0x097F)
VALID_CHAR_FRACTION_THRESHOLD = 0.5


def valid_char_fraction(text: str) -> float:
    """
    Fraction of non-whitespace characters that are plausible real text:
    Devanagari, basic Latin letters/digits, or common punctuation.
    A low fraction on text that LOOKS present usually means a legacy
    font encoding, not real Unicode content.
    """
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0

    def is_plausible(c: str) -> bool:
        code = ord(c)
        if DEVANAGARI_RANGE[0] <= code <= DEVANAGARI_RANGE[1]:
            return True
        if c.isascii() and (c.isalnum() or c in "/-.,:;()[]|"):
            return True
        return False

    valid = sum(1 for c in chars if is_plausible(c))
    return valid / len(chars)


def classify_pdf(path: Path) -> dict:
    try:
        doc = fitz.open(path)
        page_count = len(doc)
        if page_count == 0:
            return {"file": path.name, "status": "empty", "page_count": 0}

        full_text = "".join(page.get_text() for page in doc)
        total_chars = len(full_text)
        avg_chars_per_page = total_chars / page_count

        has_text_layer = avg_chars_per_page >= CHARS_PER_PAGE_THRESHOLD

        if not has_text_layer:
            status = "scanned"
            char_fraction = None
        else:
            char_fraction = round(valid_char_fraction(full_text), 3)
            if char_fraction < VALID_CHAR_FRACTION_THRESHOLD:
                # Has a text layer, but it's garbled (legacy font encoding)
                # — treat like scanned: needs OCR of the rendered glyphs,
                # not the broken extracted text.
                status = "digital_garbled"
            else:
                status = "digital"

        return {
            "file": path.name,
            "status": status,
            "page_count": page_count,
            "avg_chars_per_page": round(avg_chars_per_page, 1),
            "valid_char_fraction": char_fraction,
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
    garbled = sum(1 for r in results if r["status"] == "digital_garbled")
    errors = sum(1 for r in results if r["status"] == "error")
    empty = sum(1 for r in results if r["status"] == "empty")

    print(f"Total: {len(results)}")
    print(f"  Scanned (needs OCR):              {scanned}")
    print(f"  Digital (real text, no OCR needed): {digital}")
    print(f"  Digital but garbled font (needs OCR): {garbled}")
    print(f"  Empty:                             {empty}")
    print(f"  Errors:                            {errors}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Saved classification to {out_path}")


if __name__ == "__main__":
    main()