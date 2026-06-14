"""Text extraction for the pilezero pipeline.

Attempts to extract embedded text from a PDF using PyMuPDF. If the result
is empty or whitespace-only (no OCR layer present), falls back to running
OCRmyPDF to add a text layer, then re-extracts with PyMuPDF. On any failure
raises ExtractionError.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
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
    """Extract text from *pdf_path*, falling back to OCR if no text layer exists.

    Parameters
    ----------
    pdf_path:
        Absolute (or resolvable) path to the source PDF.

    Returns
    -------
    str
        The full extracted text across all pages.

    Raises
    ------
    ExtractionError
        If the PDF cannot be opened, OCR fails, or any other extraction
        error occurs.
    """
    source = Path(pdf_path)
    if not source.exists():
        raise ExtractionError(f"PDF not found: {pdf_path!r}")

    # --- First pass: embedded text -------------------------------------------
    text = _extract_with_fitz(pdf_path)
    if text.strip():
        return text

    # --- Fallback: run OCRmyPDF into a temp file then re-extract ------------
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name

        result = subprocess.run(
            ["ocrmypdf", "--skip-text", str(source), tmp_path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ExtractionError(
                f"ocrmypdf failed for {pdf_path!r} "
                f"(exit {result.returncode}): {result.stderr.strip()}"
            )

        text = _extract_with_fitz(tmp_path)
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(
            f"OCR fallback failed for {pdf_path!r}: {exc}"
        ) from exc
    finally:
        # Clean up temp file; ignore errors (e.g. ocrmypdf never created it).
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass

    return text


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m pilezero.extract <pdf_path>", file=sys.stderr)
        sys.exit(1)

    extracted = extract_text(sys.argv[1])
    print(extracted[:500])
