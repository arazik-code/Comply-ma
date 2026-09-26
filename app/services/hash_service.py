"""
Service d'empreinte numérique (hashing) pour factures.
Conforme DGI : SHA-256 (ou SHA-384/SHA-512) du fichier XML UBL 2.1.
Supporte le calcul en chaîne (hash chain) pour l'intégrité immuable.
"""
import hashlib
from typing import Optional


SUPPORTED_ALGORITHMS = {
    "sha256": hashlib.sha256,
    "sha384": hashlib.sha384,
    "sha512": hashlib.sha512,
}

DEFAULT_ALGORITHM = "sha256"


def compute_hash(xml_bytes: bytes, algorithm: str = DEFAULT_ALGORITHM) -> str:
    """
    Calcule l'empreinte numérique d'un fichier XML.

    Args:
        xml_bytes: Contenu du fichier XML en bytes
        algorithm: Algorithme de hashage (sha256, sha384, sha512)

    Returns:
        Empreinte hexadécimale
    """
    algo_fn = SUPPORTED_ALGORITHMS.get(algorithm.lower())
    if not algo_fn:
        raise ValueError(f"Algorithme non supporté: {algorithm}. Utilisez: {', '.join(SUPPORTED_ALGORITHMS)}")
    h = algo_fn()
    h.update(xml_bytes)
    return h.hexdigest()


def compute_hash_chain(xml_bytes: bytes, previous_hash: str, algorithm: str = DEFAULT_ALGORITHM) -> str:
    """
    Calcule un hash en chaîne : H(previous_hash + xml_bytes).
    Garantit l'intégrité immuable — toute modification du document précédent casse la chaîne.

    Args:
        xml_bytes: Contenu du fichier XML en bytes
        previous_hash: Hash du document précédent (vide pour le premier)
        algorithm: Algorithme de hashage

    Returns:
        Empreinte hexadécimale chaînée
    """
    algo_fn = SUPPORTED_ALGORITHMS.get(algorithm.lower())
    if not algo_fn:
        raise ValueError(f"Algorithme non supporté: {algorithm}")
    h = algo_fn()
    h.update(previous_hash.encode("utf-8"))
    h.update(xml_bytes)
    return h.hexdigest()


def verify_hash(xml_bytes: bytes, expected_hash: str, algorithm: str = DEFAULT_ALGORITHM) -> bool:
    """Vérifie que le hash calculé correspond au hash attendu."""
    return compute_hash(xml_bytes, algorithm) == expected_hash


def verify_hash_chain(
    xml_bytes: bytes,
    expected_hash: str,
    previous_hash: str,
    algorithm: str = DEFAULT_ALGORITHM,
) -> bool:
    """Vérifie un hash en chaîne."""
    return compute_hash_chain(xml_bytes, previous_hash, algorithm) == expected_hash


def compute_batch(documents: list[tuple[bytes, str]], algorithm: str = DEFAULT_ALGORITHM) -> list[str]:
    """
    Calcule les hashes de plusieurs documents en batch.

    Args:
        documents: Liste de (contenu_bytes, previous_hash)
        algorithm: Algorithme de hashage

    Returns:
        Liste des hashes calculés
    """
    results = []
    for xml_bytes, prev_hash in documents:
        results.append(compute_hash_chain(xml_bytes, prev_hash, algorithm))
    return results
