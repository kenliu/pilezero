# pilezero

You go paperless by scanning physical mail and shredding the paper. But your
scanner just dumps everything into one folder as generic files, and you still have
to manually rename each scan, figure out where it belongs, and move it there.
That chore piles up and doesn't get done.

pilezero fixes this. It watches your ScanSnap output folder and automatically
files each PDF the moment it appears: it recognizes the sender, extracts the
date and account number, renames the file consistently, and moves it to the
right place in Dropbox. Scanned mail is filed instantly, with no manual work.

Classification is rules-based: you define senders and routing rules in TOML
config files. No LLM or external API required.

## Safety guarantee

The physical paper is destroyed after scanning, so each PDF is the sole copy of
that document. pilezero will **never silently delete or overwrite a file.** Every
move is copy → verify (size + SHA-256) → remove-original. Filename collisions
are resolved by appending a numeric suffix, never by overwriting.

## What it does

When triggered, pilezero processes all pending PDFs in the watched folder
sequentially. One file's failure never halts the batch.

For each file:

1. **Extract** embedded text from the PDF.
2. **Classify** against your sender registry (`senders.toml`) and extract the
   document date and last-4 account number via regex.
3. **Route** via your rules (`routing.toml`) to a destination folder and
   filename template (e.g. `Bills/Electric/2026-01-15 Pacific Gas Bill.pdf`).
4. **Move** safely into place.
5. **Log** the outcome and regenerate the `status.html` report.

Files that can't be resolved are moved to triage subfolders:

| Folder         | Meaning                                                     |
|----------------|-------------------------------------------------------------|
| `_NeedsReview` | Sender unrecognized, ambiguous, or a required field missing |
| `_Unmapped`    | Sender recognized but no routing rule matched               |
| `_Errored`     | Any processing failure (extraction, move, etc.)             |

## Requirements

- Python ≥ 3.11 (uses stdlib `tomllib`; developed on 3.14)
- [`uv`](https://github.com/astral-sh/uv) for dependency management

The only runtime Python dependency is `pymupdf` (bundles its own libraries).

### OCR

There is no OCR step. Extraction reads the PDF's embedded text layer only; a
scan with no text layer is routed to `_Errored`. **Configure your scanner to
produce searchable (OCR'd) PDFs** so documents arrive with a text layer.

## Setup

```bash
uv sync
```

Then edit the three config files (see below). All paths use `~` and are
expanded at load time.

## Configuration

| File             | Purpose                                                            |
|------------------|--------------------------------------------------------------------|
| `config.toml`    | Paths: `dropbox_root`, `incoming_dir`, log/status/lock locations   |
| `senders.toml`   | Sender registry: `canonical_name`, `match_text[]`, `document_type` |
| `routing.toml`   | Routing rules: sender/document_type → `folder` + `filename_template` |

**Filename template variables:** `{date}` (YYYY-MM-DD), `{sender}`,
`{document_type}`, `{account_number}`. An absent `{account_number}` is dropped
along with its preceding separator.

**Folder resolution:** a `folder` starting with `_` resolves under
`incoming_dir`; any other folder resolves under `dropbox_root`.

Valid `document_type` values: `bill`, `statement`, `notice`, `correspondence`,
`form`, `receipt`.

## Running

```bash
uv run pilezero              # process all pending files once
uv run pilezero -v           # same, with a per-file outcome line + summary
uv run pilezero --dry-run    # show what WOULD happen, move nothing
uv run pilezero /config/dir  # use config from another directory
```

Concurrency is guarded by a non-blocking `flock`; a second overlapping run
exits silently. A run with nothing pending is a no-op.

### Inspecting a PDF / building rules

`pilezero inspect` is a read-only tool: it reads one or more PDFs, prints the
metadata the pipeline would extract (sender matches, date, account, destination
path), and when the sender isn't recognized, suggests ready-to-paste
`senders.toml` / `routing.toml` stubs. It never moves anything.

```bash
uv run pilezero inspect scan.pdf          # report + rule suggestion
uv run pilezero inspect scan.pdf --text   # also dump the full extracted text
uv run pilezero inspect scan.pdf --json   # machine-readable output
```

Typical workflow for an unrecognized document: run `pilezero inspect`, copy the
suggested `[[senders]]` / `[[rules]]` blocks into your config, fill in the
`TODO` fields, and re-run.

## Automatic triggering (macOS launchd)

A LaunchAgent triggers the pipeline on folder changes (`WatchPaths`) plus a
periodic backstop (`StartInterval`). See [`launchd/README.md`](launchd/README.md)
for install steps. You must replace the placeholder paths/username first.

## Observability

- **`status.html`**: regenerated after every file; shows a last-6-months
  summary and a color-coded table with `file://` links to triage PDFs. Bookmark it.
- **`log.jsonl`**: append-only JSONL outcome log, stored locally (not synced via Dropbox).

## Tests

```bash
uv run pytest -q   # 66 tests covering each module + end-to-end runs
```

## Project layout

```
src/pilezero/
  __main__.py   # orchestrator: lock, batch loop, error routing
  inspect.py    # read-only PDF inspector + rule suggester
  config.py     # load + validate the three TOML configs (fail-fast)
  models.py     # shared data contract: FileRecord, enums, errors
  extract.py    # embedded text via pymupdf
  classify.py   # sender match + date/account extraction
  route.py      # routing rules + filename rendering
  move.py       # safety-critical copy/verify/remove
  log.py        # non-raising JSONL logger
  status.py     # status.html generator
config.toml · senders.toml · routing.toml   # configuration
launchd/        # LaunchAgent plist + install guide
tests/          # pytest suite
```

## Roadmap

Deferred to later phases: LLM-based fallback classification, a family-member
registry for person-aware routing, retention/cleanup, duplicate-scan detection,
and confidence scoring.
