"""Tests for data quality layer: ICE validation, numbering gaps, TVA math, cabinet isolation."""
import pytest
from decimal import Decimal
from app.services.data_quality.ice_validator import validate_ice, validate_ice_batch, generate_ice
from app.services.data_quality.numbering import detect_numbering_gaps, suggest_next_number
from app.services.data_quality.tva_validator import validate_line_tva, validate_invoice_tva


class TestICEValidation:
    def test_valid_ice(self):
        ice = generate_ice("1234567890123")
        r = validate_ice(ice)
        assert r.valid

    def test_invalid_length(self):
        r = validate_ice("12345")
        assert not r.valid
        assert "15" in r.error

    def test_invalid_key(self):
        r = validate_ice("123456789012344")  # Wrong key
        assert not r.valid
        assert "clé" in r.error

    def test_non_digits(self):
        r = validate_ice("12345678901234A")
        assert not r.valid

    def test_empty_ice(self):
        r = validate_ice("")
        assert not r.valid

    def test_whitespace_ice(self):
        ice = generate_ice("1234567890123")
        r = validate_ice(f"  {ice}  ")
        assert r.valid

    def test_valid_ice_breakdown(self):
        ice = generate_ice("1234567890123")
        r = validate_ice(ice)
        assert r.rc_part == "123"
        assert r.cin_part == "4567"
        assert r.key_valid

    def test_ice_batch_duplicates(self):
        ice1 = generate_ice("1234567890123")
        ice2 = generate_ice("9876543210987")
        entries = [
            {"id": "1", "ice": ice1, "name": "A"},
            {"id": "2", "ice": ice1, "name": "B"},
            {"id": "3", "ice": ice2, "name": "C"},
        ]
        results = validate_ice_batch(entries)
        assert results[0]["valid"] and not results[0]["duplicate"]
        assert results[1]["valid"] and results[1]["duplicate"]
        assert results[2]["valid"]

    def test_generate_ice(self):
        ice = generate_ice("1234567890123")
        assert len(ice) == 15
        assert ice.isdigit()
        r = validate_ice(ice)
        assert r.valid


class TestNumberingGaps:
    def test_no_gaps(self):
        nums = [f"F{i:09d}/2025" for i in range(1, 6)]
        r = detect_numbering_gaps(nums, 2025)
        assert r.score == 100
        assert len(r.gaps) == 0

    def test_gap_detected(self):
        nums = ["F000000001/2025", "F000000002/2025", "F000000004/2025"]
        r = detect_numbering_gaps(nums, 2025)
        assert len(r.gaps) == 1
        assert r.gaps[0]["expected"] == "F000000003/2025"
        assert r.score < 100

    def test_duplicates(self):
        nums = ["F000000001/2025", "F000000001/2025"]
        r = detect_numbering_gaps(nums, 2025)
        assert len(r.duplicates) == 1

    def test_wrong_format(self):
        nums = ["INVALID", "F000000001/2025"]
        r = detect_numbering_gaps(nums, 2025)
        assert r.error_count > 0

    def test_wrong_year(self):
        nums = ["F000000001/2024"]
        r = detect_numbering_gaps(nums, 2025)
        assert r.warning_count > 0

    def test_empty_list(self):
        r = detect_numbering_gaps([], 2025)
        assert r.score == 100

    def test_suggest_next_number(self):
        nums = ["F000000001/2025", "F000000002/2025"]
        next_num = suggest_next_number(nums, 2025)
        assert next_num == "F000000003/2025"

    def test_suggest_next_empty(self):
        next_num = suggest_next_number([], 2025)
        assert next_num == "F000000001/2025"


class TestTVAMath:
    def test_valid_line(self):
        issues = validate_line_tva(
            line_number=1, quantity=Decimal("10"), unit_price=Decimal("100"),
            tva_rate=Decimal("0.20"), line_total_ht=Decimal("1000.00"),
            line_total_tva=Decimal("200.00"), line_total_ttc=Decimal("1200.00"),
        )
        assert len(issues) == 0

    def test_wrong_ht(self):
        issues = validate_line_tva(
            line_number=1, quantity=Decimal("10"), unit_price=Decimal("100"),
            tva_rate=Decimal("0.20"), line_total_ht=Decimal("999.00"),
            line_total_tva=Decimal("200.00"), line_total_ttc=Decimal("1199.00"),
        )
        assert any(i.issue_type == "math_wrong" for i in issues)

    def test_invalid_rate(self):
        issues = validate_line_tva(
            line_number=1, quantity=Decimal("1"), unit_price=Decimal("100"),
            tva_rate=Decimal("0.15"), line_total_ht=Decimal("100.00"),
            line_total_tva=Decimal("15.00"), line_total_ttc=Decimal("115.00"),
        )
        assert any(i.issue_type == "rate_invalid" for i in issues)

    def test_negative_amount(self):
        issues = validate_line_tva(
            line_number=1, quantity=Decimal("1"), unit_price=Decimal("100"),
            tva_rate=Decimal("0.20"), line_total_ht=Decimal("-100.00"),
            line_total_tva=Decimal("-20.00"), line_total_ttc=Decimal("-120.00"),
        )
        assert any(i.issue_type == "negative" for i in issues)

    def test_invoice_tva_header_mismatch(self):
        lines = [
            {"line_number": 1, "quantity": 1, "unit_price": 100, "tva_rate": 0.20,
             "line_total_ht": 100, "line_total_tva": 20, "line_total_ttc": 120},
        ]
        report = validate_invoice_tva(lines, header_ht=Decimal("200"), header_tva=Decimal("40"), header_ttc=Decimal("240"))
        assert report.error_count > 0

    def test_invoice_tva_all_correct(self):
        lines = [
            {"line_number": 1, "quantity": 1, "unit_price": 100, "tva_rate": 0.20,
             "line_total_ht": 100, "line_total_tva": 20, "line_total_ttc": 120},
            {"line_number": 2, "quantity": 2, "unit_price": 50, "tva_rate": 0.10,
             "line_total_ht": 100, "line_total_tva": 10, "line_total_ttc": 110},
        ]
        report = validate_invoice_tva(lines, header_ht=Decimal("200"), header_tva=Decimal("30"), header_ttc=Decimal("230"))
        assert report.score == 100
        assert report.error_count == 0
