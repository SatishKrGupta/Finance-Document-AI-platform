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
    Parse the notice marquee into structured records, including the real
    PDF download link for each notice.

    The site's actual structure (confirmed via view-source) is a
    <marquee id="mq1"> containing a flat sequence of alternating siblings:
        <a href="...pdf" target="_blank">Title text</a>
        <p>...Posted On: DD/MM/YYYY...</p>
    repeated once per notice. There is no wrapping container per notice,
    so we pair consecutive <a> and <p> tags.
    """
    soup = BeautifulSoup(html, "html.parser")

    marquee = soup.find("marquee", id="mq1")
    if marquee is None:
        print("WARNING: could not find <marquee id='mq1'> — page structure "
              "may have changed. Falling back to empty result.")
        return []

    elements = marquee.find_all(["a", "p"], recursive=False)

    notices = []
    i = 0
    while i < len(elements):
        a_tag = elements[i]
        title = a_tag.get_text(strip=True)

        # Clean the href: site emits raw backslashes and stray whitespace
        # in the path (Windows-server artifact), which isn't a valid URL.
        raw_href = a_tag.get("href", "").strip()
        pdf_url = raw_href.replace("\\", "/") if raw_href else None

        posted_on = None
        if i + 1 < len(elements) and elements[i + 1].name == "p":
            p_text = elements[i + 1].get_text(strip=True)
            posted_on = p_text.replace("Posted On:", "").strip()
            i += 2
        else:
            i += 1

        if title:
            notices.append({
                "title": title,
                "posted_on": posted_on,
                "pdf_url": pdf_url,
                "source_url": BASE_URL,
                "language": "hi" if any(
                    "\u0900" <= ch <= "\u097F" for ch in title
                ) else "en",
            })

    return notices


def download_pdfs(notices: list[dict], out_dir: Path) -> None:
    """Download each notice's PDF into out_dir, named by its URL's filename."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for n in notices:
        url = n.get("pdf_url")
        if not url:
            continue
        filename = url.rstrip("/").split("/")[-1]
        dest = out_dir / filename
        if dest.exists():
            continue  # don't re-download what we already have
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20, verify=False)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            print(f"  downloaded: {filename}")
        except requests.RequestException as e:
            print(f"  FAILED: {filename} ({e})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out", default="data/raw/jkuber_notices.json",
        help="Output JSON path"
    )
    parser.add_argument(
        "--download-pdfs", action="store_true",
        help="Also download each notice's linked PDF into data/raw/pdfs/"
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

    if args.download_pdfs:
        pdf_dir = out_path.parent / "pdfs"
        print(f"Downloading PDFs to {pdf_dir} ...")
        download_pdfs(notices, pdf_dir)


if __name__ == "__main__":
    main()