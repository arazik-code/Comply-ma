"""Automated report generation and scheduling."""
import csv
import io
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger("app.services.reports")


@dataclass
class Report:
    id: str
    title: str
    report_type: str
    format: str
    created_at: str
    file_path: str = ""
    file_size: int = 0
    data: dict = None

    def __post_init__(self):
        if self.data is None:
            self.data = {}


class ReportGenerator:
    """Generates business reports in various formats."""

    def __init__(self):
        self.output_dir = Path(settings.data_dir) / "reports"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_tva_report(self, invoices: list, period: str, company_name: str = "") -> Report:
        by_rate = {}
        for inv in invoices:
            if inv.status in ("validated", "sent", "archived"):
                for line in (hasattr(inv, 'lines') and inv.lines or []):
                    rate = str(getattr(line, 'tva_rate', 20))
                    if rate not in by_rate:
                        by_rate[rate] = {"ht": 0, "tva": 0, "ttc": 0, "count": 0}
                    by_rate[rate]["ht"] += float(getattr(line, 'line_total_ht', 0))
                    by_rate[rate]["tva"] += float(getattr(line, 'line_total_tva', 0))
                    by_rate[rate]["ttc"] += float(getattr(line, 'line_total_ttc', getattr(line, 'line_total_ht', 0) + getattr(line, 'line_total_tva', 0)))
                    by_rate[rate]["count"] += 1

        report_data = {"period": period, "company": company_name, "rates": by_rate}
        report_id = f"tva-{period}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        file_path = self.output_dir / f"{report_id}.json"
        file_path.write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8")

        return Report(id=report_id, title=f"Rapport TVA {period}", report_type="tva", format="json", created_at=datetime.now(timezone.utc).isoformat(), file_path=str(file_path), file_size=file_path.stat().st_size, data=report_data)

    def generate_aging_report(self, invoices: list, company_name: str = "") -> Report:
        now = datetime.now(timezone.utc)
        buckets = {"0-30j": [], "31-60j": [], "61-90j": [], "90j+": []}
        for inv in invoices:
            if inv.payment_status in ("pending", "overdue") and inv.status != "cancelled":
                days = (now - inv.invoice_date).days
                if days <= 30:
                    buckets["0-30j"].append(inv)
                elif days <= 60:
                    buckets["31-60j"].append(inv)
                elif days <= 90:
                    buckets["61-90j"].append(inv)
                else:
                    buckets["90j+"].append(inv)

        report_data = {"company": company_name, "generated_at": now.isoformat(), "buckets": {}}
        for k, invs in buckets.items():
            report_data["buckets"][k] = {"count": len(invs), "total": round(sum(float(i.total_ttc) for i in invs), 2), "invoices": [{"number": i.invoice_number, "client": getattr(i, 'client_name', 'N/A'), "amount": float(i.total_ttc), "days": (now - i.invoice_date).days} for i in invs]}

        report_id = f"aging-{now.strftime('%Y%m%d%H%M%S')}"
        file_path = self.output_dir / f"{report_id}.json"
        file_path.write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8")

        return Report(id=report_id, title="Rapport d'Aging", report_type="aging", format="json", created_at=now.isoformat(), file_path=str(file_path), file_size=file_path.stat().st_size, data=report_data)

    def export_invoices_csv(self, invoices: list, filename: str = "invoices_export.csv") -> Report:
        report_id = f"export-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        file_path = self.output_dir / f"{report_id}.csv"

        with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["Numéro", "Date", "Client", "HT", "TVA", "TTC", "Statut", "Paiement"])
            for inv in invoices:
                writer.writerow([inv.invoice_number, inv.invoice_date.strftime("%Y-%m-%d") if inv.invoice_date else "", getattr(inv, 'client_name', ''), float(inv.total_ht), float(inv.total_tva), float(inv.total_ttc), inv.status, inv.payment_status])

        return Report(id=report_id, title="Export Factures", report_type="export", format="csv", created_at=datetime.now(timezone.utc).isoformat(), file_path=str(file_path), file_size=file_path.stat().st_size)

    def generate_compliance_summary(self, invoices: list, company=None, tva_rates_dict: dict = None, company_name: str = "") -> Report:
        from app.models.client import Client
        scores = []
        issues_by_type = {}
        for inv in invoices:
            if inv.status != "draft" and hasattr(inv, 'client_id') and inv.client_id:
                try:
                    report = check_invoice(inv, [], None, company, tva_rates_dict or {})
                    scores.append(report.score)
                    for issue in (report.issues if hasattr(report, 'issues') else []):
                        check_name = getattr(issue, 'check', 'unknown')
                        issues_by_type[check_name] = issues_by_type.get(check_name, 0) + 1
                except Exception:
                    pass

        avg_score = round(sum(scores) / len(scores), 1) if scores else 100
        report_data = {"company": company_name, "avg_score": avg_score, "total_checked": len(scores), "issues_by_type": issues_by_type, "grade_distribution": {"A": sum(1 for s in scores if s >= 90), "B": sum(1 for s in scores if 70 <= s < 90), "C": sum(1 for s in scores if 50 <= s < 70), "D": sum(1 for s in scores if s < 50)}}

        report_id = f"compliance-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        file_path = self.output_dir / f"{report_id}.json"
        file_path.write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8")

        return Report(id=report_id, title="Rapport de Conformité", report_type="compliance", format="json", created_at=datetime.now(timezone.utc).isoformat(), file_path=str(file_path), file_size=file_path.stat().st_size, data=report_data)


_report_generator: Optional[ReportGenerator] = None


def get_report_generator() -> ReportGenerator:
    global _report_generator
    if _report_generator is None:
        _report_generator = ReportGenerator()
    return _report_generator
