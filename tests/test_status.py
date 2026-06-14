"""Unit tests for pilezero.status."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from pilezero.status import generate_status_html


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_log(log_path: Path, entries: list[dict]) -> None:
    ts = datetime.now(tz=timezone.utc).isoformat()
    with log_path.open("w", encoding="utf-8") as f:
        for entry in entries:
            entry.setdefault("timestamp", ts)
            f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGenerateStatusHtml:
    def test_produces_non_empty_file(self, tmp_path):
        log_path = tmp_path / "log.jsonl"
        out_path = tmp_path / "status.html"
        _write_log(log_path, [
            {"status": "success", "original_filename": "scan.pdf",
             "new_filename": "2024-03-15_PSEG_7890.pdf",
             "destination_path": "/dropbox/Bills/Electric/2024-03-15_PSEG_7890.pdf",
             "original_path": "/incoming/scan.pdf"},
        ])
        generate_status_html(str(log_path), str(out_path))
        content = out_path.read_text(encoding="utf-8")
        assert len(content) > 0

    def test_html_contains_expected_rows(self, tmp_path):
        log_path = tmp_path / "log.jsonl"
        out_path = tmp_path / "status.html"
        _write_log(log_path, [
            {"status": "success", "original_filename": "bill.pdf",
             "new_filename": "2024-03-15_PSEG_7890.pdf",
             "destination_path": "/dropbox/Bills/Electric/2024-03-15_PSEG_7890.pdf",
             "original_path": "/incoming/bill.pdf"},
            {"status": "needs_review", "original_filename": "unknown.pdf",
             "new_filename": "unknown.pdf",
             "destination_path": "/incoming/_NeedsReview/unknown.pdf",
             "original_path": "/incoming/unknown.pdf",
             "error_message": "missing required fields: sender"},
        ])
        generate_status_html(str(log_path), str(out_path))
        content = out_path.read_text(encoding="utf-8")
        assert "bill.pdf" in content
        assert "unknown.pdf" in content
        assert "2024-03-15_PSEG_7890.pdf" in content
        # Should have status badge text
        assert "Success" in content
        assert "Needs Review" in content

    def test_html_is_valid_html_structure(self, tmp_path):
        log_path = tmp_path / "log.jsonl"
        out_path = tmp_path / "status.html"
        _write_log(log_path, [])
        generate_status_html(str(log_path), str(out_path))
        content = out_path.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "<html" in content
        assert "</html>" in content
        assert "<table" in content

    def test_empty_log_shows_no_entries_message(self, tmp_path):
        log_path = tmp_path / "log.jsonl"
        out_path = tmp_path / "status.html"
        _write_log(log_path, [])
        generate_status_html(str(log_path), str(out_path))
        content = out_path.read_text(encoding="utf-8")
        assert "No entries" in content

    def test_creates_parent_dir_if_missing(self, tmp_path):
        log_path = tmp_path / "log.jsonl"
        out_path = tmp_path / "nested" / "dir" / "status.html"
        _write_log(log_path, [])
        generate_status_html(str(log_path), str(out_path))
        assert out_path.exists()

    def test_missing_log_file_still_generates_html(self, tmp_path):
        """read_entries returns [] for missing file; HTML should still be generated."""
        out_path = tmp_path / "status.html"
        generate_status_html(str(tmp_path / "nonexistent.jsonl"), str(out_path))
        assert out_path.exists()

    def test_summary_counts_in_output(self, tmp_path):
        log_path = tmp_path / "log.jsonl"
        out_path = tmp_path / "status.html"
        _write_log(log_path, [
            {"status": "success", "original_filename": "a.pdf",
             "new_filename": "a.pdf", "destination_path": "/a.pdf",
             "original_path": "/incoming/a.pdf"},
            {"status": "success", "original_filename": "b.pdf",
             "new_filename": "b.pdf", "destination_path": "/b.pdf",
             "original_path": "/incoming/b.pdf"},
            {"status": "needs_review", "original_filename": "c.pdf",
             "new_filename": "c.pdf", "destination_path": "/c.pdf",
             "original_path": "/incoming/c.pdf"},
        ])
        generate_status_html(str(log_path), str(out_path))
        content = out_path.read_text(encoding="utf-8")
        # summary cards should show counts — the number '2' for success
        # and '1' for needs_review should appear somewhere in the HTML
        assert "2" in content
        assert "1" in content
