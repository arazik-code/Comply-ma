"""
Moteur de calcul TVA conforme aux taux marocains.

Taux standards (configurables dans la table tva_rates) :
  - 20 %  (standard)
  - 14 %  (réduit)
  - 10 %  (réduit)
  - 7 %   (réduit)
"""
from decimal import Decimal, ROUND_HALF_UP


def calc_line_totals(quantity: Decimal, unit_price: Decimal, tva_rate: Decimal) -> dict:
    """
    Calcule les totaux d'une ligne de facture.

    Retourne { line_total_ht, line_total_tva, line_total_ttc }
    arrondis à 2 décimales (règle commerciale standard).
    """
    ht = (quantity * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    tva = (ht * tva_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    ttc = (ht + tva).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "line_total_ht": ht,
        "line_total_tva": tva,
        "line_total_ttc": ttc,
    }


def calc_invoice_totals(lines: list[dict]) -> dict:
    """
    Agrège les totaux de toutes les lignes d'une facture.

    Chaque ligne doit contenir les clés :
      line_total_ht, line_total_tva, line_total_ttc
    """
    total_ht = sum((line["line_total_ht"] for line in lines), Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_tva = sum((line["line_total_tva"] for line in lines), Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_ttc = sum((line["line_total_ttc"] for line in lines), Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "total_ht": total_ht,
        "total_tva": total_tva,
        "total_ttc": total_ttc,
    }


TVA_RATES_DEFAULT = [
    Decimal("0.20"),
    Decimal("0.14"),
    Decimal("0.10"),
    Decimal("0.07"),
]
