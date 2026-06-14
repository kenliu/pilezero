"""Logging module for the pilezero pipeline.

Appends JSONL entries recording the outcome of each processed file, and
provides a reader used by the status.html generator.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from pilezero.models import FileRecord, Status


def log_record(log_path: str, record: FileRecord) -> None:
    """Append a JSONL entry for *record* to *log_path*.

    Creates parent directories as needed. A failure here must never
    propagate into the pipeline — any exception is caught, a warning is
    printed to stderr, and the function returns normally.
    """
    try:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        obj: dict = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "original_filename": record.original_filename,
            "original_path": record.original_path,
            "new_filename": record.new_filename,
            "destination_path": record.destination_path,
            "document_type": record.document_type,
            "sender": record.sender,
            "account_number": record.account_number,
            "status": record.status.value if isinstance(record.status, Status) else record.status,
        }

        if record.error_message:
            obj["error_message"] = record.error_message

        preview = (record.extracted_text or "")[:200]
        obj["extracted_text_preview"] = preview

        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj) + "\n")

    except Exception as err:  # noqa: BLE001
        print(f"pilezero: logging failed: {err}", file=sys.stderr)


def read_entries(log_path: str, since_days: int | None = None) -> list[dict]:
    """Return parsed JSONL entries from *log_path*.

    Malformed lines are silently skipped. If the file does not exist an
    empty list is returned. When *since_days* is given, only entries whose
    ``timestamp`` falls within the last *since_days* days are returned.
    """
    path = Path(log_path)
    if not path.exists():
        return []

    entries: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []

    if since_days is not None:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=since_days)
        filtered: list[dict] = []
        for entry in entries:
            ts_raw = entry.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_raw)
                # Make timezone-aware if naive
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    filtered.append(entry)
            except (ValueError, TypeError):
                # Keep entries with unparseable timestamps when filtering
                filtered.append(entry)
        return filtered

    return entries
