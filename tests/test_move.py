"""Unit tests for pilezero.move."""

import pytest
from pathlib import Path

from pilezero.move import safe_move, _next_available_name
from pilezero.models import MoveError


# ---------------------------------------------------------------------------
# _next_available_name
# ---------------------------------------------------------------------------

class TestNextAvailableName:
    def test_no_collision_returns_original(self, tmp_path):
        result = _next_available_name(str(tmp_path), "invoice.pdf")
        assert result == "invoice.pdf"

    def test_collision_produces_01_suffix(self, tmp_path):
        (tmp_path / "invoice.pdf").write_bytes(b"data")
        result = _next_available_name(str(tmp_path), "invoice.pdf")
        assert result == "invoice_01.pdf"

    def test_two_collisions_produces_02_suffix(self, tmp_path):
        (tmp_path / "invoice.pdf").write_bytes(b"data")
        (tmp_path / "invoice_01.pdf").write_bytes(b"data")
        result = _next_available_name(str(tmp_path), "invoice.pdf")
        assert result == "invoice_02.pdf"

    def test_no_extension(self, tmp_path):
        (tmp_path / "doc").write_bytes(b"data")
        result = _next_available_name(str(tmp_path), "doc")
        assert result == "doc_01"

    def test_preserves_extension(self, tmp_path):
        result = _next_available_name(str(tmp_path), "file.pdf")
        assert result == "file.pdf"


# ---------------------------------------------------------------------------
# safe_move
# ---------------------------------------------------------------------------

class TestSafeMove:
    def test_copies_verifies_removes_source(self, tmp_path):
        src = tmp_path / "src" / "scan.pdf"
        src.parent.mkdir()
        src.write_bytes(b"PDF content here")

        dest_dir = tmp_path / "dest"
        result = safe_move(str(src), str(dest_dir), "scan.pdf")

        # Destination file exists
        assert Path(result).exists()
        assert Path(result).read_bytes() == b"PDF content here"
        # Source is gone
        assert not src.exists()
        # Returned path is inside dest_dir
        assert Path(result).parent == dest_dir

    def test_creates_destination_dir_if_missing(self, tmp_path):
        src = tmp_path / "scan.pdf"
        src.write_bytes(b"data")
        dest_dir = tmp_path / "new" / "deep" / "dir"
        result = safe_move(str(src), str(dest_dir), "scan.pdf")
        assert Path(result).exists()

    def test_collision_suffixing(self, tmp_path):
        src1 = tmp_path / "a.pdf"
        src1.write_bytes(b"first")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        # Place a pre-existing file at the target name
        (dest_dir / "scan.pdf").write_bytes(b"existing")

        result = safe_move(str(src1), str(dest_dir), "scan.pdf")
        assert Path(result).name == "scan_01.pdf"
        # Original existing file still intact
        assert (dest_dir / "scan.pdf").read_bytes() == b"existing"

    def test_never_overwrites(self, tmp_path):
        src = tmp_path / "scan.pdf"
        src.write_bytes(b"new content")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        existing = dest_dir / "scan.pdf"
        existing.write_bytes(b"original content")

        result = safe_move(str(src), str(dest_dir), "scan.pdf")
        # The existing file must be unchanged
        assert existing.read_bytes() == b"original content"
        # The moved file has a different name
        assert Path(result).name != "scan.pdf"

    def test_sequential_collision_suffixes(self, tmp_path):
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        # Pre-fill slots 0, _01
        (dest_dir / "doc.pdf").write_bytes(b"a")
        (dest_dir / "doc_01.pdf").write_bytes(b"b")

        src = tmp_path / "doc.pdf"
        src.write_bytes(b"c")
        result = safe_move(str(src), str(dest_dir), "doc.pdf")
        assert Path(result).name == "doc_02.pdf"

    def test_move_error_on_missing_source(self, tmp_path):
        with pytest.raises((MoveError, FileNotFoundError, OSError)):
            safe_move(str(tmp_path / "nonexistent.pdf"), str(tmp_path), "out.pdf")
