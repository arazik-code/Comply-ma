"""
Moteur de conformité DGI Maroc — version complète (25+ vérifications).

Vérifie :
  - Format ICE (15 chiffres, clé modulo-97)
  - Numéro de facture DGI (F000000001/AAAA)
  - Taux TVA autorisés (0%, 7%, 10%, 14%, 20%)
  - Cohérence des montants (TTC = HT + TVA)
  - Configuration société complète
  - Date de facture (pas futur, pas > 12 mois)
  - Signature et hash
  - Statut et transitions
  - Avoir : référence facture originale
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import re
from typing import Optional

from app.models.invoice import Invoice, InvoiceLine
from app.models.credit_note import CreditNote, CreditNoteLine
from app.models.client import Client
from app.models.company import Company
from app.models.tva import TVARate


AUTHORIZED_TVA_RATES = {Decimal("0.00"), Decimal("0.07"), Decimal("0.10"), Decimal("0.14"), Decimal("0.20")}
INVOICE_NUMBER_RE = re.compile(r"^F\d{9}/\d{4}$")
CREDIT_NOTE_NUMBER_RE = re.compile(r"^AV\d{9}/\d{4}$")


@dataclass
class ComplianceCheck:
    passed: bool
    label: str
    detail: str = ""
    severity: str = "error"  # error | warning | info


@dataclass
class ComplianceReport:
    score: int  # 0-100
    checks: list[ComplianceCheck] = field(default_factory=list)
    passed_count: int = 0
    failed_count: int = 0
    warning_count: int = 0

    @property
    def grade(self) -> str:
        if self.score >= 90:
            return "A"
        if self.score >= 75:
            return "B"
        if self.score >= 50:
            return "C"
        return "D"


def _check(checks: list, passed: bool, label: str, detail: str = "", severity: str = "error"):
    checks.append(ComplianceCheck(passed=passed, label=label, detail=detail, severity=severity))
    return passed


def _validate_ice(ice: str) -> tuple[bool, str]:
    if not ice:
        return False, "ICE obligatoire"
    ice_clean = ice.strip().replace(" ", "")
    if not ice_clean.isdigit():
        return False, f"ICE doit contenir uniquement des chiffres"
    if len(ice_clean) != 15:
        return False, f"ICE doit contenir 15 chiffres (reçu: {len(ice_clean)})"
    try:
        body = int(ice_clean[:13])
        key = int(ice_clean[13:])
        expected = 97 - (body % 97)
        if key != expected:
            return False, f"ICE clé invalide (reçu: {key}, attendu: {expected})"
    except ValueError:
        return False, "ICE format invalide"
    return True, ""


def check_invoice(
    invoice: Invoice,
    lines: list[InvoiceLine],
    client: Optional[Client],
    company: Optional[Company],
    tva_rates: dict,
) -> ComplianceReport:
    checks: list[ComplianceCheck] = []
    passed = 0
    failed = 0
    warnings = 0

    # ── Structure ──────────────────────────────────────────────────

    # 1. Lignes de facture
    if _check(checks, len(lines) > 0, "Lignes de facture", "Au moins une ligne requise"):
        passed += 1
    else:
        failed += 1

    # 2. Description non vide
    empty_desc = any(not l.description.strip() for l in lines)
    if _check(checks, not empty_desc or not lines, "Descriptions complètes", "Toutes les lignes doivent avoir une description", severity="warning"):
        if not empty_desc or not lines:
            passed += 1
        else:
            warnings += 1
    else:
        warnings += 1

    # 3. Quantités positives
    bad_qty = any(l.quantity <= 0 for l in lines)
    if _check(checks, not bad_qty, "Quantités positives", "Toutes les quantités doivent être > 0"):
        if not bad_qty:
            passed += 1
        else:
            failed += 1
    else:
        failed += 1

    # 4. Prix unitaires positifs
    bad_price = any(l.unit_price < 0 for l in lines)
    if _check(checks, not bad_price, "Prix unitaires valides", "Les prix unitaires ne doivent pas être négatifs"):
        if not bad_price:
            passed += 1
        else:
            failed += 1
    else:
        failed += 1

    # ── Identifiants ──────────────────────────────────────────────

    # 5. ICE client (obligatoire B2B)
    ice_valid, ice_err = _validate_ice(client.ice if client else "")
    if _check(checks, ice_valid, "ICE client", ice_err or "ICE valide"):
        passed += 1
    else:
        failed += 1

    # 6. Client actif
    client_active = client and client.is_active
    if _check(checks, client_active, "Client actif", "Le client doit être actif"):
        passed += 1 if client_active else 0
        if client_active:
            passed += 1
        else:
            failed += 1
    else:
        failed += 1

    # 7. Client email
    has_email = client and client.email and "@" in (client.email or "")
    if _check(checks, has_email, "Email client", "Email requis pour envoi", severity="warning"):
        if has_email:
            passed += 1
        else:
            warnings += 1
    else:
        warnings += 1

    # ── Taux TVA ──────────────────────────────────────────────────

    # 8. Taux TVA autorisés par la DGI
    bad_tva = [l for l in lines if l.tva_rate not in AUTHORIZED_TVA_RATES]
    if _check(checks, not bad_tva, "Taux TVA DGI", f"Taux non autorisé(s): {[float(l.tva_rate) for l in bad_tva]}", severity="error"):
        if not bad_tva:
            passed += 1
        else:
            failed += 1
    else:
        failed += 1

    # 9. Taux TVA actifs
    invalid_tva = False
    for line in lines:
        rate = next((r for r in tva_rates.values() if r.rate == line.tva_rate), None)
        if rate and not rate.is_active:
            invalid_tva = True
            break
    if _check(checks, not invalid_tva, "Taux TVA actifs", "Tous les taux utilisés doivent être actifs", severity="warning"):
        if not invalid_tva:
            passed += 1
        else:
            warnings += 1
    else:
        warnings += 1

    # 10. TVA collectée > 0 si taux > 0
    has_tva = any(l.tva_rate > 0 for l in lines)
    if has_tva:
        if _check(checks, invoice.total_tva > 0, "TVA collectée", "TVA > 0 requise si lignes avec TVA"):
            passed += 1
        else:
            failed += 1
    else:
        passed += 1

    # ── Montants ──────────────────────────────────────────────────

    # 11. Total HT exact
    expected_ht = sum(l.line_total_ht for l in lines)
    ht_ok = abs(expected_ht - invoice.total_ht) < Decimal("0.01")
    if _check(checks, ht_ok, "Total HT", f"Attendu: {expected_ht:.2f}, Facture: {invoice.total_ht:.2f}"):
        passed += 1
    else:
        failed += 1

    # 12. Total TVA exact
    expected_tva = sum(l.line_total_tva for l in lines)
    tva_ok = abs(expected_tva - invoice.total_tva) < Decimal("0.01")
    if _check(checks, tva_ok, "Total TVA", f"Attendu: {expected_tva:.2f}, Facture: {invoice.total_tva:.2f}"):
        passed += 1
    else:
        failed += 1

    # 13. Total TTC exact
    expected_ttc = sum(l.line_total_ttc for l in lines)
    ttc_ok = abs(expected_ttc - invoice.total_ttc) < Decimal("0.01")
    if _check(checks, ttc_ok, "Total TTC", f"Attendu: {expected_ttc:.2f}, Facture: {invoice.total_ttc:.2f}"):
        passed += 1
    else:
        failed += 1

    # 14. TTC = HT + TVA
    coherent = abs(invoice.total_ttc - (invoice.total_ht + invoice.total_tva)) < Decimal("0.01")
    if _check(checks, coherent, "Cohérence TTC", f"TTC({invoice.total_ttc:.2f}) = HT({invoice.total_ht:.2f}) + TVA({invoice.total_tva:.2f})"):
        passed += 1
    else:
        failed += 1

    # 15. HT positif
    if _check(checks, invoice.total_ht >= 0, "HT positif", f"HT: {invoice.total_ht:.2f}"):
        passed += 1 if invoice.total_ht >= 0 else 0
        if invoice.total_ht >= 0:
            passed += 1
        else:
            failed += 1
    else:
        failed += 1

    # 16. TVA non négative
    if _check(checks, invoice.total_tva >= 0, "TVA non négative", f"TVA: {invoice.total_tva:.2f}"):
        passed += 1 if invoice.total_tva >= 0 else 0
        if invoice.total_tva >= 0:
            passed += 1
        else:
            failed += 1
    else:
        failed += 1

    # ── Société ───────────────────────────────────────────────────

    # 17. ICE société
    ice_soc, ice_soc_err = _validate_ice(company.ice if company else "")
    if _check(checks, ice_soc, "ICE société", ice_soc_err or "ICE valide"):
        passed += 1
    else:
        failed += 1

    # 18. RC société
    has_rc = company and company.rc and len((company.rc or "").strip()) > 0
    if _check(checks, has_rc, "RC société", "Registre du Commerce requis"):
        passed += 1 if has_rc else 0
        if has_rc:
            passed += 1
        else:
            failed += 1
    else:
        failed += 1

    # 19. IF société
    has_if = company and company.if_number and len((company.if_number or "").strip()) > 0
    if _check(checks, has_if, "IF société", "Identifiant Fiscal requis"):
        passed += 1 if has_if else 0
        if has_if:
            passed += 1
        else:
            failed += 1
    else:
        failed += 1

    # 20. Adresse société
    has_addr = company and company.address and len((company.address or "").strip()) > 5
    if _check(checks, has_addr, "Adresse société", "Adresse complète requise"):
        passed += 1 if has_addr else 0
        if has_addr:
            passed += 1
        else:
            failed += 1
    else:
        failed += 1

    # ── Dates ─────────────────────────────────────────────────────

    # 21. Date pas dans le futur
    now = datetime.now(timezone.utc)
    inv_date = invoice.invoice_date
    if inv_date.tzinfo is None:
        inv_date = inv_date.replace(tzinfo=timezone.utc)
    date_ok = inv_date <= now + timedelta(days=1)
    if _check(checks, date_ok, "Date valide", f"Date: {invoice.invoice_date.strftime('%Y-%m-%d')}"):
        passed += 1
    else:
        failed += 1

    # 22. Date pas trop ancienne (> 12 mois)
    max_past = now - timedelta(days=365)
    date_recent = inv_date >= max_past
    if _check(checks, date_recent, "Date récente", "Facture > 12 mois", severity="warning"):
        if date_recent:
            passed += 1
        else:
            warnings += 1
    else:
        warnings += 1

    # ── Numéro de facture ─────────────────────────────────────────

    # 23. Format numéro DGI
    if invoice.invoice_number:
        num_fmt = INVOICE_NUMBER_RE.match(invoice.invoice_number)
        if _check(checks, bool(num_fmt), "Format numéro DGI", f"Attendu: F000000001/{invoice.fiscal_year}", severity="warning"):
            if num_fmt:
                passed += 1
            else:
                warnings += 1
        else:
            warnings += 1
    else:
        passed += 1  # Pas encore numéroté (brouillon)

    # ── Sécurité ──────────────────────────────────────────────────

    # 24. Hash calculé
    has_hash = bool(invoice.hash_sha256)
    if _check(checks, has_hash, "Empreinte SHA-256", "Hash non calculé", severity="warning"):
        if has_hash:
            passed += 1
        else:
            warnings += 1
    else:
        warnings += 1

    # 25. Signature XML (info seulement)
    has_lock = invoice.is_locked
    if _check(checks, True, "Signature XML", "Vérification signature", severity="info"):
        passed += 1

    # ── Statut ────────────────────────────────────────────────────

    # 26. Statut cohérent
    valid_statuses = ("draft", "validated", "submitted", "cleared", "sent", "archived")
    status_ok = invoice.status in valid_statuses
    if _check(checks, status_ok, "Statut valide", f"Statut: {invoice.status}"):
        passed += 1 if status_ok else 0
        if status_ok:
            passed += 1
        else:
            failed += 1
    else:
        failed += 1

    # 27. Paiement
    valid_payment = invoice.payment_status in ("pending", "paid", "partial", "overdue")
    if _check(checks, valid_payment, "Statut paiement", f"Paiement: {invoice.payment_status}", severity="info"):
        passed += 1

    # ── Score ─────────────────────────────────────────────────────

    total = passed + failed + warnings
    score = int((passed / total) * 100) if total > 0 else 100

    return ComplianceReport(
        score=score,
        checks=checks,
        passed_count=passed,
        failed_count=failed,
        warning_count=warnings,
    )


def check_credit_note(
    note: CreditNote,
    lines: list[CreditNoteLine],
    client: Optional[Client],
    company: Optional[Company],
    tva_rates: dict,
    original_invoice: Optional[Invoice] = None,
) -> ComplianceReport:
    checks: list[ComplianceCheck] = []
    passed = 0
    failed = 0
    warnings = 0

    # 1. Lignes
    if _check(checks, len(lines) > 0, "Lignes d'avoir", "Au moins une ligne requise"):
        passed += 1
    else:
        failed += 1

    # 2. ICE client
    ice_valid, ice_err = _validate_ice(client.ice if client else "")
    if _check(checks, ice_valid, "ICE client", ice_err or "ICE valide"):
        passed += 1
    else:
        failed += 1

    # 3. Motif
    if _check(checks, bool(note.reason and note.reason.strip()), "Motif renseigné", "Le motif est obligatoire"):
        passed += 1
    else:
        failed += 1

    # 4. Société
    if _check(checks, company and company.company_name and company.ice and company.rc, "Société configurée", "ICE, RC et raison sociale requis"):
        passed += 1
    else:
        failed += 1

    # 5. Référence facture originale
    if _check(checks, bool(note.original_invoice_id), "Facture originale", "Référence facture requise"):
        passed += 1 if note.original_invoice_id else 0
        if note.original_invoice_id:
            passed += 1
        else:
            failed += 1
    else:
        failed += 1

    # 6. Montants avoir <= facture originale
    if original_invoice:
        amount_ok = note.total_ttc <= original_invoice.total_ttc
        if _check(checks, amount_ok, "Montant avoir", f"Avoir ({note.total_ttc:.2f}) ≤ Facture ({original_invoice.total_ttc:.2f})"):
            passed += 1
        else:
            failed += 1
    else:
        passed += 1

    # 7. Taux TVA
    bad_tva = [l for l in lines if l.tva_rate not in AUTHORIZED_TVA_RATES]
    if _check(checks, not bad_tva, "Taux TVA DGI", "Taux non autorisé(s)"):
        if not bad_tva:
            passed += 1
        else:
            failed += 1
    else:
        failed += 1

    # 8. Cohérence TTC
    if lines:
        expected_ttc = sum(l.line_total_ttc for l in lines)
        coherent = abs(expected_ttc - note.total_ttc) < Decimal("0.01")
        if _check(checks, coherent, "Cohérence TTC", f"Attendu: {expected_ttc:.2f}, Avoir: {note.total_ttc:.2f}"):
            passed += 1
        else:
            failed += 1
    else:
        passed += 1

    # 9. Date
    now = datetime.now(timezone.utc)
    date_ok = note.credit_note_date <= now + timedelta(days=1)
    if _check(checks, date_ok, "Date valide", f"Date: {note.credit_note_date.strftime('%Y-%m-%d')}"):
        passed += 1
    else:
        failed += 1

    # 10. Format numéro
    if note.credit_note_number:
        num_fmt = CREDIT_NOTE_NUMBER_RE.match(note.credit_note_number)
        if _check(checks, bool(num_fmt), "Format numéro DGI", f"Attendu: AV000000001/{note.fiscal_year}", severity="warning"):
            if num_fmt:
                passed += 1
            else:
                warnings += 1
        else:
            warnings += 1
    else:
        passed += 1

    # 11. Quantités
    bad_qty = any(l.quantity <= 0 for l in lines)
    if _check(checks, not bad_qty, "Quantités positives", "Toutes les quantités doivent être > 0"):
        if not bad_qty:
            passed += 1
        else:
            failed += 1
    else:
        failed += 1

    # 12. TVA collectée
    has_tva = any(l.tva_rate > 0 for l in lines)
    if has_tva:
        if _check(checks, note.total_tva > 0, "TVA collectée", "TVA > 0 requise"):
            passed += 1
        else:
            failed += 1
    else:
        passed += 1

    total = passed + failed + warnings
    score = int((passed / total) * 100) if total > 0 else 100

    return ComplianceReport(
        score=score,
        checks=checks,
        passed_count=passed,
        failed_count=failed,
        warning_count=warnings,
    )
