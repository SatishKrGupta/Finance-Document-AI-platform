"""
scrape_gst_notifications.py

Scrapes S.O. (Statutory Order) GST notifications from
ctax.jharkhand.gov.in/gst-notifications. Verified real and allowed by
robots.txt as of this project's research. These notifications frequently
reference/amend/delete each other by S.O. number, making this dataset
much better for validating the lineage feature than routine jkuber notices.

Each entry is tagged doc_type="gst_notification" from the start.

Usage:
    python -m ingestion.scrapers.scrape_gst_notifications --download-pdfs
"""

import argparse
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://ctax.jharkhand.gov.in/gst-notifications"

# Confirmed real pagination URL structure (Liferay portal, "_cur=" is the
# page number, "_delta=" is items per page). Page 1 has no _cur param
# (or _cur=1); page 2+ needs the full portlet query string, not just the
# page path, or Liferay won't route to the right portlet instance.
PAGE_URL_TEMPLATE = (
    "https://ctax.jharkhand.gov.in/web/10231/gst-notifications"
    "?p_p_id=101_INSTANCE_0Rnkvmm4uARj"
    "&p_p_lifecycle=0"
    "&p_p_state=normal"
    "&p_p_mode=view"
    "&p_p_col_id=column-2"
    "&p_p_col_count=1"
    "&_101_INSTANCE_0Rnkvmm4uARj_delta=100"
    "&_101_INSTANCE_0Rnkvmm4uARj_keywords="
    "&_101_INSTANCE_0Rnkvmm4uARj_advancedSearch=false"
    "&_101_INSTANCE_0Rnkvmm4uARj_andOperator=true"
    "&p_r_p_564233524_resetCur=false"
    "&_101_INSTANCE_0Rnkvmm4uARj_cur={page}"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def fetch_page(url: str, retries: int = 3, delay: float = 2.0) -> str:
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            print(f"[attempt {attempt}] fetch failed: {e}")
            if attempt < retries:
                time.sleep(delay)
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts")


def parse_notifications(html: str) -> list:
    """
    Real structure (confirmed via debug_raw_page.html inspection):
        <tbody class="table-data">
          <tr>
            <td class="table-cell">S.O. 25 dt ... (short title)</td>
            <td class="table-cell">S.O. 25 dt ... (full title/filename)</td>
            <td class="table-cell">111.6 KB</td>
            <td class="table-cell">July 1, 2017</td>
            <td class="table-cell">pdf</td>
            <td class="table-cell"><a href="https://.../documents/10231/0/...?version=1.0">
              <img .../></a></td>
          </tr>
          ...
    The document link does NOT end in .pdf (it's a UUID-based document
    management URL) and its <a> tag has no text (just an icon image) —
    so title comes from the first <td>, and the link comes from the <a>
    inside the last <td>, matched by position, not by extension or text.
    """
    soup = BeautifulSoup(html, "html.parser")
    notifications = []

    tbody = soup.find("tbody", class_="table-data")
    if tbody is None:
        print("WARNING: could not find <tbody class='table-data'> — "
              "page structure may have changed.")
        return []

    rows = tbody.find_all("tr")
    for row in rows:
        cells = row.find_all("td", class_="table-cell")
        if len(cells) < 6:
            continue  # malformed row, skip rather than crash

        title = cells[0].get_text(strip=True)
        date_str = cells[3].get_text(strip=True)
        filetype = cells[4].get_text(strip=True)

        link_tag = cells[5].find("a", href=True)
        pdf_url = link_tag["href"] if link_tag else None

        if not title or not pdf_url:
            continue

        so_match = re.search(r"S\.?O\.?\s*(\d+)", title, re.IGNORECASE)
        so_number = so_match.group(1) if so_match else None

        notifications.append({
            "title": title,
            "pdf_url": pdf_url,
            "date": date_str,
            "filetype": filetype,
            "so_number": so_number,
            "doc_type": "gst_notification",
            "source": "ctax_gst_notifications",
        })

    return notifications


def download_pdfs(notifications: list, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, n in enumerate(notifications):
        url = n["pdf_url"]
        ext = n.get("filetype", "pdf").strip().lower() or "pdf"
        # URL is a UUID, not a real filename — build one from the title
        # instead so files are actually identifiable on disk.
        safe_title = re.sub(r'[<>:"/\\|?*]', "_", n["title"])[:80]
        filename = f"{i:03d}_{safe_title}.{ext}"
        dest = out_dir / filename
        if dest.exists():
            continue
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            print(f"  downloaded: {filename}")
        except requests.RequestException as e:
            print(f"  FAILED: {filename} ({e})")


def fetch_all_pages(max_pages: int = 50) -> list:
    """
    Walks pages 1, 2, 3... using the confirmed Liferay pagination URL,
    stopping when a page returns zero notifications (end of the list)
    or max_pages is hit as a safety cap against an infinite loop if the
    "empty page" detection ever misfires.
    """
    all_notifications = []
    page = 1

    while page <= max_pages:
        url = PAGE_URL_TEMPLATE.format(page=page)
        print(f"Fetching page {page} ...")
        html = fetch_page(url)
        page_notifications = parse_notifications(html)

        if not page_notifications:
            print(f"Page {page} returned 0 notifications — stopping.")
            break

        print(f"  page {page}: {len(page_notifications)} notifications")
        all_notifications.extend(page_notifications)
        page += 1
        time.sleep(1.5)  # be polite between requests

    return all_notifications


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/raw/gst_notifications.json")
    parser.add_argument("--download-pdfs", action="store_true")
    parser.add_argument("--all-pages", action="store_true",
                         help="Fetch every page, not just the first 100")
    args = parser.parse_args()

    if args.all_pages:
        notifications = fetch_all_pages()
    else:
        print(f"Fetching {BASE_URL} ...")
        html = fetch_page(BASE_URL)
        notifications = parse_notifications(html)

    print(f"\nTotal parsed: {len(notifications)} notifications")

    with_so = sum(1 for n in notifications if n["so_number"])
    print(f"  With S.O. number identified: {with_so}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(notifications, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Saved to {out_path}")

    if args.download_pdfs:
        pdf_dir = out_path.parent / "gst_pdfs"
        print(f"Downloading PDFs to {pdf_dir} ...")
        download_pdfs(notifications, pdf_dir)


if __name__ == "__main__":
    main()