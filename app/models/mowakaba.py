"""
MOWAKABA Subsidy Info Module — explains the e-invoicing subsidy program.

CRITICAL DISCLAIMER:
  - MOWAKABA subsidy eligibility for solo/auto-entrepreneur vendors is UNVERIFIED
  - Must be confirmed with Maroc PME before being presented to a client as a guarantee
  - Do not hardcode subsidy % or eligibility as fact — make them configurable
  - This module provides INFORMATION ONLY, not guaranteed eligibility
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MowakabaSubsidy:
    """Subsidy information — configurable, NOT hardcoded facts."""
    tier: str                    # TPE | PME
    subsidy_pct: float           # Configurable: 80-90% for TPE, up to 80% for PME
    max_amount: float            # Maximum subsidy amount in MAD
    eligibility: list[str]       # Eligibility criteria (informational)
    conditions: list[str]        # Conditions to maintain subsidy
    deadline: Optional[str]      # Application deadline (if known)
    source: str                  # Source of information
    verified: bool = False       # CRITICAL: has this been verified with Maroc PME?


# CRITICAL DISCLAIMER: These figures are CONFIGURABLE and UNVERIFIED
# They MUST be confirmed with Maroc PME before presenting to clients
DEFAULT_SUBSIDIES = [
    MowakabaSubsidy(
        tier="TPE",
        subsidy_pct=85.0,  # 80-90% range — CONFIGURABLE
        max_amount=10000.0,
        eligibility=[
            "Entreprise inscrite au RC",
            "Adresse fiscale au Maroc",
            "Pas de dette fiscale connue",
            "CA annuel < 500K MAD (à confirmer avec Maroc PME)",
        ],
        conditions=[
            "Maintenir l'abonnement pendant 12 mois minimum",
            "Utiliser le logiciel conformément aux normes DGI",
            "Fournir les déclarations fiscales à temps",
        ],
        deadline="À confirmer avec Maroc PME",
        source="Maroc PME — site web officiel (informations non vérifiées)",
        verified=False,
    ),
    MowakabaSubsidy(
        tier="PME",
        subsidy_pct=80.0,  # Up to 80% — CONFIGURABLE
        max_amount=15000.0,
        eligibility=[
            "Entreprise inscrite au RC",
            "Adresse fiscale au Maroc",
            "Pas de dette fiscale connue",
            "CA annuel entre 500K et 100M MAD (à confirmer)",
        ],
        conditions=[
            "Maintenir l'abonnement pendant 12 mois minimum",
            "Utiliser le logiciel conformément aux normes DGI",
            "Fournir les déclarations fiscales à temps",
        ],
        deadline="À confirmer avec Maroc PME",
        source="Maroc PME — site web officiel (informations non vérifiées)",
        verified=False,
    ),
]


def get_subsidy_info(tier: str = "TPE") -> Optional[MowakabaSubsidy]:
    """Get subsidy information for a given tier. Returns None if not found."""
    for s in DEFAULT_SUBSIDIES:
        if s.tier.upper() == tier.upper():
            return s
    return None


def get_all_subsidies() -> list[MowakabaSubsidy]:
    """Get all available subsidy information."""
    return list(DEFAULT_SUBSIDIES)


def generate_dossier_draft(
    company_name: str,
    company_ice: str,
    tier: str = "TPE",
    cab_name: str = "",
) -> str:
    """
    Generate a pre-filled dossier draft for the fiduciaire to review.
    Returns plain text — NOT a legal document.
    """
    subsidy = get_subsidy_info(tier)
    if not subsidy:
        return "Information sur les subventions non disponible pour ce type d'entreprise."

    draft = f"""
DOSSIER DE DEMANDE DE SUBVENTION MOWAKABA
==========================================

IMPORTANT: Ce brouillon est généré automatiquement et doit être vérifié
par un expert-comptable avant soumission.

Entreprise demandeur:
  Nom: {company_name}
  ICE: {company_ice}
  Type: {tier}

Subvention demandée:
  Taux: {subsidy.subsidy_pct}% (configurable — à confirmer avec Maroc PME)
  Montant maximum: {subsidy.max_amount:,.0f} MAD

Critères d'éligibilité (à vérifier):
"""
    for i, c in enumerate(subsidy.eligibility, 1):
        draft += f"  {i}. {c}\n"

    draft += f"""
Conditions:
"""
    for i, c in enumerate(subsidy.conditions, 1):
        draft += f"  {i}. {c}\n"

    draft += f"""
Source: {subsidy.source}
Vérifié: {"Oui" if subsidy.verified else "NON — À confirmer avec Maroc PME"}

---
Brouillon généré par COMPLY-MA le {__import__('datetime').datetime.now().strftime('%d/%m/%Y')}
Cabinet: {cab_name or "Non spécifié"}

AVERTISSEMENT: Ce document est un brouillon. L'éligibilité à la subvention
MOWAKABA doit être confirmée avec Maroc PME avant toute présentation au client.
Les pourcentages et montants indiqués sont configurables et non garantis.
"""
    return draft.strip()
