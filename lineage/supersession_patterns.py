"""
supersession_patterns.py

Rule-based (regex) patterns for two related but separate tasks:

1. Extracting a document's own reference number ("पत्रांक" / "letter no.")
   from its text — this is the ID other documents will cite when they
   supersede it.

2. Detecting supersession language — phrases that indicate THIS document
   cancels/replaces ANOTHER document, and extracting which one.

This is a first-pass rule-based approach, expected to catch the majority
of cases (Indian GOs tend to state supersession explicitly and formulaically).
Anything that doesn't match falls through to an LLM-based fallback pass
(see llm_fallback.py) rather than being silently missed.
"""

import re
from typing import Optional

# Devanagari letters + digits + common punctuation used inside document
# numbers (matras/vowel signs live in the same Unicode block, so the full
# \u0900-\u097F range is needed, not just the digit sub-range).
DEVANAGARI = r"\u0900-\u097F"
DOC_NUM_CHARS = rf"[\w{DEVANAGARI}/\-]"

# --- Document's own reference number ---
# Real example seen in this project's data:
#   "पत्रांक : 29/बी०टी०ई०--02/2025-26/624"
# Pattern: पत्रांक (letter no.) or "No." / "Order No." followed by a
# number that mixes digits, slashes, hyphens, and Devanagari characters.
OWN_DOC_NUMBER_PATTERNS = [
    rf"पत्रांक\s*[:\-]?\s*({DOC_NUM_CHARS}+)",
    r"(?:Memo|Order|G\.?O\.?|Letter)\s*No\.?\s*[:\-]?\s*([\w/\-]+)",
    rf"संख्या\s*[:\-]?\s*({DOC_NUM_CHARS}+)",
]

# --- Supersession language ---
# English patterns: the referenced document follows the trigger phrase.
# Each pattern should have exactly one capture group.
SUPERSESSION_PATTERNS_EN = [
    r"in supersession of\s+(?:the\s+)?(?:order|circular|notification|G\.?O\.?)?\s*(?:no\.?)?\s*([\w/\-]+)",
    r"hereby supersede[sd]?\s+([\w/\-]+)",
    r"cancell?ed\s+vide\s+([\w/\-]+)",
    r"in partial modification of\s+([\w/\-]+)",
    r"replaces?\s+(?:order|circular)?\s*(?:no\.?)?\s*([\w/\-]+)",
]

# Hindi patterns: postpositions ("के अधिक्रमण में", "के स्थान पर") follow
# the noun phrase they govern, so the referenced document number comes
# BEFORE the trigger phrase here — opposite direction from the English
# patterns above. This matches real Indian-government Hindi GO phrasing:
# "<referenced doc no.> के अधिक्रमण में" = "in supersession of <doc no.>"
SUPERSESSION_PATTERNS_HI = [
    rf"({DOC_NUM_CHARS}+)\s*के अधिक्रमण में",      # "X के अधिक्रमण में" = in supersession of X
    rf"({DOC_NUM_CHARS}+)\s*के स्थान पर",          # "X के स्थान पर" = in place of X
    rf"({DOC_NUM_CHARS}+)\s*रद्द(?:\s*किया जाता है|\s*कर दिया गया है)?",  # "X cancelled"
    rf"({DOC_NUM_CHARS}+)\s*के आंशिक संशोधन में",  # "X के आंशिक संशोधन में" = in partial amendment of X
]

# Weaker signals — text mentions another document but not necessarily
# as a formal supersession. Surface these for manual review, don't
# auto-link them in the lineage graph. Same postposition-follows-noun
# direction applies to the Hindi pattern here.
WEAK_REFERENCE_PATTERNS_EN = [
    r"with reference to\s+([\w/\-]+)",
]
WEAK_REFERENCE_PATTERNS_HI = [
    rf"({DOC_NUM_CHARS}+)\s*के आलोक में",   # "X के आलोक में" = in light of X
    rf"संदर्भ\s*[:\-]?\s*({DOC_NUM_CHARS}+)",  # "reference: X" (this one is EN-order)
]


