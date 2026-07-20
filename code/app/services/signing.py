import base64
import copy
import logging
from functools import lru_cache
from typing import Dict

import jcs  # RFC8785 canonicalization
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from app.core.config import settings

logger = logging.getLogger(__name__)


@lru_cache
def get_private_key() -> ec.EllipticCurvePrivateKey:
    """
    Get the ECDSA private key from the PEM file.

    Returns:
        ec.EllipticCurvePrivateKey: The loaded ECDSA private key.
    """
    with open(settings.SIGNING_PRIVATE_KEY_PATH, "rb") as f:
        return serialization.load_pem_private_key(
            f.read(),
            password=None,
        )


@lru_cache
def get_certificate() -> x509.Certificate:
    """
    Get the X.509 certificate from the PEM file.

    Returns:
        x509.Certificate: The loaded X.509 certificate.
    """

    with open(settings.SIGNING_CERTIFICATE_PATH, "rb") as f:
        return x509.load_pem_x509_certificate(f.read())


@lru_cache
def get_certificate_path() -> list[str]:
    """
    Get the base64-encoded DER representation of the certificate.

    Returns:
        list[str]: A list containing the base64-encoded DER representation of the certificate.
    """

    cert = get_certificate()
    der_bytes = cert.public_bytes(serialization.Encoding.DER)
    return [base64.b64encode(der_bytes).decode()]


def validate_signing_material():
    """
    Validate that the signing key and certificate match.

    Raises:
        RuntimeError: If the signing key and certificate do not match.
    """

    key = get_private_key()
    cert = get_certificate()

    if key.public_key().public_numbers() != cert.public_key().public_numbers():
        raise RuntimeError("Signing key and certificate do not match")


def sign_data(private_key: ec.EllipticCurvePrivateKey, data: bytes) -> str:
    """Sign provided bytes using ES256 and return base64(raw_r|raw_s).

    Produces a raw concatenated r||s signature encoded in base64 which is
    commonly used in JOSE-style signatures.

    Args:
        private_key: An ECDSA private key for signing.
        data: The bytes to sign.

    Returns:
        A base64-encoded string of the raw r||s signature.
    """

    if not isinstance(private_key.curve, ec.SECP256R1):
        raise ValueError("ES256 requires P-256 curve")

    signature = private_key.sign(data, ec.ECDSA(hashes.SHA256()))

    # Convert DER signature to raw r|s format
    r, s = decode_dss_signature(signature)
    raw_signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")

    return base64.urlsafe_b64encode(raw_signature).rstrip(b"=").decode("ascii")


def sign_report(report: Dict) -> Dict:
    """
    Sign the given CycloneDX report using ES256.

    Args:
        report (dict): The CycloneDX report to be signed.

    Returns:
        dict: The signed CycloneDX report with the signature added.
    """

    logger.debug("Starting report signing")

    report = copy.deepcopy(report)

    private_key = get_private_key()
    cert_path = get_certificate_path()

    # Remove existing signature if present
    # NOTE: Maybe prevent signing an already signed report.
    report.pop("signature", None)

    # Create signature object WITHOUT value
    report["signature"] = {"algorithm": "ES256", "certificatePath": cert_path}

    # Canonicalize JSON (RFC8785)
    canonical_json = jcs.canonicalize(report)

    # Sign canonical JSON
    signature_value = sign_data(private_key, canonical_json)

    # Add signature value
    report["signature"]["value"] = signature_value

    logger.debug("Report signed successfully")
    return report
