"""Unit tests for pilezero.classify."""

from pilezero.classify import classify, _extract_date, _extract_account
from pilezero.models import FileRecord, SenderEntry, Status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_senders():
    return [
        SenderEntry(
            canonical_name="PSEG",
            match_text=["PSEG", "Public Service Electric"],
            document_type="bill",
        ),
        SenderEntry(
            canonical_name="Lincoln Elementary",
            match_text=["Lincoln Elementary", "Lincoln Elementary School"],
            document_type="notice",
        ),
    ]


def _record(text: str) -> FileRecord:
    return FileRecord(original_path="/tmp/test.pdf", extracted_text=text)


# ---------------------------------------------------------------------------
# Sender matching
# ---------------------------------------------------------------------------

class TestSenderMatch:
    def test_single_sender_matched(self):
        senders = _make_senders()
        rec = _record("PSEG Public Service Electric Account #: 1234 Date: 2024-01-01")
        result = classify(rec, senders)
        assert result.sender == "PSEG"
        assert result.document_type == "bill"
        assert result.status is None  # happy path — status set by move step

    def test_ambiguous_senders_needs_review(self):
        """Two different canonical names matched → NEEDS_REVIEW."""
        senders = _make_senders()
        rec = _record("PSEG Public Service Electric Lincoln Elementary 2024-01-01")
        result = classify(rec, senders)
        assert result.status == Status.NEEDS_REVIEW
        assert "ambiguous sender" in (result.error_message or "")

    def test_conflicting_document_type_needs_review(self):
        """Same canonical_name but two entries with different document_types → NEEDS_REVIEW."""
        senders = [
            SenderEntry(canonical_name="Acme", match_text=["Acme Corp"], document_type="bill"),
            SenderEntry(canonical_name="Acme", match_text=["Acme Invoice"], document_type="receipt"),
        ]
        rec = _record("Acme Corp Acme Invoice Date: 2024-05-01")
        result = classify(rec, senders)
        assert result.status == Status.NEEDS_REVIEW
        assert "ambiguous document_type" in (result.error_message or "")

    def test_no_sender_match_missing_required_fields(self):
        """No sender match → required fields missing → NEEDS_REVIEW."""
        senders = _make_senders()
        rec = _record("Random text with no known sender but a date 2024-01-01")
        result = classify(rec, senders)
        assert result.status == Status.NEEDS_REVIEW
        assert "no sender recognized" in (result.error_message or "")


# ---------------------------------------------------------------------------
# Date extraction
# ---------------------------------------------------------------------------

class TestDateExtraction:
    def test_iso_format(self):
        assert _extract_date("Invoice date: 2024-03-15") == "2024-03-15"

    def test_mdy4_format(self):
        assert _extract_date("Date: 03/15/2024") == "2024-03-15"

    def test_mdy2_format(self):
        # YY -> 2000+YY
        assert _extract_date("Date: 03/15/24") == "2024-03-15"

    def test_month_name_long(self):
        assert _extract_date("January 15, 2024") == "2024-01-15"

    def test_month_name_short(self):
        assert _extract_date("Jan 15 2024") == "2024-01-15"

    def test_day_month_year(self):
        assert _extract_date("15 March 2024") == "2024-03-15"

    def test_no_date_returns_none(self):
        assert _extract_date("No date here at all.") is None

    def test_invalid_date_skipped(self):
        # Month 13 is invalid; should skip and return None (no other date present)
        assert _extract_date("2024-13-01") is None


# ---------------------------------------------------------------------------
# Account number extraction
# ---------------------------------------------------------------------------

class TestAccountExtraction:
    def test_last4_from_long_number(self):
        assert _extract_account("Account #: 1234567890") == "7890"

    def test_last4_from_4digit_number(self):
        assert _extract_account("Acct: 5678") == "5678"

    def test_account_number_keyword(self):
        assert _extract_account("Account Number 00001234") == "1234"

    def test_no_account_returns_none(self):
        assert _extract_account("No account info here.") is None


# ---------------------------------------------------------------------------
# Missing required field scenarios
# ---------------------------------------------------------------------------

class TestRequiredFields:
    def test_missing_date_needs_review(self):
        senders = _make_senders()
        rec = _record("PSEG Public Service Electric")  # no date
        result = classify(rec, senders)
        assert result.status == Status.NEEDS_REVIEW
        assert "date not found" in result.error_message

    def test_all_fields_present_no_review(self):
        senders = _make_senders()
        rec = _record("PSEG Account #: 1234567890 Date: 2024-03-15")
        result = classify(rec, senders)
        assert result.status is None
        assert result.sender == "PSEG"
        assert result.document_date == "2024-03-15"
        assert result.account_number == "7890"
