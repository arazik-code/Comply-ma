from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "COMPLY-MA"
    app_version: str = "1.0.0"
    debug: bool = False

    # Environnement : "dev" ou "production". En production, la clé secrète
    # par défaut est refusée au démarrage et les cookies sont Secure.
    environment: str = "dev"
    https_only: bool = False  # Force le flag Secure sur les cookies de session

    database_url: str = "sqlite:///./comply-ma.db"
    database_echo: bool = False

    secret_key: str = "change-me-in-production"

    @property
    def is_default_secret(self) -> bool:
        return self.secret_key in ("change-me-in-production", "", "changer-en-production-cle-longue-et-aleatoire")
    session_max_age: int = 86400  # 24h

    # Sécurité : coût bcrypt pour les mots de passe
    bcrypt_rounds: int = 12

    # Chemins de stockage
    data_dir: Path = Path("./data")
    archive_dir: Path = Path("./data/archives")
    logo_dir: Path = Path("./data/logos")
    cert_dir: Path = Path("./data/certs")

    # Provider de clearance : "mock" (dev/test) ou "dgi" (production, quant l'API sera publiée)
    clearance_provider: str = "mock"

    # Logging
    log_level: str = "info"
    log_format: str = "text"  # "text" ou "json"

    # Signature XML-DSig
    xml_sign_enabled: bool = True
    self_signed_cert_path: Path = Path("./data/certs/self-signed.pem")
    self_signed_key_path: Path = Path("./data/certs/self-signed-key.pem")
    pkcs12_cert_path: str = ""  # Chemin vers le certificat PKCS#12 (.p12/.pfx) pour production
    pkcs12_passphrase: str = ""  # Mot de passe du certificat PKCS#12

    # Format XML par défaut : "ubl" ou "cii"
    xml_format: str = "ubl"

    # Configuration DGI (à remplacer par les vrais endpoints)
    dgi_api_base_url: str = ""
    dgi_api_key: str = ""
    dgi_token_url: str = ""
    dgi_client_id: str = ""
    dgi_client_secret: str = ""
    dgi_scope: str = "invoices"
    dgi_mtls_cert_path: str = ""
    dgi_mtls_key_path: str = ""

    # WhatsApp Cloud API
    whatsapp_api_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = "comply-ma-verify"
    whatsapp_app_secret: str = ""

    # TVA — période de rétention légale (ans)
    retention_years: int = 10

    # SMTP — envoi d'emails
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_tls: bool = True

    # ── AI Providers ──────────────────────────────────────────────
    ai_openai_api_key: str = ""
    ai_openai_base_url: str = ""
    ai_gemini_api_key: str = ""
    ai_claude_api_key: str = ""
    ai_nvidia_api_key: str = ""
    ai_hf_token: str = ""         # HuggingFace free tier
    ai_groq_key: str = ""         # Groq free tier
    ai_together_key: str = ""     # Together free tier

    # ── PDF/A & Timestamping ──────────────────────────────────────
    pdfa_conformance: str = "pdfa-3b"
    timestamp_enabled: bool = True

    # ── Cabinet Mode (Fiduciaire) ─────────────────────────────────
    cabinet_mode: bool = False  # True = multi-tenant fiduciaire mode
    cabinet_id: str = ""        # Current cabinet ID (set per deployment)

    model_config = {"env_prefix": "COMPLY_MA_", "env_file": ".env"}


settings = Settings()
