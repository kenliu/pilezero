"""Status HTML generator for the pilezero pipeline.

Produces a single self-contained static HTML file summarising the last 6 months
of pipeline activity from the JSONL log.  The file is safe to open directly in
a browser (file:// protocol) and requires no network access.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote as url_quote

from pilezero.log import read_entries

# How many days of log history to display
_SINCE_DAYS = 183

# Status display metadata: (label, CSS class)
_STATUS_META: dict[str, tuple[str, str]] = {
    "success":      ("Success",      "status-success"),
    "needs_review": ("Needs Review", "status-needs-review"),
    "unmapped":     ("Unmapped",     "status-unmapped"),
    "errored":      ("Errored",      "status-errored"),
}

_STYLE = """\
<style>
  body {
    font-family: system-ui, -apple-system, sans-serif;
    font-size: 14px;
    margin: 0;
    padding: 16px 24px;
    background: #f8f9fa;
    color: #212529;
  }
  h1 { margin: 0 0 4px; font-size: 1.4rem; }
  .subtitle { color: #6c757d; margin: 0 0 20px; font-size: 0.85rem; }
  .summary {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    margin-bottom: 24px;
  }
  .summary-card {
    border-radius: 6px;
    padding: 10px 18px;
    min-width: 120px;
    text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,.08);
  }
  .summary-card .count { font-size: 2rem; font-weight: 700; line-height: 1; }
  .summary-card .label { font-size: 0.75rem; text-transform: uppercase; letter-spacing: .04em; color: #495057; }
  table {
    width: 100%;
    border-collapse: collapse;
    background: #fff;
    border-radius: 6px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,.08);
  }
  th {
    background: #343a40;
    color: #f8f9fa;
    text-align: left;
    padding: 8px 10px;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: .04em;
  }
  td { padding: 7px 10px; border-bottom: 1px solid #e9ecef; vertical-align: top; word-break: break-word; }
  tr:last-child td { border-bottom: none; }
  .badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 600;
  }
  /* row + card colours */
  .row-success      { background: #f0fdf4; }
  .row-needs-review { background: #fefce8; }
  .row-unmapped     { background: #fff7ed; }
  .row-errored      { background: #fef2f2; }

  .status-success      { background: #bbf7d0; color: #14532d; }
  .status-needs-review { background: #fef08a; color: #713f12; }
  .status-unmapped     { background: #fed7aa; color: #7c2d12; }
  .status-errored      { background: #fecaca; color: #7f1d1d; }

  .card-success      { background: #dcfce7; }
  .card-needs-review { background: #fef9c3; }
  .card-unmapped     { background: #ffedd5; }
  .card-errored      { background: #fee2e2; }

  a { color: #1d4ed8; }
  .reason { color: #6b7280; font-size: 0.82rem; }
  .empty { color: #6c757d; padding: 24px; text-align: center; }
</style>
"""


def _file_url(path: str) -> str:
    """Return a safe ``file://`` URL for *path*."""
    # url_quote keeps slashes; we only need to encode spaces and special chars.
    encoded = url_quote(path, safe="/:@")
    if not encoded.startswith("file://"):
        # Absolute POSIX paths start with /; Windows paths would start with
        # a drive letter — handle both.
        if encoded.startswith("/"):
            encoded = "file://" + encoded
        else:
            encoded = "file:///" + encoded
    return encoded


def _fmt_timestamp(ts_raw: str) -> str:
    """Return a human-readable local timestamp string, or the raw value on error."""
    try:
        dt = datetime.fromisoformat(ts_raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone()
        return local.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return ts_raw or ""


def generate_status_html(log_path: str, output_path: str) -> None:
    """Generate a self-contained status HTML file from the JSONL log.

    Reads the last 6 months of entries from *log_path* and writes a single
    static HTML page to *output_path*, overwriting any existing file.  Parent
    directories are created as needed.

    Parameters
    ----------
    log_path:
        Absolute path to the pipeline JSONL log file.
    output_path:
        Absolute path where the HTML file will be written.
    """
    entries = read_entries(log_path, since_days=_SINCE_DAYS)

    # Sort newest-first
    def _sort_key(e: dict) -> str:
        return e.get("timestamp", "")

    entries.sort(key=_sort_key, reverse=True)

    # Summary counts
    counts: dict[str, int] = {s: 0 for s in _STATUS_META}
    for entry in entries:
        status = entry.get("status", "")
        if status in counts:
            counts[status] += 1

    # --- Build HTML -----------------------------------------------------------
    generated_at = datetime.now(tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")

    parts: list[str] = []
    parts.append("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n")
    parts.append("<meta charset=\"utf-8\">\n")
    parts.append("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n")
    parts.append("<title>pilezero — status</title>\n")
    parts.append(_STYLE)
    parts.append("</head>\n<body>\n")

    parts.append("<h1>pilezero status</h1>\n")
    parts.append(
        f"<p class=\"subtitle\">Last 6 months &bull; generated {html.escape(generated_at)}</p>\n"
    )

    # Summary cards
    parts.append("<div class=\"summary\">\n")
    for status_key, (label, css_class) in _STATUS_META.items():
        card_class = "card-" + css_class.removeprefix("status-")
        parts.append(
            f'  <div class="summary-card {card_class}">\n'
            f'    <div class="count">{counts[status_key]}</div>\n'
            f'    <div class="label">{html.escape(label)}</div>\n'
            f'  </div>\n'
        )
    parts.append("</div>\n")

    # Table
    parts.append("<table>\n<thead><tr>\n")
    for col in ("Timestamp", "Original Filename", "New Filename", "Destination Folder", "Status", "Reason / Error"):
        parts.append(f"  <th>{html.escape(col)}</th>\n")
    parts.append("</tr></thead>\n<tbody>\n")

    if not entries:
        parts.append(
            f'<tr><td colspan="6" class="empty">No entries in the last 6 months.</td></tr>\n'
        )
    else:
        for entry in entries:
            status = entry.get("status", "")
            label, css_class = _STATUS_META.get(status, (status, ""))
            row_class = "row-" + css_class.removeprefix("status-") if css_class else ""

            ts_display = _fmt_timestamp(entry.get("timestamp", ""))
            original_filename = entry.get("original_filename") or ""
            new_filename = entry.get("new_filename") or ""
            destination_path = entry.get("destination_path") or ""
            original_path = entry.get("original_path") or ""

            # Destination folder is the parent directory of destination_path
            dest_folder = str(Path(destination_path).parent) if destination_path else ""
            if dest_folder == ".":
                dest_folder = ""

            # Reason/error column and optional file:// link
            error_message = entry.get("error_message") or ""
            triage_statuses = {"needs_review", "unmapped", "errored"}
            reason_html = ""
            if status in triage_statuses:
                link_path = destination_path or original_path
                if link_path:
                    url = _file_url(link_path)
                    link_name = html.escape(Path(link_path).name or link_path)
                    reason_html += f'<a href="{html.escape(url)}">{link_name}</a>'
                if error_message:
                    escaped_msg = html.escape(error_message)
                    if reason_html:
                        reason_html += f'<br><span class="reason">{escaped_msg}</span>'
                    else:
                        reason_html = f'<span class="reason">{escaped_msg}</span>'

            badge = (
                f'<span class="badge {html.escape(css_class)}">{html.escape(label)}</span>'
                if css_class
                else html.escape(status)
            )

            parts.append(f'<tr class="{html.escape(row_class)}">\n')
            parts.append(f'  <td>{html.escape(ts_display)}</td>\n')
            parts.append(f'  <td>{html.escape(original_filename)}</td>\n')
            if destination_path and new_filename:
                url = _file_url(destination_path)
                new_filename_html = f'<a href="{html.escape(url)}">{html.escape(new_filename)}</a>'
            else:
                new_filename_html = html.escape(new_filename)
            parts.append(f'  <td>{new_filename_html}</td>\n')
            parts.append(f'  <td>{html.escape(dest_folder)}</td>\n')
            parts.append(f'  <td>{badge}</td>\n')
            parts.append(f'  <td>{reason_html}</td>\n')
            parts.append('</tr>\n')

    parts.append("</tbody>\n</table>\n")
    parts.append("</body>\n</html>\n")

    html_content = "".join(parts)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_content, encoding="utf-8")
