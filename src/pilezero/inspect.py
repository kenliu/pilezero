"""Classification inspector + rule suggester for a single PDF.

Point it at a scanned PDF to see (a) the metadata the pipeline would extract and
(b) a ready-to-paste senders.toml / routing.toml suggestion when the document is
not yet recognized. Read-only: it never moves or writes files.

    uv run python -m pilezero.inspect path/to/scan.pdf
    uv run pilezero-inspect path/to/scan.pdf --text   # also dump full text
    uv run pilezero-inspect path/to/scan.pdf --json    # machine-readable

senders.toml / routing.toml are loaded from the config dir (same resolution as
the main pipeline) so matches reflect your real registry.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from .classify import classify
from .config import load_config
from .extract import extract_text
from .models import Config, FileRecord, Status
from .route import match_rule, render_filename, resolve_folder

_PREVIEW_CHARS = 300


def inspect_pdf(pdf_path: str, config: Config) -> dict:
    """Run extract -> classify -> route on one PDF; return a metadata dict.

    Never moves or writes files. Captures the extracted text plus every decision
    the pipeline would make, and a rule suggestion when the file is unrecognized.
    """
    record = FileRecord(original_path=pdf_path, original_filename=Path(pdf_path).name)

    result: dict = {
        "file": pdf_path,
        "extraction_error": None,
        "extracted_text": "",
        "extracted_text_chars": 0,
        "matched_senders": [],
        "sender": None,
        "document_type": None,
        "document_date": None,
        "account_number": None,
        "classification_status": None,
        "classification_message": None,
        "routing_rule": None,
        "would_route_to": None,
        "rendered_filename": None,
        "suggestion": None,
    }

    # --- extraction ---
    try:
        record.extracted_text = extract_text(pdf_path)
    except Exception as e:  # noqa: BLE001 - report, don't crash the inspector
        result["extraction_error"] = f"{type(e).__name__}: {e}"
        result["would_route_to"] = "_Errored"
        return result

    text = record.extracted_text
    result["extracted_text"] = text
    result["extracted_text_chars"] = len(text)

    # Which sender entries matched (before ambiguity resolution)?
    lowered = text.lower()
    for s in config.senders:
        hits = [m for m in s.match_text if m.lower() in lowered]
        if hits:
            result["matched_senders"].append(
                {"canonical_name": s.canonical_name, "document_type": s.document_type, "matched_on": hits}
            )

    # --- classification ---
    classify(record, config.senders)
    result["sender"] = record.sender
    result["document_type"] = record.document_type
    result["document_date"] = record.document_date
    result["account_number"] = record.account_number
    result["classification_status"] = record.status.value if record.status else None
    result["classification_message"] = record.error_message

    # --- routing (read-only) ---
    rule = None
    if record.status != Status.NEEDS_REVIEW:
        rule = match_rule(record, config.rules)

    if rule is not None:
        filename = render_filename(rule.filename_template, record)
        dest_dir = resolve_folder(rule.folder, config)
        result["routing_rule"] = {
            "sender": rule.sender,
            "document_type": rule.document_type,
            "folder": rule.folder,
            "filename_template": rule.filename_template,
        }
        result["rendered_filename"] = filename
        result["would_route_to"] = str(Path(dest_dir) / filename)
    elif record.status == Status.NEEDS_REVIEW:
        result["would_route_to"] = "_NeedsReview"
    else:
        result["would_route_to"] = "_Unmapped"

    # --- rule suggestion (only when the sender isn't recognized) ---
    if not result["matched_senders"]:
        result["suggestion"] = _suggest_rule(record, text)

    return result


def _suggest_rule(record: FileRecord, text: str) -> dict:
    """Build a senders.toml + routing.toml stub from the document's metadata.

    The sender name is a placeholder for the user to fill in; candidate
    match_text strings are pulled from distinctive lines near the top of the
    document. Detected date/account inform the filename template.
    """
    candidates = _candidate_match_strings(text)
    has_account = bool(record.account_number)

    canonical = "TODO Sender Name"
    template = "{date}_{sender}_{account_number}.pdf" if has_account else "{date}_{sender}.pdf"

    senders_toml = (
        "[[senders]]\n"
        f'canonical_name = "{canonical}"\n'
        f"match_text     = {json.dumps(candidates)}\n"
        'document_type  = "TODO"  # bill | statement | notice | correspondence | form | receipt\n'
    )
    routing_toml = (
        "[[rules]]\n"
        f'sender            = "{canonical}"\n'
        'folder            = "TODO/Folder"\n'
        f'filename_template = "{template}"\n'
    )

    return {
        "candidate_match_text": candidates,
        "detected_date": record.document_date,
        "detected_account_last4": record.account_number,
        "senders_toml": senders_toml,
        "routing_toml": routing_toml,
    }


def _candidate_match_strings(text: str, limit: int = 5) -> list[str]:
    """Heuristic: distinctive non-numeric lines near the top, good for match_text."""
    candidates: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if len(line) < 4 or len(line) > 60:
            continue
        # Skip lines that are mostly digits/punctuation (dates, amounts, acct #s).
        letters = sum(c.isalpha() for c in line)
        if letters < max(4, len(line) // 2):
            continue
        if re.fullmatch(r"[\d\W]+", line):
            continue
        if line not in candidates:
            candidates.append(line)
        if len(candidates) >= limit:
            break
    return candidates


# --- human-readable output --------------------------------------------------


def _print_human(r: dict, show_text: bool) -> None:
    print(f"File: {r['file']}")
    if r["extraction_error"]:
        print(f"  EXTRACTION FAILED: {r['extraction_error']}")
        print(f"  Would route to:   {r['would_route_to']}")
        return

    print(f"  Extracted text:   {r['extracted_text_chars']} chars")
    if not show_text:
        preview = " ".join(r["extracted_text"][:_PREVIEW_CHARS].split())
        ell = "…" if r["extracted_text_chars"] > _PREVIEW_CHARS else ""
        print(f"  Preview:          {preview}{ell}")

    if r["matched_senders"]:
        print("  Sender matches:")
        for m in r["matched_senders"]:
            print(f"    - {m['canonical_name']} ({m['document_type']}) via {m['matched_on']}")
    else:
        print("  Sender matches:   none")

    print(f"  sender         =  {r['sender']}")
    print(f"  document_type  =  {r['document_type']}")
    print(f"  document_date  =  {r['document_date']}")
    print(f"  account_number =  {r['account_number']}")
    msg = f"  ({r['classification_message']})" if r["classification_message"] else ""
    print(f"  classification =  {r['classification_status']}{msg}")
    if r["rendered_filename"]:
        print(f"  rendered name  =  {r['rendered_filename']}")
    print(f"  WOULD ROUTE TO:   {r['would_route_to']}")

    if r["suggestion"]:
        s = r["suggestion"]
        print("\n  --- suggested rule (sender not recognized) ---")
        print("  Add to senders.toml:\n")
        print(_indent(s["senders_toml"]))
        print("  Add to routing.toml:\n")
        print(_indent(s["routing_toml"]))
        if not s["candidate_match_text"]:
            print("  (No good candidate match_text found — fill match_text in by hand.)")

    if show_text:
        print("\n  --- full extracted text ---")
        print(r["extracted_text"])


def _indent(block: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line if line else line for line in block.splitlines())


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="pilezero-inspect",
        description="Read a PDF and report what the pipeline would classify/route it as, "
        "and suggest a rule when the sender is unrecognized (read-only; moves nothing).",
    )
    parser.add_argument("pdf", nargs="+", help="one or more PDF files to inspect")
    parser.add_argument(
        "-c", "--config-dir",
        default=os.environ.get("PILEZERO_CONFIG_DIR") or os.getcwd(),
        help="config dir (default: $PILEZERO_CONFIG_DIR or current directory)",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--text", action="store_true", help="print the full extracted text")
    args = parser.parse_args(argv)

    config = load_config(args.config_dir)
    results = [inspect_pdf(p, config) for p in args.pdf]

    if args.json:
        print(json.dumps(results if len(results) > 1 else results[0], indent=2))
        return

    for i, r in enumerate(results):
        if i:
            print()
        _print_human(r, show_text=args.text)


if __name__ == "__main__":
    main()
