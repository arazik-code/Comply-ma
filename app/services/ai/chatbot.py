"""WhatsApp chatbot with AI — conversational interface for invoice queries."""
import json
import logging
from dataclasses import dataclass
from typing import Optional

from app.services.ai.providers import get_ai_service, AIResponse
from app.services.ai.nlp import DarijaTranslator, get_nlp_engine

logger = logging.getLogger("app.services.ai.chatbot")


@dataclass
class ChatResponse:
    reply: str
    language: str = "darija"
    intent: str = ""
    entities: dict = None
    provider: str = ""
    success: bool = True
    error: str = ""

    def __post_init__(self):
        if self.entities is None:
            self.entities = {}


INTENT_SYSTEM_PROMPT = """Tu es l'assistant virtuel de COMPLY-MA, une plateforme de facturation électronique marocaine.
Tu parles principalement en darija (arabe marocain) avec des mots de français technique.
Tu réponds de manière concise et utile.

Capacités:
- Vérifier le statut des factures
- Expliquer les champs de facturation
- Aider avec la conformité DGI
- Expliquer la TVA et les calculs
- Répondre aux questions sur ICE, RC, IF
- Guider l'utilisateur dans l'utilisation de la plateforme

Format de réponse: court, clair, en darija avec termes techniques en français."""

INTENT_DETECTION_PROMPT = """Analyse cette intention de l'utilisateur et retourne un JSON:
{"intent": "intent_name", "entities": {"key": "value"}, "language": "darija|french|english"}

Intents possibles:
- check_invoice: vérifier une facture
- explain_tva: expliquer la TVA
- explain_ice: expliquer l'ICE
- check_compliance: vérifier la conformité
- help: demander de l'aide
- greeting: salutation
- thanks: remercier
- general: question générale

Texte: {text}"""


