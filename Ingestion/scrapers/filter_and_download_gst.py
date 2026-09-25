"""
filter_and_download_gst.py

The full GST notifications list (3,873 entries) is too large to download
and process wholesale for this project's purposes. This filters down to
notifications whose TITLE itself signals amendment/supersession language
— these are the ones most likely to actually reference another S.O. by
number, making them the highest-value subset for validating the lineage
feature. Only this filtered subset gets downloaded.

Usage:
    python -m Ingestion.scrapers.filter_and_download_gst
"""

import json
import re
from pathlib import Path

import requests

INPUT_PATH = Path("data/raw/gst_notifications.json")
OUT_FILTERED = Path("data/raw/gst_notifications_filtered.json")
OUT_DIR = Path("data/raw/gst_pdfs")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# Keywords that suggest a notification explicitly amends, deletes, or
# supersedes another one — these are the documents worth prioritizing
# for lineage testing, not the routine standalone ones.
SIGNAL_KEYWORDS = [
    "amendment", "amend", "deletion", "delete", "supersession", "supersede",
    "corrigendum", "correction", "in partial modification", "cancel",
    "rescind", "modification",
]


def is_high_signal(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in SIGNAL_KEYWORDS)


def main():
    notifications = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    print(f"Total notifications available: {len(notifications)}")

    filtered = [n for n in notifications if is_high_signal(n["title"])]
    print(f"High-signal (amendment/deletion/supersession language): "
          f"{len(filtered)}")

    OUT_FILTERED.write_text(
        json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Saved filtered list to {OUT_FILTERED}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\nDownloading {len(filtered)} PDFs to {OUT_DIR} ...")
    for i, n in enumerate(filtered):
        url = n["pdf_url"]
        ext = n.get("filetype", "pdf").strip().lower() or "pdf"
        safe_title = re.sub(r'[<>:"/\\|?*]', "_", n["title"])[:80]
        filename = f"{i:03d}_{safe_title}.{ext}"
        dest = OUT_DIR / filename
        if dest.exists():
            continue
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            print(f"  downloaded: {filename}")
        except requests.RequestException as e:
            print(f"  FAILED: {filename} ({e})")

    print(f"\nDone. {len(filtered)} high-signal GST documents downloaded.")


if __name__ == "__main__":
    main()