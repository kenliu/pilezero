"""Routing and filename-rendering for the pilezero pipeline.

Step 3.3 — match_rule: evaluate routing rules (first match wins).
Step 3.4 — render_filename: expand a filename template, sanitizing field
values and stripping optional placeholders when their data is absent.
"""

from __future__ import annotations

import os
import re

from pilezero.models import Config, FileRecord, RoutingRule

# ---------------------------------------------------------------------------
# Module-level regex constants
# ---------------------------------------------------------------------------

# Matches a single non-alphanumeric separator character immediately followed
# by the {account_number} placeholder.  Used to strip both together when
# account_number is absent.
_ACCOUNT_NUMBER_WITH_SEP: re.Pattern[str] = re.compile(
    r"[^A-Za-z0-9{]\{account_number\}"
)

# Filesystem-hostile characters that must be replaced with "-" in field values.
# Covers: / \ : * ? " < > |
_HOSTILE_CHARS: re.Pattern[str] = re.compile(r'[/\\:*?"<>|]')

# Runs of whitespace inside a field value, collapsed to "_".
_WHITESPACE_RUN: re.Pattern[str] = re.compile(r"\s+")

# A leading "." in a field value, replaced with "-".
_LEADING_DOT: re.Pattern[str] = re.compile(r"^\.")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sanitize_value(value: str) -> str:
    """Sanitize a single field value for use in a filename.

    - Replace filesystem-hostile characters (/ \\ : * ? " < > |) with "-".
    - Replace a leading "." with "-".
    - Collapse internal whitespace runs to a single "_".
    """
    value = _HOSTILE_CHARS.sub("-", value)
    value = _LEADING_DOT.sub("-", value)
    value = _WHITESPACE_RUN.sub("_", value)
    return value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def match_rule(record: FileRecord, rules: list[RoutingRule]) -> RoutingRule | None:
    """Return the first routing rule that matches *record*, or ``None``.

    Match criteria (both must be satisfied):
    - ``rule.sender == "*"`` OR ``rule.sender == record.sender``
    - ``rule.document_type is None`` OR ``rule.document_type == record.document_type``
    """
    for rule in rules:
        sender_matches = rule.sender == "*" or rule.sender == record.sender
        type_matches = rule.document_type is None or rule.document_type == record.document_type
        if sender_matches and type_matches:
            return rule
    return None


def render_filename(template: str, record: FileRecord) -> str:
    """Render *template* using fields from *record*, returning the final filename.

    Placeholder handling:
    - ``{date}`` → ``record.document_date`` (already YYYY-MM-DD)
    - ``{sender}`` → ``record.sender``
    - ``{document_type}`` → ``record.document_type``
    - ``{account_number}`` → ``record.account_number``, or the placeholder
      **and** its single preceding separator character are removed when the
      value is falsy.

    Each substituted value is sanitized: filesystem-hostile characters are
    replaced with ``"-"``, a leading ``"."`` is replaced with ``"-"``, and
    whitespace runs are collapsed to ``"_"``.  Literal text in *template*
    (separators, dots) is never sanitized.
    """
    # Handle optional {account_number} before substitution.
    if not record.account_number:
        # Remove the preceding separator char + placeholder together.
        template = _ACCOUNT_NUMBER_WITH_SEP.sub("", template)
        # Edge case: placeholder at start of template (no preceding sep char).
        template = template.replace("{account_number}", "")

    # Build substitution mapping with sanitized values.
    substitutions: dict[str, str] = {
        "date": _sanitize_value(record.document_date or ""),
        "sender": _sanitize_value(record.sender or ""),
        "document_type": _sanitize_value(record.document_type or ""),
    }
    if record.account_number:
        substitutions["account_number"] = _sanitize_value(record.account_number)

    return template.format_map(substitutions)


def resolve_folder(folder: str, config: Config) -> str:
    """Resolve a routing rule *folder* to an absolute filesystem path.

    Folders whose name starts with ``"_"`` (e.g. ``_NeedsReview``,
    ``_Unmapped``, ``_Errored``) are joined under ``config.incoming_dir``.
    All other folders are joined under ``config.dropbox_root``.
    """
    if folder.startswith("_"):
        return os.path.join(config.incoming_dir, folder)
    return os.path.join(config.dropbox_root, folder)


# ---------------------------------------------------------------------------
# Quick demo (python -m pilezero.route or python pilezero/route.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from pilezero.models import FileRecord

    # Example 1 — with account number (spec example: PSEG rule)
    rec1 = FileRecord(
        original_path="/incoming/scan.pdf",
        sender="PSEG",
        document_type="bill",
        document_date="2024-03-15",
        account_number="7890",
    )
    tmpl1 = "{date}_{sender}_{account_number}.pdf"
    result1 = render_filename(tmpl1, rec1)
    print(f"Example 1: {result1!r}")
    # Expected: '2024-03-15_PSEG_7890.pdf'

    # Example 2 — without account number (spec example: account_number absent)
    rec2 = FileRecord(
        original_path="/incoming/scan2.pdf",
        sender="PSEG",
        document_type="bill",
        document_date="2024-03-15",
        account_number=None,
    )
    result2 = render_filename(tmpl1, rec2)
    print(f"Example 2: {result2!r}")
    # Expected: '2024-03-15_PSEG.pdf'  (the "_" before {account_number} is dropped)

    # Example 3 — sanitization: hostile chars in sender name
    rec3 = FileRecord(
        original_path="/incoming/scan3.pdf",
        sender="Dr. Smith/Jones",
        document_type="statement",
        document_date="2024-06-01",
        account_number=None,
    )
    tmpl3 = "{date}_{sender}_{document_type}.pdf"
    result3 = render_filename(tmpl3, rec3)
    print(f"Example 3: {result3!r}")
    # Expected: '2024-06-01_Dr._Smith-Jones_statement.pdf'
