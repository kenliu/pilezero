"""Text extraction for the pilezero pipeline.

Always runs ocrmypdf --force-ocr to produce a clean text layer regardless of
any embedded text left by scanner software, then extracts with PyMuPDF.
Raises ExtractionError if ocrmypdf is unavailable or produces no text.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import fitz  # pymupdf

from .models import ExtractionError

# Resolved once at import time; None means ocrmypdf is not on PATH.
_OCRMYPDF = shutil.which("ocrmypdf")


def _extract_with_fitz(pdf_path: str) -> str:
    """Return concatenated text from all pages of *pdf_path* using PyMuPDF."""
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        raise ExtractionError(f"PyMuPDF could not open {pdf_path!r}: {exc}") from exc

    pages: list[str] = []
    try:
        for page in doc:
            pages.append(page.get_text())
    finally:
        doc.close()

    return "".join(pages)


def _ocr_text(pdf_path: str) -> str:
    """Run ocrmypdf on *pdf_path* and return the resulting text layer.

    Shells out to the ocrmypdf CLI so we don't import its heavy dependency
    tree. --skip-text preserves any pages that already have a text layer.
    """
    if _OCRMYPDF is None:
        raise ExtractionError(
            f"{pdf_path!r} has no embedded text layer and ocrmypdf is not installed. "
            "Install it (e.g. `brew install ocrmypdf`) or configure your scanner to "
            "produce searchable PDFs."
        )

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [_OCRMYPDF, "--force-ocr", "--quiet", pdf_path, tmp_path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ExtractionError(
                f"ocrmypdf failed on {pdf_path!r} (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )
        text = _extract_with_fitz(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return text


def extract_text(pdf_path: str) -> str:
    """Extract text from *pdf_path*, falling back to OCR for image-only scans.

    Parameters
    ----------
    pdf_path:
        Absolute (or resolvable) path to the source PDF.

    Returns
    -------
    str
        The full OCR'd text across all pages.

    Raises
    ------
    ExtractionError
        If the PDF cannot be opened, ocrmypdf is unavailable, or OCR produces
        no text.
    """
    if not Path(pdf_path).exists():
        raise ExtractionError(f"PDF not found: {pdf_path!r}")

    text = _ocr_text(pdf_path)
    if text.strip():
        return text

    raise ExtractionError(f"{pdf_path!r}: OCR produced no text.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m pilezero.extract <pdf_path>", file=sys.stderr)
        sys.exit(1)

    extracted = extract_text(sys.argv[1])
    print(extracted[:500])
