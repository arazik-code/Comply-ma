"""Darija NLP and translation service for Moroccan Arabic."""
import logging
from dataclasses import dataclass
from typing import Optional

from app.services.ai.providers import get_ai_service, AIResponse

logger = logging.getLogger("app.services.ai.nlp")


@dataclass
class TranslationResult:
    original: str
    translated: str
    source_lang: str
    target_lang: str
    provider: str = ""
    confidence: float = 0.0
    success: bool = True
    error: str = ""


@dataclass
class NLPResult:
    text: str
    tokens: list[str]
    entities: list[dict]
    sentiment: str
    language: str
    summary: str = ""
    success: bool = True
    error: str = ""


# Common Darija → French/English dictionary
DARIJA_DICTIONARY = {
    "shnu": "quoi", "kifach": "comment", "3lach": "pourquoi", "fin": "où",
    "kayn": "il y a", "ma3rftch": "je ne sais pas", "safi": "c'est tout",
    "yallah": "allez", "hna": "ici", "daba": "maintenant", "ghir": "seulement",
    "wakil": "peut-être", "inshallah": "si Dieu veut", "bismillah": "au nom de Dieu",
    "shukran": "merci", "afak": "s'il te plaît", "sm3t": "j'ai entendu",
    "ghir": "autre", "koulchi": "tout", "walou": "rien",
    "zyan": "bien", "khayb": "mauvais", "kbir": "grand", "sghir": "petit",
    "jdid": "nouveau", "qdim": "ancien", "skhoun": "chaud", "bared": "froid",
    "l3rof": "les informations", "factura": "facture", "flous": "argent",
    "khyara": "choix", "tsdra": "exportation", "tsdmira": "importation",
    "dgi": "direction générale des impôts", "tva": "taxe sur la valeur ajoutée",
    "ice": "identifiant commun de l'entreprise", "rc": "registre de commerce",
    "if": "identifiant fiscal", "cnss": "caisse nationale de sécurité sociale",
}


class DarijaTranslator:
    """Translates between Darija (Moroccan Arabic), French, and English."""

    def __init__(self):
        self.ai = get_ai_service()
        self.dictionary = DARIJA_DICTIONARY

    def darija_to_french(self, text: str) -> TranslationResult:
        return self._translate(text, "darija", "french")

    def darija_to_english(self, text: str) -> TranslationResult:
        return self._translate(text, "darija", "english")

    def french_to_darija(self, text: str) -> TranslationResult:
        return self._translate(text, "french", "darija")

    def english_to_darija(self, text: str) -> TranslationResult:
        return self._translate(text, "english", "darija")

    def auto_detect_and_translate(self, text: str, target: str = "french") -> TranslationResult:
        prompt = f"""Detecte la langue du texte suivant et traduis-le en {target}.

Texte: {text}

Retourne un JSON:
{{"detected_lang": "langue détectée", "translation": "traduction", "confidence": 0.0-1.0}}"""

        response = self.ai.chat(prompt, system="Tu es un traducteur expert en langues marocaines (darija, arabe, français, anglais).", temperature=0.1)
        if response.success:
            try:
                import json
                data = json.loads(response.content)
                return TranslationResult(
                    original=text, translated=data.get("translation", ""), source_lang=data.get("detected_lang", "auto"), target_lang=target, provider=response.provider, confidence=data.get("confidence", 0.8), success=True
                )
            except Exception:
                pass
        return TranslationResult(original=text, translated=text, source_lang="auto", target_lang=target, success=False, error="Translation failed")

    def _translate(self, text: str, source: str, target: str) -> TranslationResult:
        # Try dictionary first for simple words
        text_lower = text.lower().strip()
        if text_lower in self.dictionary:
            return TranslationResult(original=text, translated=self.dictionary[text_lower], source_lang=source, target_lang=target, confidence=1.0, provider="dictionary")

        prompt = f"Traduis ce texte de {source} vers {target}:\n\n{text}\n\nRetourne UNIQUEMENT la traduction, sans explication."
        response = self.ai.chat(prompt, system="Tu es un traducteur expert spécialisé dans les dialectes marocains.", temperature=0.3, max_tokens=500)

        if response.success:
            return TranslationResult(original=text, translated=response.content.strip(), source_lang=source, target_lang=target, provider=response.provider, confidence=0.85, success=True)

        return TranslationResult(original=text, translated=text, source_lang=source, target_lang=target, success=False, error=response.error)

    def translate_invoice_terms(self, text: str, target: str = "french") -> str:
        """Translate common invoice terms."""
        result = self._translate(text, "darija", target)
        return result.translated if result.success else text


class MoroccanNLPEngine:
    """NLP engine specialized for Moroccan business documents."""

    def __init__(self):
        self.ai = get_ai_service()
        self.translator = DarijaTranslator()

    def analyze_text(self, text: str) -> NLPResult:
        prompt = f"""Analyse ce texte marocain et extrais:
1. Les tokens/mots importants
2. Les entités nommées (personnes, organisations, montants, dates)
3. Le sentiment (positif/négatif/neutre)
4. La langue détectée

Texte: {text}

Retourne un JSON:
{{
    "tokens": ["mot1", "mot2", ...],
    "entities": [{{"text": "...", "type": "PERSON|ORG|MONEY|DATE", "value": "..."}}],
    "sentiment": "positive|negative|neutral",
    "language": "darija|french|arabic|english",
    "summary": "résumé court"
}}"""

        response = self.ai.chat(prompt, system="Tu es un expert NLP spécialisé dans les textes marocains.", temperature=0.1)
        if response.success:
            try:
                import json
                data = json.loads(response.content)
                return NLPResult(
                    text=text, tokens=data.get("tokens", []), entities=data.get("entities", []),
                    sentiment=data.get("sentiment", "neutral"), language=data.get("language", "darija"),
                    summary=data.get("summary", ""), success=True, provider=response.provider
                )
            except Exception:
                pass
        return NLPResult(text=text, tokens=[], entities=[], sentiment="neutral", language="unknown", success=False, error="NLP analysis failed")

    def extract_entities(self, text: str) -> list[dict]:
        prompt = f"""Extrais toutes les entités nommées de ce texte marocain.

Texte: {text}

Retourne un JSON: [{{"text": "...", "type": "PERSON|ORG|MONEY|DATE|ICE|ADDRESS", "value": "..."}}]"""

        response = self.ai.chat(prompt, temperature=0.1)
        if response.success:
            try:
                import json
                return json.loads(response.content)
            except Exception:
                pass
        return []

    def summarize(self, text: str, max_length: int = 100) -> str:
        prompt = f"Résume ce texte en {max_length} mots maximum:\n\n{text}"
        response = self.ai.chat(prompt, temperature=0.3, max_tokens=200)
        return response.content.strip() if response.success else text[:max_length]


_nlp_engine: Optional[MoroccanNLPEngine] = None


def get_nlp_engine() -> MoroccanNLPEngine:
    global _nlp_engine
    if _nlp_engine is None:
        _nlp_engine = MoroccanNLPEngine()
    return _nlp_engine
