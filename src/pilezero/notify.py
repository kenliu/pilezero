"""Desktop notification module for the pilezero pipeline.

Sends macOS notifications via osascript. Best-effort: all errors are
swallowed so a notification failure never affects file processing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .models import FileRecord, Status

_TITLES = {
    Status.SUCCESS: "Filed",
    Status.NEEDS_REVIEW: "Needs Review",
    Status.UNMAPPED: "Unmapped",
    Status.ERRORED: "Error",
}


def notify(record: FileRecord) -> None:
    """Send a macOS desktop notification summarising *record*'s outcome."""
    if sys.platform != "darwin":
        return
    try:
        title = _TITLES.get(record.status, "pilezero")
        if record.status == Status.SUCCESS and record.destination_path:
            body = f"{record.new_filename}\n{Path(record.destination_path).parent}"
        elif record.status == Status.ERRORED and record.error_message:
            # Truncate long error messages so the notification stays readable.
            msg = record.error_message[:120]
            body = f"{record.original_filename}\n{msg}"
        else:
            body = record.original_filename

        script = (
            f'display notification {_quote(body)} '
            f'with title "pilezero" subtitle {_quote(title)}'
        )
        subprocess.run(
            ["osascript", "-e", script],
            timeout=5,
            capture_output=True,
        )
    except Exception:  # noqa: BLE001
        pass


def _quote(s: str) -> str:
    """Wrap *s* in AppleScript double-quotes, escaping backslashes and quotes."""
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
