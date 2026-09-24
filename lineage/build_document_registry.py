"""
build_document_registry.py

Runs supersession_patterns.py extraction across every processed document
(OCR'd or direct-extracted) and builds a document registry: one record
per document with its own reference number, date, and any supersession
references it makes to other documents.

This registry is the input to the actual lineage graph build (next step)
— that step resolves "referenced_doc" strings to real doc_ids by matching
against the "own_number" field across all documents.

Usage:
    python build_document_registry.py --input data/processed --out data/lineage/document_registry.json
"""

import argparse
import json
from pathlib import Path

from lineage.supersession_patterns import (
    extract_own_doc_number,
    find_supersession_references,
)


def build_registry(processed_dir: Path) -> list:
    registry = []
    json_files = sorted(processed_dir.glob("*.json"))

    for json_path in json_files:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        doc_id = json_path.stem

        full_text = " ".join(p.get("full_text", "") for p in data.get("pages", []))

        own_number = extract_own_doc_number(full_text)
        references = find_supersession_references(full_text)

        record = {
            "doc_id": doc_id,
            "source_file": data.get("file"),
            "extraction_method": data.get("method", "ocr"),
            "page_count": data.get("page_count"),
            "own_number": own_number,
            "references": references,
            "status": "unknown",       # resolved in the graph-build step
            "superseded_by": None,     # resolved in the graph-build step
        }
        registry.append(record)

        ref_summary = f"{len(references)} reference(s)" if references else "no references"
        print(f"{doc_id}: own_number={own_number!r}, {ref_summary}")

    return registry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/processed",
                         help="Folder of OCR/extraction output JSON files")
    parser.add_argument("--out", default="data/lineage/document_registry.json",
                         help="Output path for the document registry")
    args = parser.parse_args()

    registry = build_registry(Path(args.input))

    with_number = sum(1 for r in registry if r["own_number"])
    with_refs = sum(1 for r in registry if r["references"])
    print(f"\nTotal documents: {len(registry)}")
    print(f"  With own number extracted: {with_number}")
    print(f"  With supersession references: {with_refs}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Saved registry to {out_path}")


if __name__ == "__main__":
    main()