"""End-to-end tests for the pilezero orchestrator.

Uses real-ish PDFs with embedded text (generated via PyMuPDF/fitz) so that
text extraction succeeds without OCR — keeping tests offline and fast.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import fitz  # pymupdf
import pytest

import pilezero.__main__ as main_mod


# ---------------------------------------------------------------------------
# PDF fixture helpers
# ---------------------------------------------------------------------------

def _make_pdf(path: Path, text: str) -> Path:
    """Create a minimal single-page PDF with embedded *text* at *path*."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=11)
    doc.save(str(path))
    doc.close()
    # Back-date so the stability check (mtime >= 5s) always passes in tests.
    old = path.stat().st_mtime - 10
    os.utime(path, (old, old))
    return path


# ---------------------------------------------------------------------------
# Config dir builder
# ---------------------------------------------------------------------------

def _build_config_dir(tmp_path: Path) -> tuple[Path, Path, Path]:
    """
    Return (config_dir, incoming_dir, dropbox_root) with config + sender +
    routing TOML files pointing everything under tmp_path.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    incoming_dir = tmp_path / "incoming"
    incoming_dir.mkdir()

    dropbox_root = tmp_path / "dropbox"
    dropbox_root.mkdir()

    log_path = tmp_path / "log.jsonl"
    status_html = tmp_path / "status.html"
    lock_path = tmp_path / "pilezero.lock"

    (config_dir / "config.toml").write_text(
        f"""
dropbox_root = "{dropbox_root}"
incoming_dir = "{incoming_dir}"
log_path     = "{log_path}"
status_html  = "{status_html}"
lock_path    = "{lock_path}"
""",
        encoding="utf-8",
    )

    (config_dir / "senders.toml").write_text(
        """
[[senders]]
canonical_name = "PSEG"
match_text     = ["PSEG", "Public Service Electric"]
document_type  = "bill"

[[senders]]
canonical_name = "Lincoln Elementary"
match_text     = ["Lincoln Elementary", "Lincoln Elementary School"]
document_type  = "notice"
""",
        encoding="utf-8",
    )

    (config_dir / "routing.toml").write_text(
        """
[[rules]]
sender            = "PSEG"
folder            = "Bills/Electric"
filename_template = "{date}_{sender}_{account_number}.pdf"

[[rules]]
sender            = "Lincoln Elementary"
document_type     = "notice"
folder            = "Kids/School"
filename_template = "{date}_{sender}.pdf"

