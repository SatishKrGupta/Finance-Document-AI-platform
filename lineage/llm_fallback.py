"""
llm_fallback.py

For documents where the rule-based regex extraction (supersession_patterns.py)
failed or produced a low-confidence result, this sends the document's header
text to an LLM (via Groq) to extract the same fields more robustly.

This is a TARGETED fallback, not a replacement for the regex pass — regex
is free and instant and got 292025_495 right; only the ~15 uncertain cases
need the more expensive LLM call.

Usage:
    python -m lineage.llm_fallback
"""

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

load_dotenv()  # reads .env for GROQ_API_KEY

MODEL = "openai/gpt-oss-120b"  # Groq's current recommended default

REGISTRY_PATH = Path("data/lineage/document_registry.json")
PROCESSED_DIR = Path("data/processed")

# How much of the document's text to send — the doc number and any
# supersession statement almost always appear in the first ~1500 chars
# (header/opening), so we don't need to send the whole document.
MAX_CHARS = 1500

PROMPT_TEMPLATE = """You are extracting metadata from an Indian government \
finance department document (a Government Order, circular, or notice). \
The text below may be in Hindi, English, or mixed, and may contain OCR \
errors (misrecognized characters, broken spacing).

Extract and return ONLY a JSON object with these exact keys:
- "doc_number": the document's own reference number (पत्रांक/स्मारक संख्या/ \
Memo No./Order No.), as a string, or null if genuinely not present.
- "doc_date": the document's date if stated, in DD/MM/YYYY format, or null.
- "supersedes": a list of document numbers this document explicitly \
supersedes, cancels, or replaces (look for phrases like "in supersession \
of", "के अधिक्रमण में", "cancelled vide", "के स्थान पर"). Empty list if none.

Return ONLY the JSON object, no other text, no markdown code fences.

Document text:
---
{text}
---"""


def is_low_confidence(record: dict) -> bool:
    """
    Decide whether a regex-extracted record needs the LLM fallback.
    Flags: no own_number at all, OR a suspiciously short/non-numeric
    own_number that doesn't look like a real document reference.
    """
    num = record.get("own_number")
    if not num:
        return True
    # A real doc number usually has a digit and is more than 2 chars.
    has_digit = any(c.isdigit() for c in num)
    if not has_digit or len(num) <= 2:
        return True
    return False


def load_full_text(doc_id: str) -> str:
    path = PROCESSED_DIR / f"{doc_id}.json"
    if not path.exists():
        return ""
    data = json.loads(path.read_text(encoding="utf-8"))
    full_text = " ".join(p.get("full_text", "") for p in data.get("pages", []))
    return full_text[:MAX_CHARS]


def extract_with_llm(client: Groq, text: str) -> dict:
    prompt = PROMPT_TEMPLATE.format(text=text)
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    raw = response.choices[0].message.content.strip()
    # Strip markdown fences if the model added them despite instructions
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"  WARNING: could not parse LLM response as JSON: {raw[:200]}")
        return {"doc_number": None, "doc_date": None, "supersedes": []}


def main():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("ERROR: GROQ_API_KEY not found. Check your .env file exists "
              "at the project root and contains GROQ_API_KEY=...")
        return

    client = Groq(api_key=api_key)

    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    low_conf = [r for r in registry if is_low_confidence(r)]
    print(f"Found {len(low_conf)} low-confidence documents out of "
          f"{len(registry)} total")

    for record in low_conf:
        doc_id = record["doc_id"]
        text = load_full_text(doc_id)
        if not text.strip():
            print(f"{doc_id}: no text available, skipping")
            continue

        print(f"{doc_id}: sending to LLM...")
        llm_result = extract_with_llm(client, text)

        record["llm_doc_number"] = llm_result.get("doc_number")
        record["llm_doc_date"] = llm_result.get("doc_date")
        record["llm_supersedes"] = llm_result.get("supersedes", [])
        record["extraction_source"] = "llm_fallback"

        print(f"  -> doc_number={llm_result.get('doc_number')!r}, "
              f"date={llm_result.get('doc_date')!r}, "
              f"supersedes={llm_result.get('supersedes')}")

    REGISTRY_PATH.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nUpdated registry saved to {REGISTRY_PATH}")


if __name__ == "__main__":
    main()