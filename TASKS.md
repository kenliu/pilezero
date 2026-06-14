# pilezero — Implementation Tasks

Decomposed for parallel agent hand-off. T1 is the gate (locks the shared
contract); T2–T7 fan out in parallel; T8–T10 integrate.

All examples use placeholder paths (`~/`, `<DROPBOX_ROOT>`) — never real
filesystem paths. Local state lives under `~/.pilezero/`.

## Foundation

### T1 — Scaffold + shared contracts + config loader
- `uv init` (name `pilezero`); deps: `pymupdf`, `ocrmypdf`. `tomllib` is
  stdlib (Python 3.14) — do NOT add `tomli`.
- Define `FileRecord` dataclass: `original_path`, `sender`,
  `document_type`, `document_date`, `account_number`, `extracted_text`,
  `status`, `error_message`, `new_filename`, `destination_path`.
- `config.py`: load + `expanduser` `config.toml`, `senders.toml`,
  `routing.toml`; validate `document_type` enum
  (`bill|statement|notice|correspondence|form|receipt`) and required keys
  at load time (fail fast).
- Write `config.toml`, `senders.toml`, `routing.toml` as documented stubs.
- Locks field names that all other tasks consume.

## Parallel (depend only on T1 contract)

### T2 — Text extraction + OCR fallback (`extract.py`)
`extract_text(pdf_path) -> str`. Embedded text via pymupdf first; if
empty/insufficient, run `ocrmypdf` to add a layer, re-extract. Raise typed
`ExtractionError` on failure.

### T3 — Classification (`classify.py`)
Case-insensitive substring match over `match_text`. Multi-match →
`_NeedsReview` (different `canonical_name`s, or same name w/ conflicting
`document_type`). Regex `document_date` (→ `YYYY-MM-DD`) and
`account_number` (last-4, near Account/Acct/Account #). Required-field
check (`sender`, `document_type`, `document_date`) → `needs_review` + reason.

### T4 — Routing + filename rendering (`route.py`)
First-match-wins rule eval (`sender`/`document_type`, `"*"` wildcard); no
match → `_Unmapped`. Template render; optional `{account_number}` omitted
WITH its preceding separator; conservative-replace sanitization on values
(not literals); `_`-prefixed folders resolve under `incoming_dir`, others
under `dropbox_root`.

### T5 — Safe file move (`move.py`)
`safe_move(src, dest_dir, filename)`: collision suffix (`_01`, `_02`…),
copy → verify (size/checksum) → remove original. Never overwrite. Typed
errors on failure.

### T6 — Logging (`log.py`)
Append-only JSONL with spec fields. Fully wrapped in try/except — never
raises into the pipeline.

### T7 — status.html generation (`status.py`)
Last-6-months of JSONL: summary counts by status, color-coded table,
`file://` links for review/unmapped/errored entries. Pure function of the
log file.

## Integration

### T8 — Orchestrator (`pilezero.py`)
`fcntl.flock` non-blocking (exit silently if held); list pending (exclude
`_*` subfolders); per-file sequential loop wiring T2→T5; `_Errored`
routing on any step failure; T6 log + T7 status (status in try/except).
One file's failure must not halt the batch.

### T9 — launchd plist (`net.kenliu.pilezero.plist`)
`WatchPaths` on incoming dir + `StartInterval` backstop. Placeholder paths
+ install instructions.

### T10 — Tests
Per-module unit tests (T2–T7) + one end-to-end fixture run through T8.
