"""
ocr_pipeline.py

OCRs scanned PDFs using Tesseract (English + Hindi) and saves extracted
text per page. Tesseract doesn't give per-word confidence as easily as
PaddleOCR by default, so we use image_to_data to get word-level
confidence scores and flag low-confidence words for manual review.

Usage:
    # test on a single file first
    python ocr_pipeline.py --input data/raw/pdfs/1482026_526.pdf --out data/processed

    # then batch, once you trust the output
    python ocr_pipeline.py --input data/raw/pdfs --out data/processed --batch

Requires Tesseract installed separately (not just the pip package) --
see setup notes below. If tesseract.exe isn't on your PATH, set
TESSERACT_CMD to the full path.
"""

import argparse
import io
import json
from pathlib import Path

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

# If Tesseract isn't on your system PATH, uncomment and set this to your
# actual install path, e.g.:
# TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSERACT_CMD = None
if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

# Tesseract language codes are combined with '+', e.g. "eng+hin" runs
# both models. Start with both since the corpus mixes English and Hindi;
# narrow to just "hin" or "eng" later if one is clearly dominant per doc.
OCR_LANG = "eng+hin"

# Confidence (0-100 from Tesseract) below this is flagged for manual
# review rather than trusted blindly into the RAG pipeline.
CONFIDENCE_THRESHOLD = 60

DPI = 300


def pdf_to_images(pdf_path: Path, dpi: int = DPI) -> list:
    """Render each PDF page to a PIL Image for OCR."""
    doc = fitz.open(pdf_path)
    images = []
    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)
    for page in doc:
        pix = page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        images.append(img)
    return images


def ocr_page(img: Image.Image) -> dict:
    """Run Tesseract on one page image, returning words with confidence."""
    data = pytesseract.image_to_data(
        img, lang=OCR_LANG, output_type=pytesseract.Output.DICT
    )

    words = []
    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        conf = int(data["conf"][i]) if data["conf"][i] != "-1" else -1
        if text:  # skip empty detections
            words.append({
                "text": text,
                "confidence": conf,
                "needs_review": conf != -1 and conf < CONFIDENCE_THRESHOLD,
            })

    full_text = " ".join(w["text"] for w in words)
    return {"words": words, "full_text": full_text}


def ocr_pdf(pdf_path: Path) -> dict:
    page_images = pdf_to_images(pdf_path)
    pages_result = []

    for page_num, img in enumerate(page_images, start=1):
        page_data = ocr_page(img)
        page_data["page"] = page_num
        pages_result.append(page_data)
        n_words = len(page_data["words"])
        n_flagged = sum(1 for w in page_data["words"] if w["needs_review"])
        print(f"  page {page_num}: {n_words} words "
              f"({n_flagged} flagged for review)")

    return {
        "file": pdf_path.name,
        "page_count": len(pages_result),
        "pages": pages_result,
    }


def process_file(pdf_path: Path, out_dir: Path):
    print(f"OCR: {pdf_path.name}")
    result = ocr_pdf(pdf_path)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{pdf_path.stem}.json"
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    total_words = sum(len(p["words"]) for p in result["pages"])
    flagged = sum(
        1 for p in result["pages"] for w in p["words"] if w["needs_review"]
    )
    print(f"  -> saved {out_path} ({total_words} words, {flagged} flagged "
          f"for review)")


def main():
    global OCR_LANG
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True,
                         help="A single PDF file, or a folder (with --batch)")
    parser.add_argument("--out", default="data/processed",
                         help="Output folder for OCR'd JSON")
    parser.add_argument("--batch", action="store_true",
                         help="Treat --input as a folder of PDFs")
    parser.add_argument("--lang", default=OCR_LANG,
                         help="Tesseract language code, e.g. 'eng', 'hin', "
                              "or 'eng+hin' for both")
    args = parser.parse_args()

    OCR_LANG = args.lang

    input_path = Path(args.input)
    out_dir = Path(args.out)

    if args.batch:
        pdf_files = sorted(input_path.glob("*.pdf"))
        print(f"Found {len(pdf_files)} PDFs to process")
        for pdf_path in pdf_files:
            process_file(pdf_path, out_dir)
    else:
        process_file(input_path, out_dir)


if __name__ == "__main__":
    main()