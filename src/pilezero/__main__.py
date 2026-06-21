"""pilezero orchestrator — entrypoint for `python -m pilezero`.

Acquires a non-blocking flock (exits silently if another instance holds it),
batch-processes every pending file in the watched folder sequentially, and
regenerates the status report after each file. One file's failure never halts
the batch; the safe-move semantics ensure a file always exists somewhere.

Pipeline per file (spec steps 3.1–3.8):
  extract -> classify -> route -> render filename -> safe move -> log -> status
"""

from __future__ import annotations

import fcntl
import os
import sys
import time
from pathlib import Path

from .classify import classify
from .config import load_config
from .extract import extract_text
from .log import log_record
from .models import Config, FileRecord, PipelineError, Status
from .move import _next_available_name, safe_move
from .notify import notify
from .route import match_rule, render_filename, resolve_folder
from .status import generate_status_html

# Subfolders that hold triage output — never treated as pending input.
_SPECIAL_DIRS = {"_NeedsReview", "_Unmapped", "_Errored"}


def _acquire_lock(lock_path: str):
    """Non-blocking flock. Returns the open file handle, or None if held.

    The handle must stay open for the lifetime of the process; the OS releases
    the lock automatically on exit (including crashes).
    """
    Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


_STABLE_AGE = 5.0  # seconds a file must be unmodified before processing


def _list_pdfs(incoming_dir: str) -> list[Path]:
    """All top-level PDFs in the watched folder, regardless of age."""
    root = Path(incoming_dir)
    if not root.is_dir():
        return []
    return [
        entry for entry in sorted(root.iterdir())
        if not entry.is_dir()
        and not entry.name.startswith(".")
        and entry.suffix.lower() == ".pdf"
    ]


def _list_pending(incoming_dir: str) -> list[Path]:
    """Top-level PDFs in the watched folder that are stable (mtime >= 5s ago)."""
    now = time.time()
    return [p for p in _list_pdfs(incoming_dir) if now - p.stat().st_mtime >= _STABLE_AGE]


def _place(record: FileRecord, dest_dir: str, filename: str, dry_run: bool) -> str:
    """Move (or, in dry-run, compute the would-be destination for) a file."""
    if dry_run:
        # Resolve the collision-free name without touching the filesystem.
        name = _next_available_name(dest_dir, filename)
        return str(Path(dest_dir) / name)
    return safe_move(record.original_path, dest_dir, filename)


def _route_to_special(
    record: FileRecord, config: Config, subdir: str, status: Status, dry_run: bool = False
) -> None:
    """Safe-move a file into one of the _* triage folders and set its status."""
    dest_dir = str(Path(config.incoming_dir) / subdir)
    dest = _place(record, dest_dir, record.original_filename, dry_run)
    record.new_filename = Path(dest).name
    record.destination_path = dest
    record.status = status


def _regen_status(config: Config) -> None:
    """Step 3.8 — cosmetic only; never allowed to affect processing."""
    try:
        generate_status_html(config.log_path, config.status_html)
    except Exception as e:  # noqa: BLE001 - status is best-effort
        print(f"pilezero: status.html regeneration failed: {e}", file=sys.stderr)


def _process_file(path: Path, config: Config, dry_run: bool = False) -> FileRecord:
    """Run one file through the full pipeline, returning its final record."""
    record = FileRecord(
        original_path=str(path),
        original_filename=path.name,
    )

    try:
        # 3.1 extraction
        record.extracted_text = extract_text(str(path))

        # 3.2 classification
        classify(record, config.senders)
        if record.status == Status.NEEDS_REVIEW:
            _route_to_special(record, config, "_NeedsReview", Status.NEEDS_REVIEW, dry_run)
            return record

        # 3.3 routing
        rule = match_rule(record, config.rules)
        if rule is None:
            _route_to_special(record, config, "_Unmapped", Status.UNMAPPED, dry_run)
            return record

        # 3.4 filename + 3.5/3.6 collision-safe move
        filename = render_filename(rule.filename_template, record)
        dest_dir = resolve_folder(rule.folder, config)
        dest = _place(record, dest_dir, filename, dry_run)
        record.new_filename = Path(dest).name
        record.destination_path = dest
        record.status = Status.SUCCESS
        return record

    except PipelineError as e:
        _handle_error(record, config, e, dry_run)
        return record
    except Exception as e:  # noqa: BLE001 - any failure must route to _Errored
        _handle_error(record, config, e, dry_run)
        return record


