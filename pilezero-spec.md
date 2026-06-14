# pilezero — Home Document Filing Pipeline

## Overview

A local automation pipeline that watches a ScanSnap output folder (located
inside Dropbox), classifies and renames scanned PDFs, and files them into an
organized Dropbox folder structure. No external API dependencies in Phase 1
(no LLM calls) — classification is rules-based using a sender registry.

## Critical Rule

**No file is ever silently deleted or overwritten by the pipeline.**

- Files sitting unprocessed in the watched folder are fine — they are
  already backed up via Dropbox.
- Filename collisions in any destination folder must always be resolved by
  appending a suffix — never overwrite an existing file.
- The physical paper documents are destroyed after scanning, so the scanned
  PDF is the sole copy of each document. File-move operations must be
  designed so a crash mid-operation cannot result in a file existing
  nowhere (copy to destination, verify, then remove from source).

## Triggering & Concurrency

- **Trigger mechanism**: macOS `launchd`, using:
  - `WatchPaths` on the incoming scan folder (event-driven)
  - `StartInterval` as a periodic backstop (catches anything missed)
- **Concurrency control**: `fcntl.flock` on a lock file, non-blocking
  acquire.
  - If the lock cannot be acquired, exit immediately (another instance is
    running).
  - The OS releases the lock automatically on process exit, including
    crashes — no stale-lock detection/cleanup logic needed.
- **Batch processing model**: each invocation processes *all* currently
  pending files in the watched folder sequentially (not one file per
  invocation). This makes repeated/overlapping triggers safe and
  idempotent — a second invocation that finds nothing pending simply
  exits.

## Folder Structure

All of the following live as subfolders **within the watched/incoming
Dropbox folder** (the ScanSnap output destination):

- `_NeedsReview` — sender not recognized, or a required classification
  field could not be extracted
- `_Unmapped` — sender was recognized but no routing rule matches it
- `_Errored` — any processing failure during the pipeline (extraction,
  OCR, renaming, file move, etc.)

Organized destination folders (e.g., `Bills/Electric`, `Kids/School`, etc.)
live elsewhere in Dropbox, as defined by `routing.toml`.

## Pipeline (per file, per invocation)

1. Acquire lock (`fcntl.flock`, non-blocking). If unavailable, exit
   silently.
2. List all pending files in the watched folder (excluding the
   `_NeedsReview`, `_Unmapped`, `_Errored` subfolders).
