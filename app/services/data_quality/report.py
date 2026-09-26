"""
Rapport de Conformité des Données — PDF generator.

This is the SELLABLE ARTIFACT a fiduciaire shows their client.
Branded, professional, FR/AR bilingual.
"""
import io
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger("app.services.data_quality.report")


def generate_data_quality_report_pdf(report, company_name: str = "") -> bytes:
    """Generate a branded PDF report from a ClientDataQualityReport."""
    try:
        from weasyprint import HTML
    except ImportError:
        logger.warning("weasyprint_not_available_generating_html")
        return generate_data_quality_report_html(report, company_name).encode("utf-8")

    html = generate_data_quality_report_html(report, company_name)
    pdf_bytes = HTML(string=html).write_pdf()
    return pdf_bytes


def generate_data_quality_report_html(report, company_name: str = "") -> str:
    """Generate HTML report (usable for PDF conversion or display)."""
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")
    grade_colors = {"A": "#27ae60", "B": "#f39c12", "C": "#e67e22", "D": "#e74c3c"}
    grade_color = grade_colors.get(report.grade, "#999")

    issues_rows = ""
    for issue in report.all_issues[:50]:  # Limit to 50 for display
        sev_color = "#e74c3c" if issue.severity == "error" else "#f39c12" if issue.severity == "warning" else "#3498db"
        sev_label = "Erreur" if issue.severity == "error" else "Avertissement" if issue.severity == "warning" else "Info"
        issues_rows += f"""
        <tr>
          <td><span style="color:{sev_color};font-weight:600;">●</span> {sev_label}</td>
          <td>{issue.category.upper()}</td>
          <td>{issue.entity_type}</td>
          <td>{issue.entity_name}</td>
          <td>{issue.detail}</td>
        </tr>"""

    numbering_section = ""
    if report.numbering_report:
        nr = report.numbering_report
        numbering_section = f"""
        <div class="section">
          <h2>Numérotation des factures</h2>
          <div class="stats">
            <div class="stat"><span class="stat-value">{nr.total_count}</span><span class="stat-label">Factures</span></div>
            <div class="stat"><span class="stat-value">{nr.error_count}</span><span class="stat-label">Erreurs</span></div>
            <div class="stat"><span class="stat-value">{len(nr.gaps)}</span><span class="stat-label">Lacunes</span></div>
            <div class="stat"><span class="stat-value">{len(nr.duplicates)}</span><span class="stat-label">Doublons</span></div>
          </div>
          {"<p style='color:#27ae60;'>✓ Séquence complète sans lacunes</p>" if not nr.gaps else f"<p style='color:#e74c3c;'>✗ {len(nr.gaps)} numéros manquants dans la séquence</p>"}
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<style>
  @page {{ size: A4; margin: 20mm; }}
  body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #333; line-height: 1.5; }}
  .header {{ text-align: center; border-bottom: 3px solid #1a3a5c; padding-bottom: 15px; margin-bottom: 20px; }}
  .header h1 {{ color: #1a3a5c; font-size: 22px; margin: 0; }}
  .header .subtitle {{ color: #666; font-size: 12px; margin-top: 5px; }}
  .section {{ margin-bottom: 20px; }}
  .section h2 {{ color: #1a3a5c; font-size: 16px; border-bottom: 1px solid #ddd; padding-bottom: 5px; }}
  .stats {{ display: flex; gap: 20px; margin: 15px 0; }}
  .stat {{ text-align: center; flex: 1; padding: 15px; background: #f8f9fa; border-radius: 8px; }}
  .stat-value {{ display: block; font-size: 28px; font-weight: 700; color: #1a3a5c; }}
  .stat-label {{ font-size: 11px; color: #666; text-transform: uppercase; }}
  .grade {{ text-align: center; margin: 20px 0; }}
  .grade-badge {{ display: inline-block; width: 80px; height: 80px; line-height: 80px; border-radius: 50%; color: white; font-size: 36px; font-weight: 700; background: {grade_color}; }}
  .score-bar {{ width: 100%; height: 20px; background: #eee; border-radius: 10px; overflow: hidden; margin: 10px 0; }}
  .score-fill {{ height: 100%; background: {grade_color}; border-radius: 10px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
  th {{ background: #1a3a5c; color: white; padding: 8px; text-align: left; }}
  td {{ padding: 6px 8px; border-bottom: 1px solid #eee; }}
  tr:nth-child(even) {{ background: #f8f9fa; }}
  .footer {{ margin-top: 30px; padding-top: 15px; border-top: 2px solid #1a3a5c; text-align: center; font-size: 10px; color: #666; }}
  .disclaimer {{ background: #fff3cd; border: 1px solid #ffc107; border-radius: 6px; padding: 10px; margin-top: 15px; font-size: 10px; color: #856404; }}
</style>
</head>
<body>
  <div class="header">
    <h1>RAPPORT DE CONFORMITÉ DES DONNÉES</h1>
    <div class="subtitle">{company_name or report.company_name} — Exercice {report.fiscal_year} — Généré le {now}</div>
  </div>

  <div class="grade">
    <div class="grade-badge">{report.grade}</div>
    <div style="margin-top:10px;font-size:18px;font-weight:600;">Score: {report.score}/100</div>
    <div class="score-bar"><div class="score-fill" style="width:{report.score}%;"></div></div>
  </div>

  <div class="section">
    <h2>Résumé</h2>
    <div class="stats">
      <div class="stat"><span class="stat-value">{report.total_invoices}</span><span class="stat-label">Factures</span></div>
      <div class="stat"><span class="stat-value">{report.total_clients}</span><span class="stat-label">Clients</span></div>
      <div class="stat"><span class="stat-value">{report.error_count}</span><span class="stat-label">Erreurs</span></div>
      <div class="stat"><span class="stat-value">{report.warning_count}</span><span class="stat-label">Avertissements</span></div>
    </div>
  </div>

  <div class="section">
    <h2>Validation ICE</h2>
    <div class="stats">
      <div class="stat"><span class="stat-value" style="color:#27ae60;">{report.ice_valid_count}</span><span class="stat-label">ICES valides</span></div>
      <div class="stat"><span class="stat-value" style="color:#e74c3c;">{report.ice_invalid_count}</span><span class="stat-label">ICES invalides</span></div>
    </div>
  </div>

  {numbering_section}

  <div class="section">
    <h2>Problèmes détectés ({len(report.all_issues)})</h2>
    <table>
      <thead>
        <tr><th>Sévérité</th><th>Catégorie</th><th>Entité</th><th>Nom</th><th>Détail</th></tr>
      </thead>
      <tbody>
        {issues_rows if issues_rows else "<tr><td colspan='5' style='text-align:center;color:#27ae60;'>✓ Aucun problème détecté</td></tr>"}
      </tbody>
    </table>
  </div>

  <div class="disclaimer">
    <strong>⚠ Avertissement légal :</strong> Outil de structuration et d'archivage. Ne constitue pas un conseil comptable ou fiscal.
    Validation par un expert-comptable requise. Les données structurées sont prêtes pour la conformité DGI — données structurées,
    numérotées, archivées — et pluggeront dans le canal certifié DGI le jour de sa publication.
  </div>

  <div class="footer">
    <p>COMPLY-MA — Plateforme de structuration et d'archivage de données de facturation</p>
    <p>{company_name or report.company_name} — Exercice {report.fiscal_year}</p>
  </div>
</body>
</html>"""
    return html


def store_report(report, company_id: str, company_name: str = "") -> Path:
    """Store the report as HTML (and optionally PDF) on disk."""
    report_dir = Path(settings.data_dir) / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"rapport_conformite_{company_id}_{now}"

    html = generate_data_quality_report_html(report, company_name)
    html_path = report_dir / f"{filename}.html"
    html_path.write_text(html, encoding="utf-8")

    try:
        pdf_bytes = generate_data_quality_report_pdf(report, company_name)
        pdf_path = report_dir / f"{filename}.pdf"
        pdf_path.write_bytes(pdf_bytes)
        logger.info("report_stored", extra={"path": str(pdf_path), "format": "pdf"})
        return pdf_path
    except Exception as e:
        logger.warning("pdf_generation_failed_storing_html", extra={"error": str(e)})
        return html_path