class WhatsAppChatbot:
    """AI-powered WhatsApp chatbot for invoice queries."""

    def __init__(self):
        self.ai = get_ai_service()
        self.translator = DarijaTranslator()
        self.nlp = get_nlp_engine()

    def handle_message(self, message: str, sender: str = "", context: dict = None) -> ChatResponse:
        if not message or not message.strip():
            return ChatResponse(reply="Bonjour! Kifach n9der n3awnek? (Comment puis-je vous aider?)", success=True)

        message = message.strip()
        logger.info("chatbot_message_received", extra={"sender": sender, "message": message[:100]})

        # Detect intent
        intent_result = self._detect_intent(message)
        intent = intent_result.get("intent", "general")
        entities = intent_result.get("entities", {})
        detected_lang = intent_result.get("language", "darija")

        logger.info("chatbot_intent_detected", extra={"intent": intent, "entities": entities, "language": detected_lang})

        # Route to appropriate handler
        reply = self._route_intent(intent, message, entities, detected_lang)

        return ChatResponse(
            reply=reply,
            language=detected_lang,
            intent=intent,
            entities=entities,
            success=True,
        )

    def _detect_intent(self, message: str) -> dict:
        prompt = INTENT_DETECTION_PROMPT.format(text=message)
        response = self.ai.chat(prompt, system=INTENT_SYSTEM_PROMPT, temperature=0.1, max_tokens=200)
        if response.success:
            try:
                text = response.content.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                return json.loads(text.strip())
            except Exception:
                pass
        return {"intent": "general", "entities": {}, "language": "darija"}

    def _route_intent(self, intent: str, message: str, entities: dict, language: str) -> str:
        handlers = {
            "check_invoice": self._handle_check_invoice,
            "explain_tva": self._handle_explain_tva,
            "explain_ice": self._handle_explain_ice,
            "check_compliance": self._handle_check_compliance,
            "help": self._handle_help,
            "greeting": self._handle_greeting,
            "thanks": self._handle_thanks,
            "general": self._handle_general,
        }
        handler = handlers.get(intent, self._handle_general)
        return handler(message, entities, language)

    def _handle_check_invoice(self, message: str, entities: dict, language: str) -> str:
        prompt = f"L'utilisateur veut vérifier une facture. Message: {message}\n\nRéponds en {language} avec les étapes pour vérifier une facture sur COMPLY-MA."
        response = self.ai.chat(prompt, system=INTENT_SYSTEM_PROMPT, temperature=0.5)
        return response.content if response.success else "Pour vérifier une facture, allez dans Factures > Cliquer sur le numéro de facture."

    def _handle_explain_tva(self, message: str, entities: dict, language: str) -> str:
        if language == "darija":
            return """📋 **TVA (Taxe sur la Valeur Ajoutée)**

Fi l-Maghrib, 3ndna les taux TVA kamlin:
• **0%** — Produits de base (khobz, lbzar, lma)
• **7%** — Produits alimentaires, livres
• **10%** — Hôtels, transports
• **14%** — Produits industriels
• **20%** — Taux général

**Calcule:**
TVA = HT × taux
TTC = HT + TVA

Matalan: 1000 MAD HT × 20% = 200 MAD TVA = 1200 MAD TTC

Kol facture lazim tkoun mémoire DGI w fih ICE dyal supplier."""
        return "TVA rates in Morocco: 0%, 7%, 10%, 14%, 20%. Standard rate is 20%."

    def _handle_explain_ice(self, message: str, entities: dict, language: str) -> str:
        if language == "darija":
            return """🏢 **ICE (Identifiant Commun de l'Entreprise)**

ICE huwa numérotation dyal l-entreprise f l-Maghrib:
• **15 chiffres** — koul enterprise 3ndha wa7d
• Format: XXXXXXXNNNNNNN (7 chiffres établissement + 8 identifiant)
• Kayt-check b **modulo 97**

**Fin l9it l-ICE?**
• F carte CNSS
• F avis d'imposition
• Sur le site DGI: www.dgi.gov.ma

**3lach important?**
Kol facture lazim fih ICE dyal supplier w dyal client. bla ma tmchi l DGI!"""
        return "ICE is the Moroccan business identifier (15 digits). Required on all invoices for DGI compliance."

    def _handle_check_compliance(self, message: str, entities: dict, language: str) -> str:
        if language == "darija":
            return """✅ **Vérification de Conformité DGI**

Pour vérifier si une facture est conforme:
1. **ICE** — Lazim ykoun fih ICE dyal supplier (15 chiffres)
2. **Numéro** — Format: F000000001/2025
3. **Dates** — Ma ykounch f le futur
4. **TVA** — Les taux: 0%, 7%, 10%, 14%, 20%
5. **Montants** — TTC = HT + TVA

Sur COMPLY-MA: Factures > Facture > "Vérifier Conformité" button

L'engine dyalna kaysken 27 checks automatiquement!"""
        return "COMPLY-MA checks 27 compliance rules automatically: ICE format, invoice numbering, TVA rates, date validation, amount coherence, and more."

    def _handle_help(self, message: str, entities: dict, language: str) -> str:
        if language == "darija":
            return """🤖 **COMPLY-MA — Assistant Virtuel**

Ana hna bach n3awnek! Qder n3awnek f:
• 📄 **Factures** — Créer, vérifier, envoyer
• 📊 **TVA** — Calculer, expliquer les taux
• 🏢 **ICE** — Comprendre, vérifier
• ✅ **Conformité** — Vérifier les factures
• 📦 **Bons de commande** — Gérer les achats
• 🔄 **Avoirs** — Créer des credit notes

Goul lia chno bghiti w n3awnek! 💬"""
        return "I'm your COMPLY-MA assistant! I can help with invoices, TVA, ICE, compliance, purchase orders, and more. Just ask!"

    def _handle_greeting(self, message: str, entities: dict, language: str) -> str:
        if language == "darija":
            return "Salam! 👋 Ana l-assistant dyal COMPLY-MA. Kifach n9der n3awnek l-yom? 💬"
        return "Hello! 👋 I'm your COMPLY-MA assistant. How can I help you today? 💬"

    def _handle_thanks(self, message: str, entities: dict, language: str) -> str:
        if language == "darija":
            return "Afwan! 😊 Goul lia ila 7tajti chi haja okhra. ana hna daiman! 🤝"
        return "You're welcome! 😊 Let me know if you need anything else. I'm here to help! 🤝"

    def _handle_general(self, message: str, entities: dict, language: str) -> str:
        prompt = f"L'utilisateur dit: {message}\n\nRéponds en {language} de manière utile et concise. Si c'est une question sur la facturation, guide vers COMPLY-MA."
        response = self.ai.chat(prompt, system=INTENT_SYSTEM_PROMPT, temperature=0.5, max_tokens=300)
        return response.content if response.success else "Je ne suis pas sûr de comprendre. Pouvez-vous reformuler? 🤔"


_chatbot: Optional[WhatsAppChatbot] = None


def get_chatbot() -> WhatsAppChatbot:
    global _chatbot
    if _chatbot is None:
        _chatbot = WhatsAppChatbot()
    return _chatbot
