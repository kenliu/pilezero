"""Text extraction for the pilezero pipeline.

Extracts embedded text from a PDF using PyMuPDF. If a PDF has no embedded text
layer it is treated as an extraction failure (raises ExtractionError) and the
orchestrator routes it to _Errored for manual handling.

OCR fallback (running OCRmyPDF to add a text layer for image-only scans) is
deferred for now — see the "deferred" note in the README. Configure your
scanner to produce searchable PDFs in the meantime.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz  # pymupdf

from .models import ExtractionError


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


def extract_text(pdf_path: str) -> str:
    """Extract embedded text from *pdf_path*.

    Parameters
    ----------
    pdf_path:
        Absolute (or resolvable) path to the source PDF.

    Returns
    -------
    str
        The full embedded text across all pages.

    Raises
    ------
    ExtractionError
        If the PDF cannot be opened, or has no embedded text layer (an
        image-only scan that would require OCR, which is not enabled).
    """
    source = Path(pdf_path)
    if not source.exists():
        raise ExtractionError(f"PDF not found: {pdf_path!r}")

    text = _extract_with_fitz(pdf_path)
    if text.strip():
        return text

    raise ExtractionError(
        f"{pdf_path!r} has no embedded text layer (image-only scan). OCR is not "
        "enabled; configure the scanner to produce searchable PDFs, or OCR the "
        "file manually."
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m pilezero.extract <pdf_path>", file=sys.stderr)
        sys.exit(1)

    extracted = extract_text(sys.argv[1])
    print(extracted[:500])
