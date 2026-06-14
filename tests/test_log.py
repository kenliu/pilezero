"""Unit tests for pilezero.log."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from pilezero.log import log_record, read_entries
from pilezero.models import FileRecord, Status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _success_record() -> FileRecord:
    rec = FileRecord(
        original_path="/incoming/scan.pdf",
        original_filename="scan.pdf",
        extracted_text="PSEG Account #: 1234 Date: 2024-03-15",
        sender="PSEG",
        document_type="bill",
        document_date="2024-03-15",
        account_number="1234",
        new_filename="2024-03-15_PSEG_1234.pdf",
        destination_path="/dropbox/Bills/Electric/2024-03-15_PSEG_1234.pdf",
        status=Status.SUCCESS,
    )
    return rec


# ---------------------------------------------------------------------------
# log_record / read_entries round-trip
# ---------------------------------------------------------------------------

class TestLogRoundTrip:
    def test_round_trip_success(self, tmp_path):
        log_path = str(tmp_path / "log.jsonl")
        rec = _success_record()
        log_record(log_path, rec)

        entries = read_entries(log_path)
        assert len(entries) == 1
        e = entries[0]
        assert e["status"] == "success"
        assert e["sender"] == "PSEG"
        assert e["document_type"] == "bill"
        assert e["original_filename"] == "scan.pdf"
        assert e["new_filename"] == "2024-03-15_PSEG_1234.pdf"

    def test_extracted_text_preview_truncated(self, tmp_path):
        log_path = str(tmp_path / "log.jsonl")
        rec = _success_record()
        rec.extracted_text = "A" * 500
        log_record(log_path, rec)
        entries = read_entries(log_path)
        assert len(entries[0]["extracted_text_preview"]) == 200

    def test_multiple_records_appended(self, tmp_path):
        log_path = str(tmp_path / "log.jsonl")
        for i in range(3):
            rec = _success_record()
            rec.original_filename = f"scan{i}.pdf"
            log_record(log_path, rec)
        entries = read_entries(log_path)
        assert len(entries) == 3

    def test_error_message_included_when_set(self, tmp_path):
        log_path = str(tmp_path / "log.jsonl")
        rec = _success_record()
        rec.status = Status.NEEDS_REVIEW
        rec.error_message = "missing required fields: document_date"
        log_record(log_path, rec)
        entries = read_entries(log_path)
        assert entries[0].get("error_message") == "missing required fields: document_date"

    def test_no_error_message_field_when_not_set(self, tmp_path):
        log_path = str(tmp_path / "log.jsonl")
        rec = _success_record()
        rec.error_message = None
        log_record(log_path, rec)
        entries = read_entries(log_path)
        assert "error_message" not in entries[0]


# ---------------------------------------------------------------------------
# Unwritable path does NOT raise
# ---------------------------------------------------------------------------

class TestUnwritablePath:
    def test_unwritable_log_does_not_raise(self, tmp_path):
        # Point log at a path inside a read-only directory
        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir()
        ro_dir.chmod(0o444)
        log_path = str(ro_dir / "subdir" / "log.jsonl")
        rec = _success_record()
        # Must not raise
        try:
            log_record(log_path, rec)
        finally:
            ro_dir.chmod(0o755)  # restore to allow cleanup


# ---------------------------------------------------------------------------
# read_entries edge cases
# ---------------------------------------------------------------------------

class TestReadEntries:
    def test_missing_file_returns_empty(self, tmp_path):
        result = read_entries(str(tmp_path / "nonexistent.jsonl"))
        assert result == []

    def test_malformed_lines_skipped(self, tmp_path):
        log_path = tmp_path / "log.jsonl"
        log_path.write_text('{"status": "success"}\nNOT_JSON\n{"status": "errored"}\n')
        entries = read_entries(str(log_path))
        assert len(entries) == 2
        assert entries[0]["status"] == "success"
        assert entries[1]["status"] == "errored"

    def test_since_days_filters_old_entries(self, tmp_path):
        log_path = tmp_path / "log.jsonl"
        # Old entry (10 days ago)
        old_ts = (datetime.now(tz=timezone.utc) - timedelta(days=10)).isoformat()
        # Recent entry (1 day ago)
        recent_ts = (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()
        log_path.write_text(
            json.dumps({"status": "success", "timestamp": old_ts}) + "\n" +
            json.dumps({"status": "needs_review", "timestamp": recent_ts}) + "\n"
        )
        entries = read_entries(str(log_path), since_days=7)
        assert len(entries) == 1
        assert entries[0]["status"] == "needs_review"

    def test_since_days_none_returns_all(self, tmp_path):
        log_path = tmp_path / "log.jsonl"
        old_ts = (datetime.now(tz=timezone.utc) - timedelta(days=200)).isoformat()
        recent_ts = (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()
        log_path.write_text(
            json.dumps({"status": "success", "timestamp": old_ts}) + "\n" +
            json.dumps({"status": "needs_review", "timestamp": recent_ts}) + "\n"
        )
        entries = read_entries(str(log_path), since_days=None)
        assert len(entries) == 2
