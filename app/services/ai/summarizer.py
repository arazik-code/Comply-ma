"""Document summarization service using AI."""
import logging
from dataclasses import dataclass
from typing import Optional

from app.services.ai.providers import get_ai_service, AIResponse

logger = logging.getLogger("app.services.ai.summarizer")


@dataclass
class SummaryResult:
    summary: str
    key_points: list[str]
    total_amount: float
    due_date: str
    compliance_status: str
    provider: str = ""
    success: bool = True
    error: str = ""


class DocumentSummarizer:
    """Summarizes invoices, credit notes, and other business documents using AI."""

    def __init__(self):
        self.ai = get_ai_service()

    def summarize_invoice(self, invoice_data: dict, lines: list[dict] = None) -> SummaryResult:
        context = self._build_invoice_context(invoice_data, lines)
        prompt = f"""Résume cette facture marocaine de manière concise.

{context}

Retourne un JSON:
{{
    "summary": "résumé en 2-3 phrases",
    "key_points": ["point 1", "point 2", "point 3"],
    "total_amount": montant_total,
    "due_date": "date d'échéance",
    "compliance_status": "conforme|non conforme|à vérifier"
}}"""

        response = self.ai.chat(prompt, system="Tu es un expert en facturation marocaine. Résumes les factures de manière précise et concise.", temperature=0.2, max_tokens=500)
        return self._parse_summary_response(response, invoice_data.get("total_ttc", 0), invoice_data.get("due_date", ""))

    def summarize_credit_note(self, cn_data: dict) -> SummaryResult:
        context = f"""
Type: Avoir (Credit Note)
Numéro: {cn_data.get('credit_note_number', 'N/A')}
Date: {cn_data.get('invoice_date', 'N/A')}
Raison: {cn_data.get('reason', 'N/A')}
Montant HT: {cn_data.get('total_ht', 0)} MAD
TVA: {cn_data.get('total_tva', 0)} MAD
TTC: {cn_data.get('total_ttc', 0)} MAD
Facture originale: {cn_data.get('original_invoice_number', 'N/A')}
"""
        prompt = f"""Résume cet avoir marocain.

{context}

Retourne un JSON:
{{
    "summary": "résumé en 2-3 phrases",
    "key_points": ["point 1", "point 2"],
    "total_amount": montant_total,
    "compliance_status": "conforme|non conforme"
}}"""

        response = self.ai.chat(prompt, system="Tu es un expert en facturation marocaine.", temperature=0.2)
        return self._parse_summary_response(response, cn_data.get("total_ttc", 0), "")

    def summarize_purchase_order(self, po_data: dict, lines: list[dict] = None) -> SummaryResult:
        lines_text = ""
        if lines:
            for l in lines:
                lines_text += f"  - {l.get('description', 'N/A')}: {l.get('quantity', 0)} × {l.get('unit_price', 0)} = {l.get('total', 0)} MAD\n"

        prompt = f"""Résume ce bon de commande.

Numéro: {po_data.get('po_number', 'N/A')}
Fournisseur: {po_data.get('supplier_name', 'N/A')}
Date: {po_data.get('order_date', 'N/A')}
Statut: {po_data.get('status', 'draft')}
Montant total: {po_data.get('total_amount', 0)} MAD

Lignes:
{lines_text}

Retourne un JSON:
{{
    "summary": "résumé en 2-3 phrases",
    "key_points": ["point 1", "point 2"],
    "total_amount": montant_total,
    "compliance_status": "complet|partiel|en attente"
}}"""

        response = self.ai.chat(prompt, system="Tu es un expert en gestion des achats.", temperature=0.2)
        return self._parse_summary_response(response, po_data.get("total_amount", 0), "")

    def generate_payment_reminder(self, invoice_data: dict, language: str = "french") -> str:
        lang_instruction = "en darija (arabe marocain)" if language == "darija" else "en français"
        prompt = f"""Génère un rappel de paiement {lang_instruction} pour cette facture.

Numéro: {invoice_data.get('invoice_number', 'N/A')}
Client: {invoice_data.get('client_name', 'N/A')}
Montant TTC: {invoice_data.get('total_ttc', 0)} MAD
Date d'échéance: {invoice_data.get('due_date', 'N/A')}
Jours de retard: {invoice_data.get('overdue_days', 0)}

Le rappel doit être professionnel mais amical. Inclure le montant dû et la date d'échéance."""

        response = self.ai.chat(prompt, temperature=0.5, max_tokens=300)
        return response.content if response.success else f"Rappel de paiement: Facture {invoice_data.get('invoice_number', '')} d'un montant de {invoice_data.get('total_ttc', 0)} MAD est en retard de paiement."

    def explain_compliance_issues(self, issues: list[dict], language: str = "french") -> str:
        issues_text = "\n".join([f"- [{i.get('severity', 'info')}] {i.get('check', 'N/A')}: {i.get('message', 'N/A')}" for i in issues])
        lang_instruction = "en darija" if language == "darija" else "en français"
        prompt = f"""Explique {lang_instruction} ces problèmes de conformité de facture de manière claire et actionable.

Problèmes:
{issues_text}

Pour chaque problème, explique:
1. Ce que c'est
2. Pourquoi c'est important
3. Comment le corriger"""

        response = self.ai.chat(prompt, system="Tu es un expert en conformité DGI.", temperature=0.3, max_tokens=1000)
        return response.content if response.success else "Veuillez corriger les problèmes de conformité listés."

    def _build_invoice_context(self, data: dict, lines: list[dict] = None) -> str:
        lines_text = ""
        if lines:
            for l in lines:
                lines_text += f"  - {l.get('description', 'N/A')}: {l.get('quantity', 0)} × {l.get('unit_price', 0)} = {l.get('total', 0)} MAD (TVA {l.get('tva_rate', 20)}%)\n"

        return f"""
Type: Facture
Numéro: {data.get('invoice_number', 'N/A')}
Fournisseur: {data.get('supplier_name', 'N/A')} (ICE: {data.get('supplier_ice', 'N/A')})
Client: {data.get('client_name', 'N/A')} (ICE: {data.get('client_ice', 'N/A')})
Date: {data.get('invoice_date', 'N/A')}
Échéance: {data.get('due_date', 'N/A')}
Statut: {data.get('status', 'N/A')}

Montants:
  HT: {data.get('total_ht', 0)} MAD
  TVA ({data.get('tva_rate', 20)}%): {data.get('total_tva', 0)} MAD
  TTC: {data.get('total_ttc', 0)} MAD

Lignes:
{lines_text}

Conformité DGI: {data.get('compliance_status', 'non vérifié')}
"""

    def _parse_summary_response(self, response: AIResponse, default_amount: float, default_due: str) -> SummaryResult:
        if not response.success:
            return SummaryResult(summary="", key_points=[], total_amount=default_amount, due_date=default_due, compliance_status="unknown", success=False, error=response.error)

        try:
            text = response.content.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            import json
            data = json.loads(text.strip())
            return SummaryResult(
                summary=data.get("summary", ""),
                key_points=data.get("key_points", []),
                total_amount=float(data.get("total_amount", default_amount)),
                due_date=data.get("due_date", default_due),
                compliance_status=data.get("compliance_status", "unknown"),
                provider=response.provider,
                success=True,
            )
        except Exception as e:
            return SummaryResult(
                summary=response.content[:500] if response.content else "",
                key_points=[], total_amount=default_amount, due_date=default_due,
                compliance_status="unknown", provider=response.provider, success=True
            )


_summarizer: Optional[DocumentSummarizer] = None


def get_summarizer() -> DocumentSummarizer:
    global _summarizer
    if _summarizer is None:
        _summarizer = DocumentSummarizer()
    return _summarizer
