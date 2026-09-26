"""
Sécurité des uploads — validation de type MIME et taille.

Utilisé pour les logos d'entreprise et tout futur upload de fichiers.
"""
import logging
from pathlib import Path

logger = logging.getLogger("app.upload_security")

ALLOWED_IMAGE_TYPES = {
    ".png": b"\x89PNG\r\n\x1a\n",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".webp": b"RIFF",
}

MAX_IMAGE_SIZE = 2 * 1024 * 1024  # 2 Mo


class UploadValidationError(ValueError):
    """Upload rejeté (type ou taille invalide)."""


def validate_image_upload(filename: str | None, content: bytes) -> str:
    """
    Valide un upload d'image : extension autorisée, magic bytes cohérents,
    taille <= MAX_IMAGE_SIZE.

    Retourne l'extension canonique (".png", ".jpg" ou ".webp").
    Lève UploadValidationError si invalide.
    """
    if not filename:
        raise UploadValidationError("Nom de fichier manquant")

    ext = Path(filename).suffix.lower()
    if ext == ".jpeg":
        ext = ".jpg"
    if ext not in ALLOWED_IMAGE_TYPES:
        raise UploadValidationError(
            f"Type de fichier non autorisé ({ext or '?'}). "
            "Formats acceptés : PNG, JPEG, WebP."
        )

    if len(content) > MAX_IMAGE_SIZE:
        raise UploadValidationError("Fichier trop volumineux (max 2 Mo)")

    if not content:
        raise UploadValidationError("Fichier vide")

    magic = ALLOWED_IMAGE_TYPES[ext]
    if not content.startswith(magic):
        raise UploadValidationError(
            "Le contenu du fichier ne correspond pas à son extension"
        )

    logger.info("upload_validated", extra={"ext": ext, "size": len(content)})
    return ext
