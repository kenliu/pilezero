# pilezero

A local, rules-based automation pipeline that watches a ScanSnap output folder
(inside Dropbox), classifies and renames scanned PDFs, and files them into an
organized Dropbox folder structure. Phase 1 has **no external API / LLM
dependencies** — classification is rules-based via a sender registry.

## Critical safety rule

**No file is ever silently deleted or overwritten.** The physical paper is
destroyed after scanning, so each scanned PDF is the sole copy. Every move is
copy → verify (size + SHA-256) → remove-original, and filename collisions are
resolved by appending a numeric suffix — never by overwriting.

## How it works

Each invocation processes **all** currently pending PDFs in the watched folder,
sequentially. One file's failure never halts the batch.

```
extract → classify → route → render filename → safe-move → log → regenerate status.html
```

1. **Extract** embedded PDF text; if none, run OCRmyPDF to add a text layer and re-extract.
2. **Classify** against `senders.toml` (case-insensitive substring match) and
   extract `document_date` + `account_number` (last 4 digits) via regex.
3. **Route** via `routing.toml` rules (first match wins) to a destination folder
   and filename template.
4. **Safe-move** into place with collision-safe naming.
5. **Log** the outcome as JSONL and regenerate the `status.html` report.

Files that can't be resolved are routed to triage subfolders of the watched
folder:

| Folder         | Meaning                                                       |
|----------------|---------------------------------------------------------------|
| `_NeedsReview` | Sender unrecognized, ambiguous, or a required field missing   |
| `_Unmapped`    | Sender recognized but no routing rule matched                 |
| `_Errored`     | Any processing failure (extraction, OCR, move, etc.)          |

## Requirements

- Python ≥ 3.11 (uses stdlib `tomllib`; developed on 3.14)
- [`uv`](https://github.com/astral-sh/uv) for dependency management
- `ocrmypdf` available on `PATH` (for the OCR fallback)

## Setup

```bash
uv sync
```

Then edit the three config files (see below). All paths use `~` and are
expanded at load time.

## Configuration

| File           | Purpose                                                          |
|----------------|------------------------------------------------------------------|
| `config.toml`  | Machine paths: `dropbox_root`, `incoming_dir`, log/status/lock   |
| `senders.toml` | Sender registry: `canonical_name`, `match_text[]`, `document_type` |
| `routing.toml` | Routing rules: `sender`/`document_type` → `folder` + `filename_template` |

**Filename template variables:** `{date}` (YYYY-MM-DD), `{sender}`,
`{document_type}`, `{account_number}`. An absent `{account_number}` is dropped
along with its preceding separator.

**Folder resolution:** a `folder` starting with `_` (e.g. `_Unmapped`) resolves
under `incoming_dir`; any other folder resolves under `dropbox_root`.

Valid `document_type` values: `bill`, `statement`, `notice`, `correspondence`,
`form`, `receipt`.

## Running

```bash
uv run python -m pilezero            # uses repo dir for config
uv run python -m pilezero /path/to/config-dir
# or set PILEZERO_CONFIG_DIR
```

Concurrency is guarded by a non-blocking `flock`; a second overlapping run that
can't get the lock exits silently. Idempotent — a run with nothing pending is a
no-op.

## Automatic triggering (macOS launchd)

A LaunchAgent triggers the pipeline on folder changes (`WatchPaths`) plus a
periodic backstop (`StartInterval`). See [`launchd/README.md`](launchd/README.md)
for install steps — you must replace the placeholder paths/username first.

## Observability

- **`status.html`** — regenerated after every file; shows last-6-months summary
  counts, a color-coded table, and `file://` links to triage PDFs. Bookmark it.
- **`log.jsonl`** — append-only JSONL outcome log, stored locally (not synced
  via Dropbox).

## Tests

```bash
uv run pytest -q
```

66 tests covering each module plus end-to-end runs through the orchestrator.

## Project layout

```
pilezero/
  __main__.py   # orchestrator: lock, batch loop, error routing (python -m pilezero)
  config.py     # load + validate the three TOML configs (fail-fast)
  models.py     # shared data contract: FileRecord, enums, errors
  extract.py    # pymupdf + OCRmyPDF fallback
  classify.py   # sender match + date/account extraction
  route.py      # routing rules + filename rendering
  move.py       # safety-critical copy/verify/remove
  log.py        # non-raising JSONL logger
  status.py     # status.html generator
config.toml · senders.toml · routing.toml   # configuration
launchd/        # LaunchAgent plist + install guide
tests/          # pytest suite
TASKS.md        # implementation task breakdown
```

## Phase 1 scope

Deferred to later phases: LLM-based fallback classification, a family-member
registry for person-aware routing, retention/cleanup, duplicate-scan detection,
and confidence scoring. See the design spec for details.
