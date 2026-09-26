"""
Tests de calcul TVA — conformité aux règles marocaines.
"""
from decimal import Decimal

import pytest

from app.services.tva import calc_line_totals, calc_invoice_totals


class TestLineTotals:
    """Calcul des totaux par ligne de facture."""

    def test_simple_line_20pct(self):
        """1 article à 100 DH avec TVA 20%."""
        result = calc_line_totals(Decimal("1"), Decimal("100"), Decimal("0.20"))
        assert result["line_total_ht"] == Decimal("100.00")
        assert result["line_total_tva"] == Decimal("20.00")
        assert result["line_total_ttc"] == Decimal("120.00")

    def test_multiple_qty_14pct(self):
        """3 articles à 50 DH avec TVA 14%."""
        result = calc_line_totals(Decimal("3"), Decimal("50"), Decimal("0.14"))
        assert result["line_total_ht"] == Decimal("150.00")
        assert result["line_total_tva"] == Decimal("21.00")
        assert result["line_total_ttc"] == Decimal("171.00")

    def test_10pct_tva(self):
        """TVA à 10%."""
        result = calc_line_totals(Decimal("1"), Decimal("200"), Decimal("0.10"))
        assert result["line_total_ht"] == Decimal("200.00")
        assert result["line_total_tva"] == Decimal("20.00")
        assert result["line_total_ttc"] == Decimal("220.00")

    def test_07pct_tva(self):
        """TVA à 7% (taux réduit)."""
        result = calc_line_totals(Decimal("1"), Decimal("100"), Decimal("0.07"))
        assert result["line_total_ht"] == Decimal("100.00")
        assert result["line_total_tva"] == Decimal("7.00")
        assert result["line_total_ttc"] == Decimal("107.00")

    def test_decimal_quantities(self):
        """Quantités décimales (ex: 2.5 heures)."""
        result = calc_line_totals(Decimal("2.5"), Decimal("80"), Decimal("0.20"))
        assert result["line_total_ht"] == Decimal("200.00")
        assert result["line_total_tva"] == Decimal("40.00")
        assert result["line_total_ttc"] == Decimal("240.00")

    def test_rounding_two_decimals(self):
        """L'arrondi doit être à 2 décimales (règle commerciale)."""
        result = calc_line_totals(Decimal("1"), Decimal("99.99"), Decimal("0.20"))
        assert result["line_total_ht"] == Decimal("99.99")
        assert result["line_total_tva"] == Decimal("20.00")  # 99.99 * 0.20 = 19.998 -> 20.00
        assert result["line_total_ttc"] == Decimal("119.99")


class TestInvoiceTotals:
    """Agrégation des totaux d'une facture complète."""

    def test_single_line(self):
        """Facture avec une seule ligne."""
        lines = [
            {"line_total_ht": Decimal("100.00"), "line_total_tva": Decimal("20.00"), "line_total_ttc": Decimal("120.00")},
        ]
        result = calc_invoice_totals(lines)
        assert result["total_ht"] == Decimal("100.00")
        assert result["total_tva"] == Decimal("20.00")
        assert result["total_ttc"] == Decimal("120.00")

    def test_multiple_lines_same_rate(self):
        """Facture avec plusieurs lignes au même taux."""
        lines = [
            {"line_total_ht": Decimal("100.00"), "line_total_tva": Decimal("20.00"), "line_total_ttc": Decimal("120.00")},
            {"line_total_ht": Decimal("200.00"), "line_total_tva": Decimal("40.00"), "line_total_ttc": Decimal("240.00")},
        ]
        result = calc_invoice_totals(lines)
        assert result["total_ht"] == Decimal("300.00")
        assert result["total_tva"] == Decimal("60.00")
        assert result["total_ttc"] == Decimal("360.00")

    def test_mixed_tva_rates(self):
        """Facture avec lignes à différents taux TVA."""
        lines = [
            {"line_total_ht": Decimal("100.00"), "line_total_tva": Decimal("20.00"), "line_total_ttc": Decimal("120.00")},
            {"line_total_ht": Decimal("100.00"), "line_total_tva": Decimal("14.00"), "line_total_ttc": Decimal("114.00")},
            {"line_total_ht": Decimal("100.00"), "line_total_tva": Decimal("7.00"), "line_total_ttc": Decimal("107.00")},
        ]
        result = calc_invoice_totals(lines)
        assert result["total_ht"] == Decimal("300.00")
        assert result["total_tva"] == Decimal("41.00")
        assert result["total_ttc"] == Decimal("341.00")

    def test_empty_lines(self):
        """Facture sans ligne doit retourner 0."""
        result = calc_invoice_totals([])
        assert result["total_ht"] == Decimal("0.00")
        assert result["total_tva"] == Decimal("0.00")
        assert result["total_ttc"] == Decimal("0.00")