def normalize_ocr_spacing(text: str) -> str:
    """
    OCR pipelines that reconstruct full_text by joining individually
    detected words with plain spaces (as ours does) introduce spurious
    spaces around punctuation that was originally tight against the
    surrounding characters — e.g. "29 /बी...-02 / 2025-26" instead of
    "29/बी...-02/2025-26". Document numbers rely on that punctuation
    being contiguous, so collapse it before pattern matching.
    """
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"\s*-\s*", "-", text)
    return text


def extract_own_doc_number(text: str) -> Optional[str]:
    """Try each own-number pattern in order, return the first match."""
    text = normalize_ocr_spacing(text)
    for pattern in OWN_DOC_NUMBER_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return None


def _has_digit(text: str) -> bool:
    """
    A real document reference always contains a digit (year, serial
    number). Generic connector phrases like "the", "any", "उपरोक्त"
    (the above-mentioned), "उक्त" (the aforementioned) get matched by
    the loose "with reference to X" / "के आलोक में" patterns but never
    contain a digit — this filters those false positives out.
    """
    ascii_digit = any(c.isdigit() for c in text)
    devanagari_digit = any("\u0966" <= c <= "\u096F" for c in text)
    return ascii_digit or devanagari_digit


def find_supersession_references(text: str) -> list[dict]:
    """
    Scan text for supersession language. Returns a list of dicts:
        {"referenced_doc": "...", "pattern_type": "supersedes"|"weak_reference",
         "language": "en"|"hi", "matched_phrase": "..."}
    Does NOT resolve the referenced doc to an actual doc_id — that join
    happens later once you have all documents' own numbers indexed.
    """
    text = normalize_ocr_spacing(text)
    results = []

    for pattern in SUPERSESSION_PATTERNS_EN:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            results.append({
                "referenced_doc": match.group(1).strip(),
                "pattern_type": "supersedes",
                "language": "en",
                "matched_phrase": match.group(0),
            })

    for pattern in SUPERSESSION_PATTERNS_HI:
        for match in re.finditer(pattern, text):
            ref = match.group(1).strip() if match.lastindex else ""
            if ref:  # skip empty captures (e.g. bare "cancelled" with no ref)
                results.append({
                    "referenced_doc": ref,
                    "pattern_type": "supersedes",
                    "language": "hi",
                    "matched_phrase": match.group(0),
                })

    for pattern in WEAK_REFERENCE_PATTERNS_EN:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            results.append({
                "referenced_doc": match.group(1).strip(),
                "pattern_type": "weak_reference",
                "language": "en",
                "matched_phrase": match.group(0),
            })

    for pattern in WEAK_REFERENCE_PATTERNS_HI:
        for match in re.finditer(pattern, text):
            results.append({
                "referenced_doc": match.group(1).strip(),
                "pattern_type": "weak_reference",
                "language": "hi",
                "matched_phrase": match.group(0),
            })

    return [r for r in results if _has_digit(r["referenced_doc"])]


if __name__ == "__main__":
    samples = [
        (
            "पत्रांक : 29/बी०टी०ई०--02/2025-26/624 झारखण्ड सरकार वित्त विभाग "
            "पूर्व आदेश संख्या 15/2019 के अधिक्रमण में यह आदेश जारी किया जाता है।"
        ),
        "This order is issued in supersession of GO No. FD-12/2019.",
        "आदेश संख्या 45/2020 के स्थान पर यह आदेश प्रभावी होगा।",
        # Simulates real OCR word-joining artifact: spaces inserted
        # around slashes/hyphens because words were detected separately.
        "पत्रांक : 29 /बी०टी०ई०--02 / 2025-26 / 624 झारखण्ड सरकार",
        # Generic prose that should now be filtered out (no digit present)
        "with reference to the above matter, kindly note that...",
        "उपरोक्त के आलोक में यह सूचित किया जाता है।",
    ]
    for s in samples:
        print("---")
        print("Text:", s)
        print("Own doc number:", extract_own_doc_number(s))
        print("References:", find_supersession_references(s))