"""
jkuber_scraper.py

Scrapes the "Latest News" notice list from the Jharkhand Finance Department's
employee/treasury portal (jkuber.jharkhand.gov.in). This is a real, dated,
department-issued source — a good first dataset for the Finance Document AI
Platform project.

NOTE: This targets the public notice list on the portal's landing page.
The site may not expose a clean API, so this scrapes rendered HTML.
Inspect the actual page structure (view-source or browser devtools) before
relying on this — selectors below are best-effort and WILL need adjusting
once you can see the live DOM (this environment's network access doesn't
allow fetching this domain directly, so verify locally).

Usage:
    python jkuber_scraper.py --out data/raw/jkuber_notices.json
"""

import argparse
import json
import time
from pathlib import Path

import certifi
import requests
import urllib3
from bs4 import BeautifulSoup

# jkuber.jharkhand.gov.in does not send its full certificate chain
# (missing intermediate cert) — browsers silently work around this,
# but requests/urllib3 do not. Since this is a public notice board
# with no sensitive data exchange, we disable verification here and
# suppress the resulting warning explicitly so it's a deliberate choice.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://jkuber.jharkhand.gov.in/emp/Default.aspx"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def fetch_page(url: str, retries: int = 3, delay: float = 2.0) -> str:
    """Fetch raw HTML with basic retry logic."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(
                url, headers=HEADERS, timeout=15, verify=False
            )
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            print(f"[attempt {attempt}] fetch failed: {e}")
            if attempt < retries:
                time.sleep(delay)
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts")


def parse_notices(html: str) -> list[dict]:
    """
    Parse the notice list into structured records.

    Each notice on the page currently looks like:
        <notice title text>
        Posted On: DD/MM/YYYY

    Adjust the selector once you inspect the real HTML — this is a
    reasonable starting guess based on the page's rendered text structure.
    """
    soup = BeautifulSoup(html, "html.parser")
    notices = []

    # Placeholder selector — replace with the real container class/id
    # once you inspect the page (e.g. div.news-item, li.notice-entry, etc.)
    candidates = soup.find_all(string=lambda s: s and "Posted On:" in s)

    for node in candidates:
        posted_on = node.strip().replace("Posted On:", "").strip()
        # Title is typically the preceding sibling text block
        title_node = node.find_previous(string=True)
        title = title_node.strip() if title_node else None

        if title and posted_on:
            notices.append({
                "title": title,
                "posted_on": posted_on,
                "source_url": BASE_URL,
                "language": "hi" if any(
                    "\u0900" <= ch <= "\u097F" for ch in title
                ) else "en",
            })

    return notices


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out", default="data/raw/jkuber_notices.json",
        help="Output JSON path"
    )
    args = parser.parse_args()

    print(f"Fetching {BASE_URL} ...")
    html = fetch_page(BASE_URL)

    notices = parse_notices(html)
    print(f"Parsed {len(notices)} notices")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(notices, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()