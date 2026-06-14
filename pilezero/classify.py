"""Classification step for the pilezero pipeline.

Matches extracted document text against the sender registry, extracts
document_date and account_number via regex, and validates that all required
fields are present.  Sets record.status = Status.NEEDS_REVIEW when anything
is ambiguous or missing; leaves status as None on the happy path (status is
set to SUCCESS later by the move step).
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from typing import Optional

from pilezero.models import FileRecord, SenderEntry, Status

# ---------------------------------------------------------------------------
# Regex patterns — documented with comments
# ---------------------------------------------------------------------------

# MM/DD/YYYY  or  M/D/YYYY  (e.g. "01/15/2024", "1/5/2024")
_PAT_MDY4 = r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"

# MM/DD/YY  or  M/D/YY  (e.g. "01/15/24", "1/5/24")
_PAT_MDY2 = r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b"

# Month DD, YYYY or Month DD YYYY  (e.g. "January 15, 2024", "Jan 15 2024")
_MONTHS = (
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
)
_PAT_MONTH_D_Y = rf"\b({_MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})\b"

# YYYY-MM-DD  (ISO 8601, e.g. "2024-01-15")
_PAT_ISO = r"\b(\d{4})-(\d{2})-(\d{2})\b"

# DD Mon YYYY  (e.g. "15 Jan 2024", "15 January 2024")
_PAT_DMY = rf"\b(\d{{1,2}})\s+({_MONTHS})\s+(\d{{4}})\b"

# Account number near keywords — capture last 4 digits of a digit sequence.
# Matches: "Account #: 1234567", "Acct: 1234", "Account Number 00001234", etc.
_PAT_ACCOUNT = (
    r"(?:Account\s*(?:Number|#|No\.?)?|Acct\.?)\s*[:\s]?\s*(\d+)"
)

# Pre-compiled versions used at runtime
_RE_MDY4 = re.compile(_PAT_MDY4, re.IGNORECASE)
_RE_MDY2 = re.compile(_PAT_MDY2, re.IGNORECASE)
_RE_MONTH_D_Y = re.compile(_PAT_MONTH_D_Y, re.IGNORECASE)
_RE_ISO = re.compile(_PAT_ISO)
_RE_DMY = re.compile(_PAT_DMY, re.IGNORECASE)
_RE_ACCOUNT = re.compile(_PAT_ACCOUNT, re.IGNORECASE)

# Mapping of abbreviated and full month names to month numbers
_MONTH_MAP: dict[str, int] = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _try_date(year: int, month: int, day: int) -> Optional[str]:
    """Validate and normalise a y/m/d triple to 'YYYY-MM-DD', or None."""
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _extract_date(text: str) -> Optional[str]:
    """Return the first plausible date found in *text* as 'YYYY-MM-DD'.

    Search order: ISO (unambiguous) → Month-name formats → numeric formats.
    Within each pattern the first regex match is used; if the date values are
    invalid (e.g. month 13) the match is skipped and the next pattern tried.
    """
    # ISO 8601 — most unambiguous
    for m in _RE_ISO.finditer(text):
        result = _try_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if result:
            return result

    # "Month DD, YYYY" / "Month DD YYYY"
    for m in _RE_MONTH_D_Y.finditer(text):
        month_num = _MONTH_MAP.get(m.group(1).lower())
        if month_num:
            result = _try_date(int(m.group(3)), month_num, int(m.group(2)))
            if result:
                return result

    # "DD Month YYYY"
    for m in _RE_DMY.finditer(text):
        month_num = _MONTH_MAP.get(m.group(2).lower())
        if month_num:
            result = _try_date(int(m.group(3)), month_num, int(m.group(1)))
            if result:
                return result

    # "MM/DD/YYYY"
    for m in _RE_MDY4.finditer(text):
        result = _try_date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        if result:
            return result

    # "MM/DD/YY" — interpret YY as 2000+YY (reasonable for scanned docs)
    for m in _RE_MDY2.finditer(text):
        year = 2000 + int(m.group(3))
        result = _try_date(year, int(m.group(1)), int(m.group(2)))
        if result:
            return result

    return None


def _extract_account(text: str) -> Optional[str]:
    """Return the last-4 digits of the first account number found, or None."""
    m = _RE_ACCOUNT.search(text)
    if m:
        digits = m.group(1)
        if len(digits) >= 4:
            return digits[-4:]
        # Fewer than 4 digits — still return them (e.g. a 4-digit account IS
        # a valid last-4 answer)
        return digits.zfill(4)[-4:] if digits else None
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify(record: FileRecord, senders: list[SenderEntry]) -> FileRecord:
    """Classify *record* using *senders* and in-text pattern extraction.

    Mutates *record* in-place (populating sender, document_type,
    document_date, account_number, and possibly status / error_message)
    and also returns it for convenience.

    Steps
    -----
    1. Sender matching — case-insensitive substring search.
    2. Date and account-number extraction via regex.
    3. Required-field check — sets NEEDS_REVIEW if any required field is
       missing and no ambiguity error was already set.
    """
    text = record.extracted_text

    # ------------------------------------------------------------------
    # Step 1 — Sender matching
    # ------------------------------------------------------------------
    matched_entries: list[SenderEntry] = [
        entry
        for entry in senders
        for phrase in entry.match_text
        if phrase.lower() in text.lower()
    ]

    if matched_entries:
        # Group by canonical_name
        by_name: dict[str, list[SenderEntry]] = {}
        for entry in matched_entries:
            by_name.setdefault(entry.canonical_name, []).append(entry)

        if len(by_name) > 1:
            # Multiple distinct senders matched — ambiguous
            names = ", ".join(sorted(by_name))
            record.status = Status.NEEDS_REVIEW
            record.error_message = f"ambiguous sender: {names}"
        else:
            # Exactly one canonical_name — check for conflicting document_type
            canonical_name = next(iter(by_name))
            entries_for_name = by_name[canonical_name]
            doc_types = {e.document_type for e in entries_for_name}
            if len(doc_types) > 1:
                types_str = ", ".join(sorted(doc_types))
                record.status = Status.NEEDS_REVIEW
                record.error_message = (
                    f"ambiguous document_type for {canonical_name}: {types_str}"
                )
            else:
                record.sender = canonical_name
                record.document_type = entries_for_name[0].document_type

    # ------------------------------------------------------------------
    # Step 2 — Date and account-number extraction
    # ------------------------------------------------------------------
    record.document_date = _extract_date(text)
    record.account_number = _extract_account(text)

    # ------------------------------------------------------------------
    # Step 3 — Required-field check (only if no ambiguity already flagged)
    # ------------------------------------------------------------------
    if record.status is None:
        missing = [
            field
            for field, value in (
                ("sender", record.sender),
                ("document_type", record.document_type),
                ("document_date", record.document_date),
            )
            if not value
        ]
        if missing:
            record.status = Status.NEEDS_REVIEW
            record.error_message = "missing required fields: " + ", ".join(missing)

    return record


# ---------------------------------------------------------------------------
# __main__ — quick smoke-test for date/account extraction
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    if not text:
        print("Usage: python -m pilezero.classify '<document text>'")
        sys.exit(1)

    dummy = FileRecord(original_path="<stdin>", extracted_text=text)
    result = classify(dummy, senders=[])
    print(f"document_date  : {result.document_date}")
    print(f"account_number : {result.account_number}")
    print(f"sender         : {result.sender}")
    print(f"document_type  : {result.document_type}")
    print(f"status         : {result.status}")
    print(f"error_message  : {result.error_message}")
