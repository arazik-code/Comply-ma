"""
TVA Math Validation — verifies tax calculations on invoices and lines.

Authorized DGI rates: 0%, 7%, 10%, 14%, 20%
Checks: line-level math, header-level math, cross-line consistency.
"""
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP


AUTHORIZED_TVA_RATES = {
    Decimal("0.00"), Decimal("0.07"), Decimal("0.10"),
    Decimal("0.14"), Decimal("0.20"),
}

TOLERANCE = Decimal("0.02")


@dataclass
class TVAIssue:
    issue_type: str  # rate_invalid | math_wrong | header_mismatch | missing_tva | negative
    severity: str    # error | warning
    line_number: int
    detail: str


@dataclass
class TVAReport:
    total_lines: int
    issues: list[TVAIssue] = field(default_factory=list)
    computed_ht: Decimal = Decimal("0.00")
    computed_tva: Decimal = Decimal("0.00")
    computed_ttc: Decimal = Decimal("0.00")
    declared_ht: Decimal = Decimal("0.00")
    declared_tva: Decimal = Decimal("0.00")
    declared_ttc: Decimal = Decimal("0.00")
    score: int = 100

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")


def _q(value: Decimal) -> Decimal:
    """Round to 2 decimal places."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def validate_line_tva(
    line_number: int,
    quantity: Decimal,
    unit_price: Decimal,
    tva_rate: Decimal,
    line_total_ht: Decimal,
    line_total_tva: Decimal,
    line_total_ttc: Decimal,
) -> list[TVAIssue]:
    """Validate TVA math on a single invoice line."""
    issues = []

    # 1. Rate must be authorized
    if tva_rate not in AUTHORIZED_TVA_RATES:
        issues.append(TVAIssue(
            issue_type="rate_invalid", severity="error", line_number=line_number,
            detail=f"Taux TVA {tva_rate * 100:.1f}% non autorisé (autorisés: 0, 7, 10, 14, 20%)",
        ))

    # 2. HT = quantity × unit_price
    expected_ht = _q(quantity * unit_price)
    if abs(expected_ht - line_total_ht) > TOLERANCE:
        issues.append(TVAIssue(
            issue_type="math_wrong", severity="error", line_number=line_number,
            detail=f"HT incorrect: {line_total_ht:.2f} ≠ {quantity} × {unit_price:.2f} = {expected_ht:.2f}",
        ))

    # 3. TVA = HT × rate
    expected_tva = _q(line_total_ht * tva_rate)
    if abs(expected_tva - line_total_tva) > TOLERANCE:
        issues.append(TVAIssue(
            issue_type="math_wrong", severity="error", line_number=line_number,
            detail=f"TVA incorrecte: {line_total_tva:.2f} ≠ {line_total_ht:.2f} × {tva_rate * 100:.1f}% = {expected_tva:.2f}",
        ))

    # 4. TTC = HT + TVA
    expected_ttc = _q(line_total_ht + line_total_tva)
    if abs(expected_ttc - line_total_ttc) > TOLERANCE:
        issues.append(TVAIssue(
            issue_type="math_wrong", severity="error", line_number=line_number,
            detail=f"TTC incorrect: {line_total_ttc:.2f} ≠ {line_total_ht:.2f} + {line_total_tva:.2f} = {expected_ttc:.2f}",
        ))

    # 5. Non-negative
    if line_total_ht < 0 or line_total_tva < 0 or line_total_ttc < 0:
        issues.append(TVAIssue(
            issue_type="negative", severity="error", line_number=line_number,
            detail=f"Montants négatifs: HT={line_total_ht:.2f}, TVA={line_total_tva:.2f}, TTC={line_total_ttc:.2f}",
        ))

    return issues


def validate_invoice_tva(
    lines: list[dict],
    header_ht: Decimal,
    header_tva: Decimal,
    header_ttc: Decimal,
) -> TVAReport:
    """
    Validate TVA math across all lines and header totals.
    Each line dict: {line_number, quantity, unit_price, tva_rate, line_total_ht, line_total_tva, line_total_ttc}
    """
    report = TVAReport(total_lines=len(lines))
    computed_ht = Decimal("0.00")
    computed_tva = Decimal("0.00")
    computed_ttc = Decimal("0.00")

    for line in lines:
        line_issues = validate_line_tva(
            line_number=line.get("line_number", 0),
            quantity=Decimal(str(line.get("quantity", 0))),
            unit_price=Decimal(str(line.get("unit_price", 0))),
            tva_rate=Decimal(str(line.get("tva_rate", 0))),
            line_total_ht=Decimal(str(line.get("line_total_ht", 0))),
            line_total_tva=Decimal(str(line.get("line_total_tva", 0))),
            line_total_ttc=Decimal(str(line.get("line_total_ttc", 0))),
        )
        report.issues.extend(line_issues)

        computed_ht += Decimal(str(line.get("line_total_ht", 0)))
        computed_tva += Decimal(str(line.get("line_total_tva", 0)))
        computed_ttc += Decimal(str(line.get("line_total_ttc", 0)))

    report.computed_ht = computed_ht
    report.computed_tva = computed_tva
    report.computed_ttc = computed_ttc
    report.declared_ht = header_ht
    report.declared_tva = header_tva
    report.declared_ttc = header_ttc

    # Header-level checks
    if abs(computed_ht - header_ht) > TOLERANCE:
        report.issues.append(TVAIssue(
            issue_type="header_mismatch", severity="error", line_number=0,
            detail=f"Total HT facture ({header_ht:.2f}) ≠ somme lignes ({computed_ht:.2f})",
        ))

    if abs(computed_tva - header_tva) > TOLERANCE:
        report.issues.append(TVAIssue(
            issue_type="header_mismatch", severity="error", line_number=0,
            detail=f"Total TVA facture ({header_tva:.2f}) ≠ somme lignes ({computed_tva:.2f})",
        ))

    if abs(computed_ttc - header_ttc) > TOLERANCE:
        report.issues.append(TVAIssue(
            issue_type="header_mismatch", severity="error", line_number=0,
            detail=f"Total TTC facture ({header_ttc:.2f}) ≠ somme lignes ({computed_ttc:.2f})",
        ))

    # Header coherence: TTC = HT + TVA
    expected_ttc = _q(header_ht + header_tva)
    if abs(expected_ttc - header_ttc) > TOLERANCE:
        report.issues.append(TVAIssue(
            issue_type="header_mismatch", severity="error", line_number=0,
            detail=f"Facture TTC ({header_ttc:.2f}) ≠ HT ({header_ht:.2f}) + TVA ({header_tva:.2f}) = {expected_ttc:.2f}",
        ))

    # Score
    error_count = report.error_count
    if error_count == 0 and report.warning_count == 0:
        report.score = 100
    else:
        report.score = max(0, 100 - (error_count * 15) - (report.warning_count * 5))

    return report
