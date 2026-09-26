"""OCR engine for invoice scanning — extracts text from images/PDFs."""
import io
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.services.ai.providers import get_ai_service, AIResponse

logger = logging.getLogger("app.services.ai.ocr")


@dataclass
class InvoiceOCRResult:
    success: bool = False
    supplier_name: str = ""
    supplier_ice: str = ""
    supplier_address: str = ""
    invoice_number: str = ""
    invoice_date: str = ""
    due_date: str = ""
    total_ht: float = 0.0
    total_tva: float = 0.0
    total_ttc: float = 0.0
    tva_rate: float = 20.0
    currency: str = "MAD"
    lines: list[dict] = field(default_factory=list)
    raw_text: str = ""
    provider: str = ""
    confidence: float = 0.0
    error: str = ""


class InvoiceOCR:
    """OCR engine that uses AI to extract invoice data from images/PDFs."""

    def __init__(self):
        self.ai = get_ai_service()

    def extract_from_image(self, image_bytes: bytes, filename: str = "", mime_type: str = "image/png") -> InvoiceOCRResult:
        import base64
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:{mime_type};base64,{b64}"
        return self._extract_with_vision(data_url, filename)

    def extract_from_text(self, text: str) -> InvoiceOCRResult:
        prompt = self._build_extraction_prompt(text)
        response = self.ai.chat(prompt, system=self._get_system_prompt(), temperature=0.1, max_tokens=2000)
        return self._parse_response(response)

    def _extract_with_vision(self, data_url: str, filename: str) -> InvoiceOCRResult:
        prompt = f"""Analyse cette image de facture marocaine et extrais les informations suivantes en JSON.
Filename: {filename}

Retourne UNIQUEMENT un JSON valide avec ces champs:
{{
    "supplier_name": "nom du fournisseur",
    "supplier_ice": "numéro ICE (15 chiffres)",
    "supplier_address": "adresse complète",
    "invoice_number": "numéro de facture",
    "invoice_date": "YYYY-MM-DD",
    "due_date": "YYYY-MM-DD ou null",
    "total_ht": montant HT (nombre),
    "total_tva": montant TVA (nombre),
    "total_ttc": montant TTC (nombre),
    "tva_rate": taux TVA en pourcentage (nombre),
    "currency": "MAD",
    "lines": [
        {{"description": "description", "quantity": qté, "unit_price": prix unitaire, "total": total ligne}}
    ]
}}

Si un champ n'est pas trouvable, mets null. Pour les montants, utilise des nombres (pas de texte)."""

        response = self.ai.chat(prompt, system=self._get_vision_system_prompt(), temperature=0.1, max_tokens=2000)
        return self._parse_response(response)

    def _get_system_prompt(self) -> str:
        return """Tu es un expert en extraction de données de factures marocaines.
Tu dois analyser le texte fourni et extraire toutes les informations pertinentes.
Tu retournes toujours un JSON valide, sans texte additionnel."""

    def _get_vision_system_prompt(self) -> str:
        return """Tu es un expert OCR spécialisé dans les factures marocaines.
Tu analyses les images de factures et extrais les données avec précision.
Tu retournes toujours un JSON valide, sans texte additionnel."""

    def _build_extraction_prompt(self, text: str) -> str:
        return f"""Analyse ce texte de facture marocaine et extrais les informations en JSON.

Texte:
{text}

Retourne UNIQUEMENT un JSON valide avec ces champs:
{{
    "supplier_name": "nom du fournisseur",
    "supplier_ice": "numéro ICE (15 chiffres)",
    "supplier_address": "adresse complète",
    "invoice_number": "numéro de facture",
    "invoice_date": "YYYY-MM-DD",
    "due_date": "YYYY-MM-DD ou null",
    "total_ht": montant HT (nombre),
    "total_tva": montant TVA (nombre),
    "total_ttc": montant TTC (nombre),
    "tva_rate": taux TVA en pourcentage (nombre),
    "currency": "MAD",
    "lines": [
        {{"description": "description", "quantity": qté, "unit_price": prix unitaire, "total": total ligne}}
    ]
}}

Si un champ n'est pas trouvable, mets null."""

    def _parse_response(self, response: AIResponse) -> InvoiceOCRResult:
        if not response.success:
            return InvoiceOCRResult(success=False, error=response.error, provider=response.provider)

        try:
            text = response.content.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            import json
            data = json.loads(text)

            return InvoiceOCRResult(
                success=True,
                supplier_name=data.get("supplier_name") or "",
                supplier_ice=data.get("supplier_ice") or "",
                supplier_address=data.get("supplier_address") or "",
                invoice_number=data.get("invoice_number") or "",
                invoice_date=data.get("invoice_date") or "",
                due_date=data.get("due_date") or "",
                total_ht=float(data.get("total_ht") or 0),
                total_tva=float(data.get("total_tva") or 0),
                total_ttc=float(data.get("total_ttc") or 0),
                tva_rate=float(data.get("tva_rate") or 20),
                currency=data.get("currency") or "MAD",
                lines=data.get("lines") or [],
                raw_text=response.content,
                provider=response.provider,
                confidence=0.85,
            )
        except Exception as e:
            logger.error("ocr_parse_failed", extra={"error": str(e), "raw": response.content[:200]})
            return InvoiceOCRResult(success=False, error=f"Parse error: {str(e)}", raw_text=response.content, provider=response.provider)


_ocr_engine: Optional[InvoiceOCR] = None


def get_ocr_engine() -> InvoiceOCR:
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = InvoiceOCR()
    return _ocr_engine
