"""
tag_document_types.py

Assigns a doc_type to every document in the corpus, based on the
taxonomy: GO_circular, financial_rules, budget_document, gst_notification,
gst_circular. Uses the original notice title (from the scraper) to
classify each jkuber-sourced document with simple keyword rules.

This produces data/raw/doc_types.json: {doc_id: {doc_type, title, source}}
— a lookup other scripts (build_document_registry.py, future chunking)
should merge in, rather than guessing document type from content later.

Usage:
    python -m lineage.tag_document_types
"""

import json
import re
from pathlib import Path

JKUBER_NOTICES = Path("data/raw/jkuber_notices.json")
OUT_PATH = Path("data/raw/doc_types.json")


def doc_id_from_pdf_url(pdf_url: str) -> str:
    """Match the doc_id derivation used in build_document_registry.py —
    the PDF filename stem."""
    filename = pdf_url.rstrip("/").split("/")[-1]
    return Path(filename).stem


def classify_title(title: str) -> str:
    """
    Keyword-based rules, checked in order of specificity. This is a
    first pass over a known, small corpus (25 docs) — good enough here;
    a larger/more varied corpus would need a more robust classifier.
    """
    t = title.lower()

    if "financial rules" in t or "वित्तीय नियमावली" in title:
        return "financial_rules"

    if "बजट" in title and ("प्राक्कलन" in title or "अनुपूरक" in title
                             or "बजट भाषण" in title):
        return "budget_document"

    if "विनियोग" in title and "अधिनियम" in title:
        # Jharkhand Appropriation Act expenditure authorization —
        # a GO in form, but budget-related in substance.
        return "GO_circular"

    if "quotation" in t or "निविदा" in title:
        return "tender_notice"

    # Default: routine departmental order/circular/notice
    return "GO_circular"


def main():
    if not JKUBER_NOTICES.exists():
        print(f"ERROR: {JKUBER_NOTICES} not found.")
        return

    notices = json.loads(JKUBER_NOTICES.read_text(encoding="utf-8"))

    tags = {}
    for notice in notices:
        pdf_url = notice.get("pdf_url")
        if not pdf_url:
            continue
        doc_id = doc_id_from_pdf_url(pdf_url)
        doc_type = classify_title(notice["title"])
        tags[doc_id] = {
            "doc_type": doc_type,
            "title": notice["title"],
            "source": "jkuber_portal",
        }
        print(f"{doc_id}: {doc_type}  —  {notice['title'][:60]}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(tags, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    from collections import Counter
    counts = Counter(v["doc_type"] for v in tags.values())
    print(f"\nTotal tagged: {len(tags)}")
    for doc_type, count in counts.items():
        print(f"  {doc_type}: {count}")
    print(f"Saved to {OUT_PATH}")


if __name__ == "__main__":
    main()