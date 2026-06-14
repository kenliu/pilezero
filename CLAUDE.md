# CLAUDE.md

Guidance for working in the pilezero repo. See `pilezero-spec.md` for the
authoritative behavior spec and `README.md` for user-facing docs.

## What this is

A local, rules-based pipeline that files scanned PDFs from a watched Dropbox
folder into an organized structure. Python, managed with `uv`. No LLM/API
dependencies in Phase 1.

## The one rule that overrides everything

**No file is ever silently deleted or overwritten.** Each scanned PDF is the
sole copy of a destroyed paper document. Any file operation must be
copy → verify (size + checksum) → remove-original, never a bare move/rename, and
collisions must be resolved by suffixing — never overwriting. If you touch
`move.py` or anything that relocates files, preserve these semantics and the
"a crash mid-operation must never leave a file existing nowhere" guarantee.

## Architecture

Single linear pipeline, one module per stage, all coding against the shared
contract in `pilezero/models.py` (`FileRecord`, `Status`/`DocumentType` enums,
config dataclasses, typed errors). **Do not rename `FileRecord` fields without
updating every consumer** — extract, classify, route, move, log, status all
depend on them.

```
__main__.py  orchestrator: flock, batch loop, error routing, status regen
config.py    load + validate the 3 TOML files; fail-fast on bad config
extract.py   embedded text via pymupdf (import fitz); no-text scan -> ExtractionError (OCR deferred)
classify.py  case-insensitive sender match; date/account regex extraction
route.py     first-match-wins rules; filename template render; sanitization
move.py      SAFETY-CRITICAL copy/verify/remove + collision suffixing
log.py       append-only JSONL; must NEVER raise into the pipeline
status.py    last-6-months HTML report
```

Per-file flow: `extract → classify → route → render → safe-move → log → status`.

## Routing rules that are easy to get wrong

- **Status is not set to `SUCCESS` until after the move.** classify leaves it
  `None` on the happy path; only `__main__` sets `SUCCESS`.
- **Ambiguous sender → `_NeedsReview`** (two different canonical_names, or the
  same name with conflicting document_types).
- **No routing rule match → `_Unmapped`** (even if there's no `*` catch-all).
- **Any failure in extract/classify/route/move → `_Errored`** with safe-move
  semantics; the batch continues to the next file.
- **`_`-prefixed folders** resolve under `incoming_dir`; all others under
  `dropbox_root`.
- **Absent `{account_number}`** drops the placeholder *and its preceding
  separator* from the rendered filename.
- **status.html regeneration is cosmetic** — wrapped in try/except; never let a
  status failure affect file processing or be logged as a pipeline error.
- **Logging is best-effort** — `log.py` swallows its own errors to stderr.

## Conventions

- Every module: `from __future__ import annotations`, a module docstring, typed
  signatures. Match the existing style — look at `models.py`/`config.py`.
- Use placeholder paths (`~/`, `<...>`, `USERNAME`) in configs/docs/examples.
  **Never hardcode real absolute user paths.**
- Config files (`config.toml`/`senders.toml`/`routing.toml`) are stubs; treat
  them as examples, not real data.

## Commands

```bash
uv sync                          # install deps
uv run pytest -q                 # run the full suite (66 tests)
uv run python -m pilezero        # run the pipeline against repo-dir config
uv run python -m pilezero DIR    # config from DIR (or PILEZERO_CONFIG_DIR)
```

## Testing notes

- Tests are offline/fast. There is no OCR step; a PDF with no embedded text
  layer raises `ExtractionError` and is routed to `_Errored`. OCR (an OCRmyPDF
  fallback) is deferred — don't re-add an `ocrmypdf` dependency without a reason.
- E2E tests build temp configs + pymupdf-generated PDFs with embedded text and
  run `pilezero.__main__.run()`. Mirror that pattern for new integration tests.
- If you find a real bug in a pipeline module, fix it directly and explain it —
  don't work around it in a test.
