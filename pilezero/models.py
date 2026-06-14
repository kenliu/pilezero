"""Shared data contracts for the pilezero pipeline.

Every pipeline module codes against the types defined here. The field names
on FileRecord are the stable contract — do not rename without updating all
consumers (extract, classify, route, move, log, status).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DocumentType(str, Enum):
    """The closed set of valid document types (validated at config load)."""

    BILL = "bill"
    STATEMENT = "statement"
    NOTICE = "notice"
    CORRESPONDENCE = "correspondence"
    FORM = "form"
    RECEIPT = "receipt"


class Status(str, Enum):
    """Terminal outcome for a single file in one pipeline pass."""

    SUCCESS = "success"
    NEEDS_REVIEW = "needs_review"
    UNMAPPED = "unmapped"
    ERRORED = "errored"


@dataclass
class FileRecord:
    """Carries one file's state through the whole pipeline.

    Populated incrementally: extract -> classify -> route -> move. The log
    and status modules read the final state.
    """

    original_path: str
    original_filename: str = ""

    # Populated by extract
    extracted_text: str = ""

    # Populated by classify
    sender: Optional[str] = None
    document_type: Optional[str] = None
    document_date: Optional[str] = None  # normalized YYYY-MM-DD
    account_number: Optional[str] = None  # last-4 only, optional

    # Populated by route + move
    new_filename: Optional[str] = None
    destination_path: Optional[str] = None

    # Outcome
    status: Optional[Status] = None
    error_message: Optional[str] = None


@dataclass
class SenderEntry:
    canonical_name: str
    match_text: list[str]
    document_type: str


@dataclass
class RoutingRule:
    sender: str  # canonical_name or "*"
    folder: str
    filename_template: str
    document_type: Optional[str] = None  # None = match any type


@dataclass
class Config:
    dropbox_root: str
    incoming_dir: str
    log_path: str
    status_html: str
    lock_path: str
    senders: list[SenderEntry] = field(default_factory=list)
    rules: list[RoutingRule] = field(default_factory=list)


# --- Typed errors -----------------------------------------------------------


class PipelineError(Exception):
    """Base for pipeline failures that route a file to _Errored."""


class ExtractionError(PipelineError):
    """Text extraction (embedded or OCR) failed."""


class MoveError(PipelineError):
    """A safe-move (copy/verify/remove) operation failed."""


class ConfigError(Exception):
    """Config files are malformed or invalid. Fatal at startup."""
