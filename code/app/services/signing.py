import base64
import copy
import functools
import logging
import os
import threading
from typing import Callable, Dict, TypeVar

import jcs  # RFC8785 canonicalization
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class SigningError(RuntimeError):
    """Raised when the signing key and certificate do not match."""


class SignatureVerificationError(ValueError):
    """Raised when a signed report's signature is missing, malformed or invalid."""


def load_if_changed(path: str) -> Callable[[Callable[[], T]], Callable[[], T]]:
    """Decorator factory that caches a zero-arg loader's return value,
    reloading it whenever the file at `path` has changed (tracked by
    modification time) since it was last loaded. This lets a rotated
    key/certificate be picked up on the next call, without requiring a
    process restart.

    This is a factory (called with `path` to produce the actual decorator)
    rather than a plain decorator, because each use watches a different
    file -- the same reason `functools.lru_cache(maxsize=...)` is a
    factory too. `path` is resolved once, when the decorator is applied
    (typically at import time), so it must already be the file's final
    configured location.

    Args:
        path: Path of the file to watch for changes.

    Returns:
        A decorator that wraps a zero-arg loader function with the
        caching/reload behavior described above.
    """

    cache: dict = {}
    lock = threading.Lock()

    def reload_on_change(func: Callable[[], T]) -> Callable[[], T]:
        """Wrap `func` with the caching/reload behavior for `path`.

        Args:
            func: Zero-arg function that loads and returns the value
                currently at `path`.

        Returns:
            A zero-arg function returning the cached value, transparently
            reloaded via `func` whenever `path`'s mtime changes.
        """

        @functools.wraps(func)
        def wrapper() -> T:
            mtime = os.stat(path).st_mtime

            with lock:
                if cache.get("mtime") != mtime:
                    logger.info("Loading %s from %s", func.__name__, path)
                    cache["value"] = func()
                    cache["mtime"] = mtime

                return cache["value"]

        return wrapper

    return reload_on_change


@load_if_changed(path=settings.SIGNING_PRIVATE_KEY_PATH)
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


@load_if_changed(path=settings.SIGNING_CERTIFICATE_PATH)
def get_certificate() -> x509.Certificate:
    """
    Get the X.509 certificate from the PEM file.

    Returns:
        x509.Certificate: The loaded X.509 certificate.
    """

    with open(settings.SIGNING_CERTIFICATE_PATH, "rb") as f:
        return x509.load_pem_x509_certificate(f.read())


def get_certificate_path(cert: x509.Certificate | None = None) -> list[str]:
    """
    Get the JSF `certificatePath` of the certificate: its DER encoding as
    unpadded base64url, like every JSF `byte[]` value.

    Args:
        cert: Certificate to encode. Defaults to the current
            `get_certificate()` value if not given.

    Returns:
        list[str]: A list containing the base64url DER encoding of the certificate.
    """

    if cert is None:
        cert = get_certificate()

    der_bytes = cert.public_bytes(serialization.Encoding.DER)
    return [base64.urlsafe_b64encode(der_bytes).rstrip(b"=").decode("ascii")]


def validate_signing_material(
    key: ec.EllipticCurvePrivateKey | None = None, cert: x509.Certificate | None = None
) -> None:
    """
    Validate that the signing key and certificate match.

    Args:
        key: Private key to validate. Defaults to the current
            `get_private_key()` value if not given.
        cert: Certificate to validate. Defaults to the current
            `get_certificate()` value if not given.

    Raises:
        SigningError: If the signing key and certificate do not match.
    """

    if key is None:
        key = get_private_key()
    if cert is None:
        cert = get_certificate()

    if key.public_key().public_numbers() != cert.public_key().public_numbers():
        raise SigningError("Signing key and certificate do not match")


def sign_data(private_key: ec.EllipticCurvePrivateKey, data: bytes) -> str:
    """Sign provided bytes using ES256 and return base64url(raw_r|raw_s).

    Produces a raw concatenated r||s signature encoded as unpadded base64url,
    as JWA (RFC 7518) and JSF require.

    Args:
        private_key: An ECDSA private key for signing.
        data: The bytes to sign.

    Returns:
        An unpadded base64url string of the raw r||s signature.
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
    cert = get_certificate()

    validate_signing_material(key=private_key, cert=cert)

    cert_path = get_certificate_path(cert)

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


def decode_base64url(value: str) -> bytes:
    """Decode unpadded base64url, the encoding JSF uses for binary values.

    Args:
        value: The base64url string, with or without padding.

    Returns:
        The decoded bytes.
    """

    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def verify_data(
    public_key: ec.EllipticCurvePublicKey, data: bytes, signature_value: str
) -> None:
    """Verify an ES256 signature produced by `sign_data`.

    Args:
        public_key: The ECDSA public key to verify with.
        data: The signed bytes.
        signature_value: The base64url raw r||s signature.

    Raises:
        SignatureVerificationError: If the signature is malformed or does not
            match the data and key.
    """

    if not isinstance(public_key.curve, ec.SECP256R1):
        raise SignatureVerificationError("ES256 requires a P-256 key")

    try:
        raw_signature = decode_base64url(signature_value)
    except ValueError as e:
        raise SignatureVerificationError(
            f"Signature value is not valid base64url: {e}"
        ) from e

    if len(raw_signature) != 64:
        raise SignatureVerificationError(
            f"ES256 signature must be 64 bytes, got {len(raw_signature)}"
        )

    # Convert raw r|s format back to DER
    r = int.from_bytes(raw_signature[:32], "big")
    s = int.from_bytes(raw_signature[32:], "big")

    try:
        public_key.verify(
            encode_dss_signature(r, s), data, ec.ECDSA(hashes.SHA256())
        )
    except InvalidSignature as e:
        raise SignatureVerificationError("Signature does not match") from e


def verify_report(report: Dict) -> None:
    """
    Verify the ES256 signature of a CycloneDX report signed by `sign_report`.

    The signature is checked against the public key of the first
    certificate in `signature.certificatePath`, over the RFC8785 canonical
    JSON of the report without `signature.value`. This checks integrity
    only: whether the certificate is trusted is not checked.

    Args:
        report (dict): The signed CycloneDX report.

    Raises:
        SignatureVerificationError: If the signature is missing, malformed or
            invalid.
    """

    logger.debug("Starting report signature verification")

    report = copy.deepcopy(report)

    signature = report.get("signature")
    if not isinstance(signature, dict):
        raise SignatureVerificationError("Report is not signed")

    if signature.get("algorithm") != "ES256":
        raise SignatureVerificationError(
            f"Unsupported signature algorithm: {signature.get('algorithm')!r}"
        )

    signature_value = signature.pop("value", None)
    if not isinstance(signature_value, str):
        raise SignatureVerificationError("Signature has no value")

    cert_path = signature.get("certificatePath")
    if not isinstance(cert_path, list) or not cert_path:
        raise SignatureVerificationError("Signature has no certificate")

    try:
        # JSF uses base64url. Standard base64 also decodes, so certificates
        # signed before STRAE switched to base64url still verify.
        cert = x509.load_der_x509_certificate(decode_base64url(cert_path[0]))
    except ValueError as e:
        raise SignatureVerificationError(f"Invalid signing certificate: {e}") from e

    public_key = cert.public_key()
    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise SignatureVerificationError("Signing certificate is not an EC key")

    # Canonicalize JSON (RFC8785), without the signature value, as when signing
    canonical_json = jcs.canonicalize(report)

    verify_data(public_key, canonical_json, signature_value)

    logger.debug("Report signature verified successfully")
