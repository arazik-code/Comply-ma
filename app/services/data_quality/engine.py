"""
Data Quality Engine — orchestrates all checks and produces a client-level report.

This is the SELLABLE ARTIFACT: "Rapport de conformité des données"
that a fiduciaire shows their client.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from app.services.data_quality.ice_validator import validate_ice, validate_ice_batch
from app.services.data_quality.numbering import detect_numbering_gaps, NumberingReport
from app.services.data_quality.tva_validator import validate_invoice_tva, TVAReport


@dataclass
class DataIssue:
    category: str        # ice | numbering | tva | structure | duplicate | legal
    severity: str        # error | warning | info
    entity_type: str     # company | client | invoice | line
    entity_id: str
    entity_name: str
    field: str
    detail: str
    fixable: bool = False
    fixed_value: str = ""


@dataclass
class ClientDataQualityReport:
    client_id: str
    client_name: str
    company_name: str
    generated_at: str
    fiscal_year: int

    # Summary
    total_invoices: int = 0
    total_clients: int = 0
    total_products: int = 0

    # ICE validation
    ice_issues: list[DataIssue] = field(default_factory=list)
    ice_valid_count: int = 0
    ice_invalid_count: int = 0

    # Numbering
    numbering_report: Optional[NumberingReport] = None

    # TVA
    tva_issues: list[DataIssue] = field(default_factory=list)

    # Structure
    structure_issues: list[DataIssue] = field(default_factory=list)

    # Duplicates
    duplicate_issues: list[DataIssue] = field(default_factory=list)

    # Overall
    all_issues: list[DataIssue] = field(default_factory=list)
    score: int = 100
    grade: str = "A"

    # Counts
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0

    # Fix summary
    auto_fixable: int = 0
    manual_review: int = 0


class DataQualityEngine:
    """Orchestrates all data quality checks for a client company."""

    def run_full_audit(
        self,
        company_id: str,
        company_name: str,
        company_ice: str,
        company_rc: str,
        company_if: str,
        clients: list[dict],
        invoices: list[dict],
        fiscal_year: int = 2025,
    ) -> ClientDataQualityReport:
        """Run complete data quality audit."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        report = ClientDataQualityReport(
            client_id=company_id, client_name=company_name,
            company_name=company_name, generated_at=now, fiscal_year=fiscal_year,
        )

        # ── Company ICE ────────────────────────────────────────────
        self._check_company_ice(report, company_ice, company_rc, company_if, company_name)

        # ── Client ICEs ────────────────────────────────────────────
        self._check_client_ices(report, clients)

        # ── Numbering ──────────────────────────────────────────────
        self._check_numbering(report, invoices, fiscal_year)

        # ── TVA Math ───────────────────────────────────────────────
        self._check_tva_math(report, invoices)

        # ── Structure ──────────────────────────────────────────────
        self._check_structure(report, invoices, clients)

        # ── Duplicates ─────────────────────────────────────────────
        self._check_duplicates(report, invoices)

        # ── Compute totals ─────────────────────────────────────────
        report.all_issues = (
            report.ice_issues + report.tva_issues +
            report.structure_issues + report.duplicate_issues
        )
        if report.numbering_report:
            from app.services.data_quality.numbering import NumberingIssue
            for ni in report.numbering_report.issues:
                report.all_issues.append(DataIssue(
                    category="numbering", severity=ni.severity,
                    entity_type="invoice", entity_id="", entity_name="",
                    field="invoice_number", detail=ni.detail,
                ))

        report.error_count = sum(1 for i in report.all_issues if i.severity == "error")
        report.warning_count = sum(1 for i in report.all_issues if i.severity == "warning")
        report.info_count = sum(1 for i in report.all_issues if i.severity == "info")
        report.auto_fixable = sum(1 for i in report.all_issues if i.fixable)
        report.manual_review = len(report.all_issues) - report.auto_fixable

        # Score
        if report.error_count == 0 and report.warning_count == 0:
            report.score = 100
        else:
            report.score = max(0, 100 - (report.error_count * 8) - (report.warning_count * 3))
        report.score = min(report.score, 100)

        if report.score >= 90:
            report.grade = "A"
        elif report.score >= 75:
            report.grade = "B"
        elif report.score >= 50:
            report.grade = "C"
        else:
            report.grade = "D"

        return report

    def _check_company_ice(self, report, ice, rc, if_number, name):
        result = validate_ice(ice)
        if not result.valid:
            report.ice_issues.append(DataIssue(
                category="ice", severity="error", entity_type="company",
                entity_id=report.client_id, entity_name=name,
                field="ice", detail=f"ICE société: {result.error}",
            ))
            report.ice_invalid_count += 1
        else:
            report.ice_valid_count += 1

        if not rc or not rc.strip():
            report.structure_issues.append(DataIssue(
                category="structure", severity="error", entity_type="company",
                entity_id=report.client_id, entity_name=name,
                field="rc", detail="RC (Registre du Commerce) manquant",
            ))

        if not if_number or not if_number.strip():
            report.structure_issues.append(DataIssue(
                category="structure", severity="error", entity_type="company",
                entity_id=report.client_id, entity_name=name,
                field="if_number", detail="IF (Identifiant Fiscal) manquant",
            ))

    def _check_client_ices(self, report, clients):
        report.total_clients = len(clients)
        for c in clients:
            ice = c.get("ice", "")
            name = c.get("name", "Inconnu")
            cid = c.get("id", "")

            if not ice or not ice.strip():
                report.ice_issues.append(DataIssue(
                    category="ice", severity="error", entity_type="client",
                    entity_id=cid, entity_name=name,
                    field="ice", detail=f"ICE manquant pour client '{name}'",
                ))
                report.ice_invalid_count += 1
            else:
                result = validate_ice(ice)
                if not result.valid:
                    report.ice_issues.append(DataIssue(
                        category="ice", severity="error", entity_type="client",
                        entity_id=cid, entity_name=name,
                        field="ice", detail=f"ICE invalide pour '{name}': {result.error}",
                    ))
                    report.ice_invalid_count += 1
                else:
                    report.ice_valid_count += 1

            # Check missing fields
            if not c.get("rc"):
                report.structure_issues.append(DataIssue(
                    category="structure", severity="warning", entity_type="client",
                    entity_id=cid, entity_name=name,
                    field="rc", detail=f"RC manquant pour client '{name}'",
                ))
            if not c.get("if_number"):
                report.structure_issues.append(DataIssue(
                    category="structure", severity="warning", entity_type="client",
                    entity_id=cid, entity_name=name,
                    field="if_number", detail=f"IF manquant pour client '{name}'",
                ))

    def _check_numbering(self, report, invoices, fiscal_year):
        invoice_numbers = [i.get("invoice_number", "") for i in invoices if i.get("invoice_number")]
        report.total_invoices = len(invoices)

        if invoice_numbers:
            report.numbering_report = detect_numbering_gaps(
                invoice_numbers, fiscal_year, "invoice"
            )

    def _check_tva_math(self, report, invoices):
        for inv in invoices:
            lines = inv.get("lines", [])
            if not lines:
                continue

            line_dicts = []
            for idx, l in enumerate(lines, 1):
                line_dicts.append({
                    "line_number": idx,
                    "quantity": l.get("quantity", 0),
                    "unit_price": l.get("unit_price", 0),
                    "tva_rate": l.get("tva_rate", 0),
                    "line_total_ht": l.get("line_total_ht", 0),
                    "line_total_tva": l.get("line_total_tva", 0),
                    "line_total_ttc": l.get("line_total_ttc", 0),
                })

            tva_report = validate_invoice_tva(
                line_dicts,
                header_ht=Decimal(str(inv.get("total_ht", 0))),
                header_tva=Decimal(str(inv.get("total_tva", 0))),
                header_ttc=Decimal(str(inv.get("total_ttc", 0))),
            )

            for issue in tva_report.issues:
                report.tva_issues.append(DataIssue(
                    category="tva", severity=issue.severity,
                    entity_type="invoice",
                    entity_id=inv.get("id", ""),
                    entity_name=inv.get("invoice_number", inv.get("id", "")),
                    field=f"line_{issue.line_number}" if issue.line_number else "header",
                    detail=issue.detail,
                ))

    def _check_structure(self, report, invoices, clients):
        for inv in invoices:
            inv_num = inv.get("invoice_number", "")
            inv_id = inv.get("id", "")

            if not inv.get("invoice_date"):
                report.structure_issues.append(DataIssue(
                    category="structure", severity="error", entity_type="invoice",
                    entity_id=inv_id, entity_name=inv_num,
                    field="invoice_date", detail=f"Date manquante pour facture '{inv_num}'",
                ))

            if not inv.get("client_id"):
                report.structure_issues.append(DataIssue(
                    category="structure", severity="error", entity_type="invoice",
                    entity_id=inv_id, entity_name=inv_num,
                    field="client_id", detail=f"Client manquant pour facture '{inv_num}'",
                ))

            lines = inv.get("lines", [])
            if not lines:
                report.structure_issues.append(DataIssue(
                    category="structure", severity="warning", entity_type="invoice",
                    entity_id=inv_id, entity_name=inv_num,
                    field="lines", detail=f"Aucune ligne pour facture '{inv_num}'",
                ))
            else:
                for idx, line in enumerate(lines, 1):
                    if not line.get("description", "").strip():
                        report.structure_issues.append(DataIssue(
                            category="structure", severity="warning", entity_type="line",
                            entity_id=inv_id, entity_name=f"{inv_num} ligne {idx}",
                            field="description", detail=f"Description vide ligne {idx}",
                        ))

    def _check_duplicates(self, report, invoices):
        seen = {}
        for inv in invoices:
            num = inv.get("invoice_number", "")
            if not num:
                continue
            if num in seen:
                report.duplicate_issues.append(DataIssue(
                    category="duplicate", severity="error", entity_type="invoice",
                    entity_id=inv.get("id", ""), entity_name=num,
                    field="invoice_number",
                    detail=f"Numéro dupliqué: '{num}' (factures {seen[num]} et {inv.get('id', '')})",
                ))
            else:
                seen[num] = inv.get("id", "")


_engine: Optional[DataQualityEngine] = None


def get_data_quality_engine() -> DataQualityEngine:
    global _engine
    if _engine is None:
        _engine = DataQualityEngine()
    return _engine
