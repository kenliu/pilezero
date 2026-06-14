"""Unit tests for pilezero.route."""

from pilezero.models import Config, FileRecord, RoutingRule
from pilezero.route import match_rule, render_filename, resolve_folder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rec(**kwargs) -> FileRecord:
    defaults = dict(
        original_path="/tmp/test.pdf",
        sender="PSEG",
        document_type="bill",
        document_date="2024-03-15",
        account_number="7890",
    )
    defaults.update(kwargs)
    return FileRecord(**defaults)


def _config(dropbox_root="/dropbox", incoming_dir="/incoming") -> Config:
    return Config(
        dropbox_root=dropbox_root,
        incoming_dir=incoming_dir,
        log_path="/tmp/log.jsonl",
        status_html="/tmp/status.html",
        lock_path="/tmp/pz.lock",
    )


def _rules():
    return [
        RoutingRule(sender="PSEG", folder="Bills/Electric",
                    filename_template="{date}_{sender}_{account_number}.pdf"),
        RoutingRule(sender="Lincoln Elementary", folder="Kids/School",
                    filename_template="{date}_{sender}.pdf", document_type="notice"),
        RoutingRule(sender="*", folder="_Unmapped",
                    filename_template="{date}_{sender}_{document_type}.pdf"),
    ]


# ---------------------------------------------------------------------------
# match_rule
# ---------------------------------------------------------------------------

class TestMatchRule:
    def test_first_match_wins(self):
        rules = _rules()
        rec = _rec(sender="PSEG", document_type="bill")
        rule = match_rule(rec, rules)
        assert rule is not None
        assert rule.folder == "Bills/Electric"

    def test_wildcard_catches_unmatched_sender(self):
        rules = _rules()
        rec = _rec(sender="UnknownCo", document_type="statement")
        rule = match_rule(rec, rules)
        assert rule is not None
        assert rule.folder == "_Unmapped"

    def test_document_type_filter_matches(self):
        rules = [
            RoutingRule(sender="Lincoln Elementary", folder="Kids/School",
                        filename_template="{date}_{sender}.pdf", document_type="notice"),
        ]
        rec = _rec(sender="Lincoln Elementary", document_type="notice")
        rule = match_rule(rec, rules)
        assert rule is not None
        assert rule.folder == "Kids/School"

    def test_document_type_filter_no_match(self):
        """If rule specifies document_type=notice but record has bill, no match."""
        rules = [
            RoutingRule(sender="Lincoln Elementary", folder="Kids/School",
                        filename_template="{date}_{sender}.pdf", document_type="notice"),
        ]
        rec = _rec(sender="Lincoln Elementary", document_type="bill")
        rule = match_rule(rec, rules)
        assert rule is None

    def test_no_rules_returns_none(self):
        rec = _rec()
        assert match_rule(rec, []) is None

    def test_rule_with_no_document_type_matches_any(self):
        rules = [
            RoutingRule(sender="PSEG", folder="Bills/Electric",
                        filename_template="{date}_{sender}.pdf", document_type=None),
        ]
        rec = _rec(sender="PSEG", document_type="statement")
        rule = match_rule(rec, rules)
        assert rule is not None


# ---------------------------------------------------------------------------
# render_filename
# ---------------------------------------------------------------------------

class TestRenderFilename:
    def test_with_account_number(self):
        rec = _rec(sender="PSEG", document_date="2024-03-15", account_number="7890")
        result = render_filename("{date}_{sender}_{account_number}.pdf", rec)
        assert result == "2024-03-15_PSEG_7890.pdf"

    def test_without_account_number_drops_separator(self):
        rec = _rec(sender="PSEG", document_date="2024-03-15", account_number=None)
        result = render_filename("{date}_{sender}_{account_number}.pdf", rec)
        assert result == "2024-03-15_PSEG.pdf"

    def test_without_account_number_no_trailing_sep(self):
        """Separator before {account_number} is dropped, not left dangling."""
        rec = _rec(sender="PSEG", document_date="2024-03-15", account_number=None)
        result = render_filename("{date}_{sender}_{account_number}.pdf", rec)
        assert not result.endswith("_.pdf")

    def test_hostile_sender_name_sanitized(self):
        """Slashes and colons in sender name are replaced with '-'."""
        rec = _rec(sender="Dr. Smith/Jones", document_date="2024-06-01",
                   document_type="statement", account_number=None)
        result = render_filename("{date}_{sender}_{document_type}.pdf", rec)
        # / → -, whitespace → _, leading . preserved as-is in literal but
        # the dot in "Dr." is not leading because the value starts with 'D'
        assert "/" not in result
        assert "Dr." in result
        assert "Smith-Jones" in result

    def test_whitespace_in_sender_collapsed(self):
        rec = _rec(sender="Lincoln Elementary", document_date="2024-01-01",
                   account_number=None)
        result = render_filename("{date}_{sender}.pdf", rec)
        assert "Lincoln_Elementary" in result

    def test_all_fields_rendered(self):
        rec = _rec(sender="Acme", document_type="receipt",
                   document_date="2023-12-01", account_number="1234")
        result = render_filename("{date}_{sender}_{document_type}_{account_number}.pdf", rec)
        assert result == "2023-12-01_Acme_receipt_1234.pdf"


# ---------------------------------------------------------------------------
# resolve_folder
# ---------------------------------------------------------------------------

class TestResolveFolder:
    def test_underscore_prefix_resolves_to_incoming(self):
        cfg = _config(dropbox_root="/dropbox", incoming_dir="/incoming")
        result = resolve_folder("_NeedsReview", cfg)
        assert result == "/incoming/_NeedsReview"

    def test_normal_folder_resolves_to_dropbox_root(self):
        cfg = _config(dropbox_root="/dropbox", incoming_dir="/incoming")
        result = resolve_folder("Bills/Electric", cfg)
        assert result == "/dropbox/Bills/Electric"

    def test_unmapped_under_incoming(self):
        cfg = _config(dropbox_root="/dropbox", incoming_dir="/incoming")
        result = resolve_folder("_Unmapped", cfg)
        assert result == "/incoming/_Unmapped"