[[rules]]
sender            = "*"
folder            = "_Unmapped"
filename_template = "{date}_{sender}_{document_type}.pdf"
""",
        encoding="utf-8",
    )

    return config_dir, incoming_dir, dropbox_root


# ---------------------------------------------------------------------------
# E2E test
# ---------------------------------------------------------------------------

class TestE2E:
    def test_pseg_bill_filed_correctly(self, tmp_path):
        config_dir, incoming_dir, dropbox_root = _build_config_dir(tmp_path)

        pseg_text = (
            "PSEG Public Service Electric\n"
            "Account #: 1234567890\n"
            "Date: 03/15/2024\n"
            "Your monthly bill enclosed."
        )
        _make_pdf(incoming_dir / "pseg_scan.pdf", pseg_text)

        ret = main_mod.run(str(config_dir))
        assert ret == 0

        # Source file consumed
        assert not (incoming_dir / "pseg_scan.pdf").exists()

        # Filed in Bills/Electric with expected name
        dest_dir = dropbox_root / "Bills" / "Electric"
        filed = list(dest_dir.glob("*.pdf"))
        assert len(filed) == 1
        assert filed[0].name == "2024-03-15_PSEG_7890.pdf"

        # JSONL log entry
        log_path = tmp_path / "log.jsonl"
        entries = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
        assert len(entries) == 1
        e = entries[0]
        assert e["status"] == "success"
        assert e["sender"] == "PSEG"
        assert e["new_filename"] == "2024-03-15_PSEG_7890.pdf"

        # status.html generated
        assert (tmp_path / "status.html").exists()
        assert (tmp_path / "status.html").stat().st_size > 0

    def test_unknown_sender_goes_to_needs_review(self, tmp_path):
        config_dir, incoming_dir, dropbox_root = _build_config_dir(tmp_path)

        unknown_text = (
            "Totally Unknown Sender Corp\n"
            "Invoice date: 2024-05-10\n"
            "Amount due: $99.00"
        )
        _make_pdf(incoming_dir / "unknown_scan.pdf", unknown_text)

        ret = main_mod.run(str(config_dir))
        assert ret == 0

        # Source consumed
        assert not (incoming_dir / "unknown_scan.pdf").exists()

        # File in _NeedsReview
        needs_review_dir = incoming_dir / "_NeedsReview"
        assert needs_review_dir.is_dir()
        filed = list(needs_review_dir.glob("*.pdf"))
        assert len(filed) == 1

        # Log entry has needs_review status
        log_path = tmp_path / "log.jsonl"
        entries = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
        assert len(entries) == 1
        assert entries[0]["status"] == "needs_review"

    def test_both_pseg_and_unknown_processed_in_batch(self, tmp_path):
        config_dir, incoming_dir, dropbox_root = _build_config_dir(tmp_path)

        pseg_text = (
            "PSEG Public Service Electric\n"
            "Account #: 9998887771\n"
            "Date: 2024-06-01"
        )
        unknown_text = (
            "Random Corp XYZ\n"
            "Date: 2024-06-15"
        )
        _make_pdf(incoming_dir / "pseg.pdf", pseg_text)
        _make_pdf(incoming_dir / "unknown.pdf", unknown_text)

        ret = main_mod.run(str(config_dir))
        assert ret == 0

        # Both source files consumed
        assert not (incoming_dir / "pseg.pdf").exists()
        assert not (incoming_dir / "unknown.pdf").exists()

        # PSEG filed
        filed = list((dropbox_root / "Bills" / "Electric").glob("*.pdf"))
        assert len(filed) == 1

        # Unknown in _NeedsReview
        needs_review = list((incoming_dir / "_NeedsReview").glob("*.pdf"))
        assert len(needs_review) == 1

        # Two log entries
        log_path = tmp_path / "log.jsonl"
        entries = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
        assert len(entries) == 2
        statuses = {e["status"] for e in entries}
        assert "success" in statuses
        assert "needs_review" in statuses

    def test_idempotency_second_run_adds_no_entries(self, tmp_path):
        config_dir, incoming_dir, dropbox_root = _build_config_dir(tmp_path)

        # First run with one file
        pseg_text = (
            "PSEG Public Service Electric\n"
            "Account #: 1234567890\n"
            "Date: 2024-03-15"
        )
        _make_pdf(incoming_dir / "pseg.pdf", pseg_text)
        main_mod.run(str(config_dir))

        log_path = tmp_path / "log.jsonl"
        entries_after_first = [l for l in log_path.read_text().splitlines() if l.strip()]
        assert len(entries_after_first) == 1

        # Second run — nothing pending
        ret = main_mod.run(str(config_dir))
        assert ret == 0

        entries_after_second = [l for l in log_path.read_text().splitlines() if l.strip()]
        assert len(entries_after_second) == 1  # no new entries

    def test_lincoln_elementary_filed_correctly(self, tmp_path):
        config_dir, incoming_dir, dropbox_root = _build_config_dir(tmp_path)

        text = (
            "Lincoln Elementary School\n"
            "Parent Notice — Field Trip\n"
            "Date: April 20, 2024"
        )
        _make_pdf(incoming_dir / "school_notice.pdf", text)

        ret = main_mod.run(str(config_dir))
        assert ret == 0

        assert not (incoming_dir / "school_notice.pdf").exists()

        dest_dir = dropbox_root / "Kids" / "School"
        filed = list(dest_dir.glob("*.pdf"))
        assert len(filed) == 1
        assert filed[0].name == "2024-04-20_Lincoln_Elementary.pdf"