def _handle_error(record: FileRecord, config: Config, exc: Exception, dry_run: bool = False) -> None:
    """Step 3.9 — route a failed file to _Errored with safe-move semantics."""
    record.status = Status.ERRORED
    record.error_message = f"{type(exc).__name__}: {exc}"
    try:
        _route_to_special(record, config, "_Errored", Status.ERRORED, dry_run)
    except Exception as move_exc:  # noqa: BLE001
        # The file could not be moved; it stays put (still backed up by Dropbox).
        record.error_message += f" | _Errored move failed: {move_exc}"
        print(
            f"pilezero: failed to move {record.original_path} to _Errored: {move_exc}",
            file=sys.stderr,
        )


def run(config_dir: str, dry_run: bool = False, quiet: bool = False) -> int:
    config = load_config(config_dir)

    lock = _acquire_lock(config.lock_path)
    if lock is None:
        # Another instance is running — exit silently (idempotent triggers).
        return 0

    counts = {s: 0 for s in Status}
    try:
        if not quiet:
            mode = "DRY RUN — no files will be moved" if dry_run else "processing"
            print(f"pilezero: {mode} {config.incoming_dir}")
        # Loop until the folder is truly empty. If files exist but aren't stable
        # yet (scanner still writing), sleep 1s and retry rather than exiting —
        # otherwise the WatchPaths trigger fires before mtime is old enough and
        # the agent exits without processing anything.
        # dry-run processes one snapshot only (files never move, loop never ends).
        while True:
            pending = _list_pending(config.incoming_dir)
            if pending:
                for path in pending:
                    record = _process_file(path, config, dry_run=dry_run)
                    counts[record.status] = counts.get(record.status, 0) + 1
                    if not quiet:
                        _print_outcome(record)
                    if not dry_run:
                        notify(record)
                        log_record(config.log_path, record)  # 3.7 — never raises
                        _regen_status(config)  # 3.8 — best-effort
            elif _list_pdfs(config.incoming_dir) and not dry_run:
                time.sleep(1)  # files present but not stable yet; wait and retry
                continue
            if not pending or dry_run:
                break
    finally:
        lock.close()  # lock released here (and by OS on any crash)

    if not quiet:
        summary = ", ".join(f"{s.value}={counts[s]}" for s in Status)
        print(f"pilezero: done. {summary}")
    return 0


def _print_outcome(record: FileRecord) -> None:
    status = record.status.value if record.status else "?"
    line = f"  [{status}] {record.original_filename}"
    if record.destination_path:
        line += f" -> {record.destination_path}"
    if record.error_message:
        line += f"  ({record.error_message})"
    print(line)
    if record.status == Status.NEEDS_REVIEW:
        print(f"    sender:  {record.sender or 'none'}")
        print(f"    date:    {record.document_date or 'not found'}")
        print(f"    account: {record.account_number or 'not found'}")
        preview = " ".join((record.extracted_text or "")[:300].split())
        if preview:
            print(f"    text:    {preview}")


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="pilezero")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="process pending PDFs in the watched folder")
    run_p.add_argument(
        "config_dir",
        nargs="?",
        default=os.environ.get("PILEZERO_CONFIG_DIR") or str(Path.home() / ".pilezero"),
        help="directory holding config.toml/senders.toml/routing.toml "
        "(default: $PILEZERO_CONFIG_DIR or ~/.pilezero)",
    )
    run_p.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would happen without moving files or writing logs",
    )
    run_p.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="suppress all output (useful when run from launchd)",
    )

    install_p = sub.add_parser(
        "install-launchd", help="install the macOS LaunchAgent (run once after setup)"
    )
    install_p.add_argument(
        "--project-dir",
        help="path to the pilezero project directory (default: auto-detected)",
    )
    install_p.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would be installed without making changes",
    )

    inspect_p = sub.add_parser(
        "inspect", help="show what the pipeline would do with a PDF (read-only)"
    )
    inspect_p.add_argument("pdf", nargs="+", help="one or more PDF files to inspect")
    inspect_p.add_argument(
        "-c", "--config-dir",
        default=os.environ.get("PILEZERO_CONFIG_DIR") or str(Path.home() / ".pilezero"),
        help="config dir (default: $PILEZERO_CONFIG_DIR or ~/.pilezero)",
    )
    inspect_p.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    inspect_p.add_argument("--text", action="store_true", help="print the full extracted text")

    args = parser.parse_args(argv)

    if args.command == "run":
        sys.exit(run(args.config_dir, dry_run=args.dry_run, quiet=args.quiet))
    elif args.command == "install-launchd":
        from .install_launchd import install_agent
        sys.exit(install_agent(project_dir=args.project_dir, dry_run=args.dry_run))
    elif args.command == "inspect":
        from .inspect import run as inspect_run
        sys.exit(inspect_run(args.pdf, args.config_dir, json_output=args.json, show_text=args.text))


if __name__ == "__main__":
    main()