3. For each pending file, in sequence:
   1. **Text extraction**
      - Attempt to extract embedded text from the PDF.
      - If no embedded OCR text is present, run **OCRmyPDF** to add an OCR
        text layer, then re-extract.
   2. **Classification (rules-based, no LLM)**
      - Search extracted text against `senders.toml` entries
        (case-insensitive substring match on each entry's `match_text`
        values).
      - On match: use the entry's `canonical_name` as `sender` and
        `document_type` as the document's type.
      - On no match: `sender` and `document_type` are unresolved.
      - Regardless of sender match, attempt to extract:
        - `document_date` — the date on the document (not the scan date),
          via pattern/regex matching.
        - `account_number` — **last 4 digits only** of any account number
          found, via pattern/regex matching near keywords like "Account",
          "Acct", "Account #", etc. This field is optional.
      - **Required fields**: `sender`, `document_type`, `document_date`.
        If any of these could not be determined → route this file to
        `_NeedsReview` (copy file there, log status, continue to next
        file).
   3. **Routing**
      - Evaluate `routing.toml` `[[rules]]` in order (first match wins),
        matching on `sender` and/or `document_type`.
      - If a rule matches: use its `folder` and `filename_template`.
      - If no rule matches (including no catch-all): route to `_Unmapped`
        (copy file there, log status, continue to next file).
   4. **Filename rendering**
      - Render `filename_template` using available fields:
        `{date}`, `{sender}`, `{document_type}`, `{account_number}`.
      - `{date}` is formatted as `YYYY-MM-DD`.
      - Required fields (`date`, `sender`, `document_type`) are always
        present at this point (guaranteed by step 3.2's check).
      - Optional fields (`account_number`): if empty, omit the placeholder
        **and** one adjacent separator character from the rendered
        filename (e.g., `{date}_{sender}_{account_number}.pdf` with no
        account number renders as `{date}_{sender}.pdf`, not
        `{date}_{sender}_.pdf`).
   5. **Collision check**
      - If a file with the rendered filename already exists in the
        destination folder, append a numeric suffix (e.g., `_01`, `_02`)
        until a non-colliding name is found. Never overwrite.
   6. **File move**
      - Copy the file to the destination folder under the final filename.
      - Verify the copy succeeded (e.g., file exists, non-zero size, or
        checksum match).
      - Remove the original from the watched folder only after
        verification succeeds.
   7. **Logging**
      - Append a JSONL entry (see Logging section below) recording the
        outcome of this file.
   8. **Status report regeneration**
      - Regenerate `status.html` (see Observability section).
      - This step is wrapped in try/except — any failure here is
        cosmetic only and must not affect file processing or be treated
        as a pipeline error.
   9. **On any failure during steps 3.1–3.6** (extraction error, OCR
      error, file I/O error, etc.):
      - Copy the file to `_Errored` (verify, then remove original —
        same safe-move semantics as step 3.6).
      - Log the failure with status `errored` and an error message.
      - Continue to the next pending file (one file's failure must not
        halt the batch).
4. Release lock (automatic on process exit).

## Configuration Files

### `senders.toml`

Sender registry — shared source of truth for sender identity, used by
classification. Each entry:

```toml
[[senders]]
canonical_name = "PSEG"
match_text = ["PSEG", "Public Service Electric"]
document_type = "bill"

[[senders]]
canonical_name = "Lincoln Elementary"
match_text = ["Lincoln Elementary", "Lincoln Elementary School"]
document_type = "notice"
```

- `canonical_name`: the normalized sender name used in filenames, routing,
  and logs.
- `match_text`: list of strings to search for (case-insensitive substring
  match) in extracted document text. Any match identifies this sender.
- `document_type`: the document type associated with this sender. Valid
  values: `bill`, `statement`, `notice`, `correspondence`, `form`,
  `receipt`.

### `routing.toml`

Routing rules — maps classified documents to destination folders and
filename formats. Evaluated top-to-bottom, first match wins.

```toml
# Rules are evaluated in order; the first matching rule is used.

[[rules]]
sender = "PSEG"
folder = "Bills/Electric"
filename_template = "{date}_{sender}_{account_number}.pdf"

[[rules]]
sender = "Lincoln Elementary"
document_type = "notice"
folder = "Kids/School"
filename_template = "{date}_{sender}.pdf"

[[rules]]
sender = "*"
folder = "_Unmapped"
filename_template = "{date}_{sender}_{document_type}.pdf"
```

- Match fields: `sender` (matches `canonical_name` from `senders.toml`,
  `"*"` = wildcard/any), `document_type` (optional — if omitted, matches
  any document type for that sender).
- Output fields: `folder` (destination path relative to Dropbox root, or
  as configured), `filename_template` (see template variables below).
- A catch-all rule (`sender = "*"`) pointing at `_Unmapped` is optional —
  if no rule matches at all (including no catch-all), the file is routed
  to `_Unmapped` regardless.

### Filename Template Variables

- `{date}` — `document_date`, formatted `YYYY-MM-DD` (required, always
  present)
- `{sender}` — `canonical_name` (required, always present)
- `{document_type}` — document type (required, always present)
- `{account_number}` — last 4 digits, or omitted (with adjacent separator)
  if not present on the document

## Observability — `status.html`

- Regenerated after **every** file processed (step 3.8 above).
- Generation failures are non-fatal (try/except), logged but do not affect
  the pipeline.
- Displays entries from the **last 6 months** of the JSONL log.
- Contents:
  - Summary counts by status (success / needs_review / unmapped / errored)
    for the displayed period.
  - A table of recent entries: timestamp, original filename, new filename,
    destination folder, status, and (for needs_review/unmapped/errored
    entries) the reason/error message.
  - Color-coded rows by status for quick visual scanning.
  - `file://` links to PDFs in `_NeedsReview`, `_Unmapped`, and `_Errored`
    so they can be opened directly for triage.
- Output: a single static HTML file at a fixed local path (overwritten
  each run — bookmarkable).

## Logging

- Format: **JSONL** (one JSON object per line, append-only).
- Location: local filesystem, **not** synced via Dropbox.
- Per-file log entry fields:
  - `timestamp`
  - `original_filename`, `original_path`
  - `new_filename`, `destination_path` (if filed)
  - `document_type`
  - `sender`
  - `account_number` (if present)
  - `status`: one of `success`, `needs_review`, `unmapped`, `errored`
  - `error_message` (if status is `errored`)
  - `extracted_text_preview` (first ~200 chars, for debugging)
- A logging failure must never block or fail file processing — wrap
  logging in try/except; if it fails, print/log a warning and continue.

## Backend

- Language: Python
- Package management: `uv`
- Key dependencies: `ocrmypdf` (OCR fallback), a PDF text-extraction
  library (e.g., `pymupdf`/`pdfplumber`), `tomllib`/`tomli` for config
  parsing (stdlib `tomllib` if Python 3.11+).

## Known Edge Cases (monitor in practice; not addressed in Phase 1)

- **File-fully-written race**: a file mid-write by ScanSnap could
  theoretically be picked up by the pipeline before it's complete,
  causing extraction to fail and the file to land in `_NeedsReview` or
  `_Errored` even though it's actually fine moments later. Given trigger
  latency (`launchd` + batch processing), this is expected to be rare.
  Mitigate later with a simple "skip if file mtime is less than ~5 seconds
  old" check if this is observed in practice.

## Explicitly Deferred (Phase 1)

- Date/account-number extraction patterns are an implementation detail —
  reasonable regex patterns should be chosen during implementation, but
  the exact patterns are not specified here.
- Stricter confidence thresholds by document type (e.g., higher bar for
  medical/financial documents) — not implemented; all documents follow the
  same required-field check.
- Retention/cleanup rules for old filed documents — not implemented.
- Duplicate-scan detection (e.g., hash-based) — not implemented.
- Confidence scoring mechanism — not implemented; classification is
  binary (matched sender + extractable required fields, or
  `_NeedsReview`/`_Unmapped`).

## Phase 2 (Not Part of This Build)

- **LLM-based fallback classification**: for documents where the
  rules-based sender lookup in `senders.toml` finds no match, send
  extracted text to an LLM to determine `sender`, `document_type`,
  `document_date`, and `account_number`. Should be prompted with the list
  of known `canonical_name` values from `senders.toml` to encourage
  consistent naming.
- **Family member registry**: a config file mapping family member names
  (and name variants) for person-aware routing and filenames — e.g.,
  routing medical or school documents to per-person folders based on names
  found in the document text. Needs design work around multi-match
  handling (documents mentioning multiple family members).
