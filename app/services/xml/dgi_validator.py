"""
Validateur DGI Maroc — vérifie les règles métier spécifiques à la DGI.
Valide le format ICE, le numéro de facture, les taux TVA, les dates, etc.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional


@dataclass
class DGIValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)


# Taux TVA autorisés par la DGI Maroc
AUTHORIZED_TVA_RATES = {
    Decimal("0.00"),
    Decimal("0.07"),
    Decimal("0.10"),
    Decimal("0.14"),
    Decimal("0.20"),
}

# Format numéro facture DGI : F + 9 chiffres + / + année (ex: F000000001/2025)
INVOICE_NUMBER_PATTERN = re.compile(r"^F\d{9}/\d{4}$")

# Format avoir : AV + 9 chiffres + / + année (ex: AV000000001/2025)
CREDIT_NOTE_NUMBER_PATTERN = re.compile(r"^AV\d{9}/\d{4}$")


def validate_ice(ice: str) -> tuple[bool, str]:
    """
    Valide le format ICE marocain (Identifiant Commun de l'Entreprise).
    Format : 15 chiffres
      - 3 chiffres (RC)
      - 4 chiffres (CIN ou équivalent)
      - 6 chiffres (séquence)
      - 2 chiffres (clé de contrôle modulo-97)

    Returns:
        (is_valid, error_message)
    """
    if not ice:
        return False, "ICE obligatoire"

    ice_clean = ice.strip().replace(" ", "")

    if not ice_clean.isdigit():
        return False, f"ICE doit contenir uniquement des chiffres (reçu: {ice_clean})"

    if len(ice_clean) != 15:
        return False, f"ICE doit contenir 15 chiffres (reçu: {len(ice_clean)} chiffres)"

    # Vérifier la clé de contrôle (modulo-97)
    try:
        body = int(ice_clean[:13])
        key = int(ice_clean[13:])
        expected_key = 97 - (body % 97)
        if key != expected_key:
            return False, f"ICE clé invalide (reçu: {key}, attendu: {expected_key})"
    except ValueError:
        return False, "ICE format invalide"

    return True, ""


def validate_invoice_number(number: str, fiscal_year: int) -> tuple[bool, str]:
    """
    Valide le format du numéro de facture DGI.
    Format : F + 9 chiffres + / + année (ex: F000000001/2025)
    """
    if not number:
        return False, "Numéro de facture obligatoire"

    if not INVOICE_NUMBER_PATTERN.match(number):
        return False, f"Format invalide (attendu: F000000001/{fiscal_year}, reçu: {number})"

    # Vérifier l'année dans le numéro
    parts = number.split("/")
    if len(parts) == 2:
        try:
            num_year = int(parts[1])
            if num_year != fiscal_year:
                return False, f"Année dans le numéro ({num_year}) ne correspond pas à l'exercice ({fiscal_year})"
        except ValueError:
            return False, "Année invalide dans le numéro"

    return True, ""


def validate_credit_note_number(number: str, fiscal_year: int) -> tuple[bool, str]:
    """Valide le format du numéro d'avoir DGI."""
    if not number:
        return False, "Numéro d'avoir obligatoire"

    if not CREDIT_NOTE_NUMBER_PATTERN.match(number):
        return False, f"Format invalide (attendu: AV000000001/{fiscal_year}, reçu: {number})"

    return True, ""


def validate_tva_rates(rates: list[Decimal]) -> tuple[bool, str]:
    """Vérifie que tous les taux TVA sont dans la liste autorisée par la DGI."""
    for rate in rates:
        if rate not in AUTHORIZED_TVA_RATES:
            return False, f"Taux TVA non autorisé: {rate*100:.1f}% (autorisés: 0%, 7%, 10%, 14%, 20%)"
    return True, ""


def validate_invoice_date(invoice_date: datetime, reference_date: Optional[datetime] = None) -> tuple[bool, str]:
    """
    Valide la date de facture selon les règles DGI :
    - Pas dans le futur (tolérance 1 jour pour fuseaux horaires)
    - Pas antérieure à 12 mois
    """
    ref = reference_date or datetime.now(timezone.utc)
    tolerance = timedelta(days=1)

    if invoice_date > ref + tolerance:
        return False, f"Date de facture dans le futur: {invoice_date.strftime('%Y-%m-%d')}"

    max_past = ref - timedelta(days=365)
    if invoice_date < max_past:
        return False, f"Date de facture trop ancienne (> 12 mois): {invoice_date.strftime('%Y-%m-%d')}"

    return True, ""


def validate_amounts(total_ht: Decimal, total_tva: Decimal, total_ttc: Decimal) -> tuple[bool, str]:
    """
    Vérifie la cohérence des montants :
    - TTC = HT + TVA (tolérance 0.01)
    - HT >= 0
    - TVA >= 0
    """
    if total_ht < 0:
        return False, f"Total HT négatif: {total_ht:.2f}"

    if total_tva < 0:
        return False, f"Total TVA négatif: {total_tva:.2f}"

    expected_ttc = total_ht + total_tva
    if abs(total_ttc - expected_ttc) > Decimal("0.01"):
        return False, f"TTC incohérent: {total_ttc:.2f} != HT({total_ht:.2f}) + TVA({total_tva:.2f}) = {expected_ttc:.2f}"

    return True, ""


def validate_company_config(company) -> tuple[bool, str]:
    """
    Vérifie que la société est correctement configurée pour la facturation DGI.
    Requiert: company_name, ICE, RC, IF, adresse, ville.
    """
    missing = []
    if not company.company_name or not company.company_name.strip():
        missing.append("raison sociale")
    if not company.ice or not company.ice.strip():
        missing.append("ICE")
    if not company.rc or not company.rc.strip():
        missing.append("RC")
    if not company.if_number or not company.if_number.strip():
        missing.append("IF")
    if not company.address or not company.address.strip():
        missing.append("adresse")
    if not company.city or not company.city.strip():
        missing.append("ville")

    if missing:
        return False, f"Configuration société incomplète: {', '.join(missing)}"
    return True, ""


def validate_full_invoice(invoice, lines, client, company, tva_rates_dict) -> DGIValidationResult:
    """
    Validation complète d'une facture contre toutes les règles DGI.
    Combine ICE, numéro, TVA, dates, montants, configuration.
    """
    result = DGIValidationResult(valid=True)

    # ICE client
    if client:
        ice_valid, ice_err = validate_ice(client.ice or "")
        if not ice_valid:
            result.valid = False
            result.errors.append(f"ICE client: {ice_err}")

    # ICE société
    if company:
        ice_valid, ice_err = validate_ice(company.ice or "")
        if not ice_valid:
            result.valid = False
            result.errors.append(f"ICE société: {ice_err}")

    # Numéro de facture (si déjà attribué)
    if invoice.invoice_number:
        num_valid, num_err = validate_invoice_number(invoice.invoice_number, invoice.fiscal_year)
        if not num_valid:
            result.valid = False
            result.errors.append(f"Numéro: {num_err}")

    # Date
    date_valid, date_err = validate_invoice_date(invoice.invoice_date)
    if not date_valid:
        result.valid = False
        result.errors.append(f"Date: {date_err}")

    # Taux TVA
    tva_rates = [line.tva_rate for line in lines]
    tva_valid, tva_err = validate_tva_rates(tva_rates)
    if not tva_valid:
        result.warnings.append(f"TVA: {tva_err}")

    # Montants
    amt_valid, amt_err = validate_amounts(invoice.total_ht, invoice.total_tva, invoice.total_ttc)
    if not amt_valid:
        result.valid = False
        result.errors.append(f"Montants: {amt_err}")

    # Configuration société
    if company:
        cfg_valid, cfg_err = validate_company_config(company)
        if not cfg_valid:
            result.valid = False
            result.errors.append(f"Société: {cfg_err}")

    return result
