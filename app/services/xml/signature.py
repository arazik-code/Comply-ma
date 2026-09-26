"""
Module de signature numérique pour documents XML.
Supporte :
  - Self-signed (développement)
  - PKCS#12 (production — Barid e-Sign, etc.)
  - Vérification de signature
"""
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger("app.xml.signature")

try:
    from lxml import etree as lxml_etree
    from signxml import XMLSigner, XMLVerifier, methods
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_der_private_key
    # cryptography >= 42 : les chargeurs de certificats vivent dans cryptography.x509
    from cryptography.x509 import load_pem_x509_certificate, load_der_x509_certificate
    from cryptography.x509 import (
        CertificateBuilder, Name, NameAttribute, BasicConstraints,
        SubjectAlternativeName, DNSName, oid,
    )
    from cryptography import x509 as cryptography_x509
    from cryptography.hazmat.primitives.serialization import pkcs12

    HAS_SIGNXML = True
except ImportError:
    HAS_SIGNXML = False
    logger.warning("signxml not available — XML-DSig disabled (pip install signxml)")


class XmlSigner:
    """Interface abstraite pour les signataires XML."""
    def sign(self, xml_bytes: bytes, cert_path: Optional[str] = None) -> bytes:
        raise NotImplementedError

    def verify(self, signed_xml_bytes: bytes) -> bool:
        raise NotImplementedError


class SelfSignedSigner(XmlSigner):
    """Signataire avec certificat auto-généré (dev/test)."""
    def __init__(self):
        self.cert_path = settings.self_signed_cert_path
        self.key_path = settings.self_signed_key_path

    def sign(self, xml_bytes: bytes, cert_path: Optional[str] = None) -> bytes:
        if not HAS_SIGNXML:
            marker = b"<!-- Signature XML-DSig non disponible (signxml manquant) -->\n"
            return xml_bytes + marker

        path = cert_path or str(self.cert_path)
        key_path = str(self.key_path)

        with open(key_path, "rb") as f:
            private_key = load_pem_private_key(f.read(), password=None)
        with open(path, "rb") as f:
            cert = cryptography_x509.load_pem_x509_certificate(f.read())

        signer = XMLSigner(
            method=methods.enveloped,
            signature_algorithm="rsa-sha256",
            digest_algorithm="sha256",
        )

        xml_doc = lxml_etree.fromstring(xml_bytes)
        signed_element = signer.sign(xml_doc, key=private_key, cert=[cert])
        signed_xml = lxml_etree.tostring(signed_element, xml_declaration=True, encoding="UTF-8")
        logger.info("xml_signed_selfsigned", extra={"cert": path})
        return signed_xml

    def verify(self, signed_xml_bytes: bytes) -> bool:
        if not HAS_SIGNXML:
            return False
        try:
            cert_path = str(self.cert_path)
            with open(cert_path, "rb") as f:
                cert = cryptography_x509.load_pem_x509_certificate(f.read())
            xml_doc = lxml_etree.fromstring(signed_xml_bytes)
            XMLVerifier().verify(xml_doc, x509_cert=cert)
            return True
        except Exception as e:
            logger.warning("signature_verification_failed", extra={"error": str(e)})
            return False


class PKCS12Signer(XmlSigner):
    """
    Signataire avec certificat PKCS#12 (.p12/.pfx).
    Pour production avec Barid e-Sign ou autre CA marocain.
    """
    def __init__(self, p12_path: str, passphrase: Optional[bytes] = None):
        self.p12_path = Path(p12_path)
        self.passphrase = passphrase

    def sign(self, xml_bytes: bytes, cert_path: Optional[str] = None) -> bytes:
        if not HAS_SIGNXML:
            marker = b"<!-- Signature XML-DSig non disponible (signxml manquant) -->\n"
            return xml_bytes + marker

        if not self.p12_path.exists():
            raise FileNotFoundError(f"Certificat PKCS#12 introuvable: {self.p12_path}")

        with open(self.p12_path, "rb") as f:
            p12_data = f.read()

        private_key, cert, chain = pkcs12.load_key_and_certificates(
            p12_data, self.passphrase
        )

        if private_key is None or cert is None:
            raise ValueError("Certificat PKCS#12 invalide ou mot de passe incorrect")

        signer = XMLSigner(
            method=methods.enveloped,
            signature_algorithm="rsa-sha256",
            digest_algorithm="sha256",
        )

        xml_doc = lxml_etree.fromstring(xml_bytes)
        certs = [cert] + (chain or [])
        signed_element = signer.sign(xml_doc, key=private_key, cert=certs)
        signed_xml = lxml_etree.tostring(signed_element, xml_declaration=True, encoding="UTF-8")
        logger.info("xml_signed_pkcs12", extra={"cert": str(self.p12_path)})
        return signed_xml

    def verify(self, signed_xml_bytes: bytes) -> bool:
        if not HAS_SIGNXML:
            return False
        try:
            with open(self.p12_path, "rb") as f:
                p12_data = f.read()
            _, cert, _ = pkcs12.load_key_and_certificates(p12_data, self.passphrase)
            if cert is None:
                return False
            xml_doc = lxml_etree.fromstring(signed_xml_bytes)
            XMLVerifier().verify(xml_doc, x509_cert=cert)
            return True
        except Exception as e:
            logger.warning("pkcs12_verification_failed", extra={"error": str(e)})
            return False


def verify_xml_signature(signed_xml_bytes: bytes, cert_pem: Optional[bytes] = None) -> bool:
    """
    Vérifie la signature XML-DSig d'un document signé.
    Si cert_pem est fourni, utilise ce certificat. Sinon, essaie le certificat auto-signé.
    """
    if not HAS_SIGNXML:
        return False

    try:
        xml_doc = lxml_etree.fromstring(signed_xml_bytes)
        if cert_pem:
            cert = load_pem_x509_certificate(cert_pem)
            XMLVerifier().verify(xml_doc, x509_cert=cert)
        else:
            XMLVerifier().verify(xml_doc)
        return True
    except Exception as e:
        logger.warning("signature_verification_failed", extra={"error": str(e)})
        return False


_signer_instance: Optional[XmlSigner] = None


def get_signer() -> XmlSigner:
    """Retourne le signataire configuré (singleton)."""
    global _signer_instance
    if _signer_instance is None:
        p12_path = getattr(settings, "pkcs12_cert_path", "")
        p12_pass = getattr(settings, "pkcs12_passphrase", "")
        if p12_path and Path(p12_path).exists():
            _signer_instance = PKCS12Signer(p12_path, p12_pass.encode() if p12_pass else None)
        else:
            _signer_instance = SelfSignedSigner()
    return _signer_instance


def reset_signer():
    """Réinitialise le signataire (utile après changement de config)."""
    global _signer_instance
    _signer_instance = None


def generate_self_signed_cert(force: bool = False):
    cert_path = settings.self_signed_cert_path
    key_path = settings.self_signed_key_path

    if cert_path.exists() and key_path.exists() and not force:
        return

    settings.cert_dir.mkdir(parents=True, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = Name([
        NameAttribute(oid.NameOID.COUNTRY_NAME, "MA"),
        NameAttribute(oid.NameOID.ORGANIZATION_NAME, "COMPLY-MA"),
        NameAttribute(oid.NameOID.COMMON_NAME, "COMPLY-MA Test Cert"),
    ])

    cert = (
        CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=3650))
        .add_extension(BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(SubjectAlternativeName([DNSName("localhost")]), critical=False)
        .sign(private_key=key, algorithm=hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    logger.info("self_signed_cert_generated", extra={"cert": str(cert_path)})
