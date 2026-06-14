"""Safe file-move operations for the pilezero pipeline.

Implements a copy-verify-delete pattern so a crash mid-operation never leaves
a file existing nowhere.  The scanned PDF is the sole copy of a destroyed
paper document — data loss is unacceptable.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from .models import MoveError


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of the file at *path*."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65_536), b""):
            h.update(chunk)
    return h.hexdigest()


def _next_available_name(dest_dir: str, filename: str) -> str:
    """Return a non-colliding filename inside *dest_dir*.

    If *dest_dir/filename* does not exist, *filename* is returned unchanged.
    Otherwise a numeric suffix is appended before the extension until a free
    slot is found::

        "invoice.pdf"  ->  "invoice_01.pdf"  ->  "invoice_02.pdf"  ...

    Args:
        dest_dir: Absolute (or resolvable) path to the destination directory.
        filename: Proposed filename (basename only, e.g. ``"invoice.pdf"``).

    Returns:
        A filename (not a full path) that does not yet exist in *dest_dir*.
    """
    dest = Path(dest_dir)
    candidate = dest / filename
    if not candidate.exists():
        return filename

    stem = Path(filename).stem
    suffix = Path(filename).suffix  # includes the leading dot, e.g. ".pdf"
    counter = 1
    while True:
        new_name = f"{stem}_{counter:02d}{suffix}"
        if not (dest / new_name).exists():
            return new_name
        counter += 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def safe_move(src: str, dest_dir: str, filename: str) -> str:
    """Copy *src* to *dest_dir/filename*, verify, then remove the original.

    Safety contract
    ---------------
    * The original file at *src* is **never** removed unless the copy has been
      verified (destination exists, sizes match, SHA-256 checksums match).
    * If a collision is detected, a numeric suffix is appended to *filename*
      (``_01``, ``_02``, …) until a free name is found.  Existing files are
      never overwritten.
    * On any failure: a ``MoveError`` is raised, the source is left intact,
      and any partially-written destination file is removed so that a retry
      can re-run the collision check cleanly.

    Args:
        src:      Absolute path to the source file (the scanned PDF).
        dest_dir: Destination directory.  Created (including parents) if it
                  does not exist.
        filename: Desired basename for the file in *dest_dir*.

    Returns:
        The absolute path of the file at its final destination.

    Raises:
        MoveError: If the copy, verification, or source-removal step fails.
    """
    src_path = Path(src).resolve()
    dest_path = Path(dest_dir)

    # 1. Ensure destination directory exists.
    dest_path.mkdir(parents=True, exist_ok=True)

    # 2. Collision check — never overwrite.
    final_name = _next_available_name(str(dest_path), filename)
    final_dest = dest_path / final_name

    # 3. Copy.
    try:
        shutil.copy2(str(src_path), str(final_dest))
    except Exception as exc:
        # Attempt to clean up a partial write so a retry is clean.
        try:
            if final_dest.exists():
                final_dest.unlink()
        except Exception:
            pass
        raise MoveError(
            f"Failed to copy '{src_path}' -> '{final_dest}': {exc}"
        ) from exc

    # 4. Verify — existence, size, checksum.
    try:
        if not final_dest.exists():
            raise MoveError(
                f"Destination file missing after copy: '{final_dest}'"
            )

        src_size = src_path.stat().st_size
        dest_size = final_dest.stat().st_size
        if src_size != dest_size:
            raise MoveError(
                f"Size mismatch after copy: source={src_size} bytes, "
                f"destination={dest_size} bytes ('{final_dest}')"
            )

        src_digest = _sha256(src_path)
        dest_digest = _sha256(final_dest)
        if src_digest != dest_digest:
            raise MoveError(
                f"SHA-256 mismatch after copy: source={src_digest}, "
                f"destination={dest_digest} ('{final_dest}')"
            )
    except MoveError:
        # Clean up the failed/corrupt destination copy before re-raising.
        try:
            if final_dest.exists():
                final_dest.unlink()
        except Exception:
            pass
        raise
    except Exception as exc:
        try:
            if final_dest.exists():
                final_dest.unlink()
        except Exception:
            pass
        raise MoveError(
            f"Verification error for '{final_dest}': {exc}"
        ) from exc

    # 5. Remove source — only reached if verification succeeded.
    try:
        src_path.unlink()
    except Exception as exc:
        # Source removal failed.  The destination copy is good, but the
        # original still exists.  Surface this as an error so the caller can
        # decide how to handle the duplicate; do NOT delete the destination.
        raise MoveError(
            f"Copy verified but failed to remove source '{src_path}': {exc}"
        ) from exc

    return str(final_dest.resolve())
