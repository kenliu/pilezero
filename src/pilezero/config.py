"""Config loading and validation.

Loads config.toml, senders.toml, routing.toml. Validates required keys and
the document_type enum at load time and fails fast (ConfigError) so a bad
config never reaches per-file processing.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from .models import (
    Config,
    ConfigError,
    DocumentType,
    RoutingRule,
    SenderEntry,
)

_VALID_TYPES = {t.value for t in DocumentType}


def _expand(p: str) -> str:
    return str(Path(os.path.expanduser(p)).resolve(strict=False))


def _load_toml(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError as e:
        raise ConfigError(f"config file not found: {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"malformed TOML in {path}: {e}") from e


def load_config(config_dir: str | os.PathLike) -> Config:
    """Load and validate all three config files from a directory."""
    d = Path(config_dir)

    raw = _load_toml(d / "config.toml")
    for key in ("dropbox_root", "incoming_dir", "log_path", "status_html", "lock_path"):
        if key not in raw:
            raise ConfigError(f"config.toml missing required key: {key}")

    senders = _load_senders(d / "senders.toml")
    rules = _load_routing(d / "routing.toml")

    return Config(
        dropbox_root=_expand(raw["dropbox_root"]),
        incoming_dir=_expand(raw["incoming_dir"]),
        log_path=_expand(raw["log_path"]),
        status_html=_expand(raw["status_html"]),
        lock_path=_expand(raw["lock_path"]),
        senders=senders,
        rules=rules,
    )


def _load_senders(path: Path) -> list[SenderEntry]:
    raw = _load_toml(path)
    out: list[SenderEntry] = []
    for i, entry in enumerate(raw.get("senders", [])):
        for key in ("canonical_name", "match_text", "document_type"):
            if key not in entry:
                raise ConfigError(f"senders.toml entry {i} missing key: {key}")
        dt = entry["document_type"]
        if dt not in _VALID_TYPES:
            raise ConfigError(
                f"senders.toml entry {i} ({entry['canonical_name']}): "
                f"invalid document_type {dt!r}; valid: {sorted(_VALID_TYPES)}"
            )
        if not isinstance(entry["match_text"], list) or not entry["match_text"]:
            raise ConfigError(
                f"senders.toml entry {i}: match_text must be a non-empty list"
            )
        out.append(
            SenderEntry(
                canonical_name=entry["canonical_name"],
                match_text=entry["match_text"],
                document_type=dt,
            )
        )
    return out


def _load_routing(path: Path) -> list[RoutingRule]:
    raw = _load_toml(path)
    out: list[RoutingRule] = []
    for i, rule in enumerate(raw.get("rules", [])):
        for key in ("sender", "folder", "filename_template"):
            if key not in rule:
                raise ConfigError(f"routing.toml rule {i} missing key: {key}")
        dt = rule.get("document_type")
        if dt is not None and dt not in _VALID_TYPES:
            raise ConfigError(
                f"routing.toml rule {i}: invalid document_type {dt!r}"
            )
        out.append(
            RoutingRule(
                sender=rule["sender"],
                folder=rule["folder"],
                filename_template=rule["filename_template"],
                document_type=dt,
            )
        )
    return out
