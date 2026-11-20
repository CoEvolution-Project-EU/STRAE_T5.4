import base64
import copy
import functools
import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
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
from app.models.trusted_keys import TrustedKey, TrustedKeys

logger = logging.getLogger(__name__)

T = TypeVar("T")


class SigningError(RuntimeError):
    """Raised when the signing material can't be used to sign: the key and
    certificate don't match, the certificate is expired or not yet valid, the
    key is not in the trust list, or the trust list can't be loaded.
    """


class SignatureVerificationError(ValueError):
    """Raised when a signed report's signature is missing, malformed or invalid."""


class TrustListError(RuntimeError):
    """Raised when the trust list is missing or malformed.

    This is a server misconfiguration, not a problem with a document, so it
    must not be reported as an invalid signature.
    """


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


@load_if_changed(path=settings.TRUSTED_KEYS_PATH)
def load_trusted_keys() -> dict[str, TrustedKey]:
    """Load the trust list from `TRUSTED_KEYS_PATH`.

    Returns:
        The trusted keys, keyed by public key fingerprint.

    Raises:
        TrustListError: If the file can't be read, is not valid JSON, or
            doesn't match the `TrustedKeys` model.
    """

    path = settings.TRUSTED_KEYS_PATH

    try:
        with open(path, "rb") as f:
            trusted = TrustedKeys.model_validate(json.load(f))
    except OSError as e:
        raise TrustListError(f"Trust list {path} can't be read: {e}") from e
    # Invalid JSON, invalid UTF-8 and Pydantic errors are all `ValueError`s.
    except ValueError as e:
        raise TrustListError(f"Trust list {path} is invalid: {e}") from e

    logger.info("Loaded %d trusted signing keys from %s", len(trusted.keys), path)

    return {key.sha256: key for key in trusted.keys}


def get_trusted_keys() -> dict[str, TrustedKey]:
    """Get the trust list, reloaded whenever its file changes.

    Returns:
        The trusted keys, keyed by public key fingerprint.

    Raises:
        TrustListError: If the trust list is missing or malformed.
    """

    try:
        return load_trusted_keys()
    # `load_if_changed` calls `os.stat` before the loader runs.
    except OSError as e:
        raise TrustListError(
            f"Trust list {settings.TRUSTED_KEYS_PATH} can't be read: {e}"
        ) from e


def public_key_fingerprint(cert: x509.Certificate) -> str:
    """Get the fingerprint the trust list identifies a key by.

    It is the SHA-256 of the certificate's public key, DER encoded as
    `SubjectPublicKeyInfo`, so every certificate for the same key has the
    same fingerprint. The same value as:
    `openssl x509 -noout -pubkey | openssl pkey -pubin -outform DER | sha256sum`.

    Args:
        cert: The certificate whose public key to fingerprint.

    Returns:
        The fingerprint, as lowercase hex.
    """

    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(spki).hexdigest()


def is_strae_key(
    cert: x509.Certificate, trusted: dict[str, TrustedKey] | None = None
) -> bool:
    """Check whether the certificate's public key is in the trust list.

    The certificate's validity dates are not checked: documents signed before
    a certificate expired, or before a key was retired, must still verify.

    Args:
        cert: The certificate to check.
        trusted: The trust list. Defaults to `get_trusted_keys()` if not given.

    Returns:
        Whether the key is one STRAE signs, or has signed, with.

    Raises:
        TrustListError: If the trust list is missing or malformed.
    """

    if trusted is None:
        trusted = get_trusted_keys()

    return public_key_fingerprint(cert) in trusted


def check_signing_certificate(
    cert: x509.Certificate,
    trusted: dict[str, TrustedKey] | None = None,
    now: datetime | None = None,
) -> None:
    """Check that the certificate can be used to sign now.

    Args:
        cert: The signing certificate.
        trusted: The trust list. Defaults to `get_trusted_keys()` if not given.
        now: The current time. Defaults to the current UTC time if not given.

    Raises:
        SigningError: If the certificate is not yet valid or has expired, the
            trust list can't be loaded, or the key is not in the trust list.
    """

    if now is None:
        now = datetime.now(timezone.utc)

    if now < cert.not_valid_before_utc:
        raise SigningError(
            f"Signing certificate is not valid until "
            f"{cert.not_valid_before_utc.isoformat()}"
        )
    if now > cert.not_valid_after_utc:
        raise SigningError(
            f"Signing certificate expired on {cert.not_valid_after_utc.isoformat()}"
        )

    # A trust list that can't be loaded is a problem with the signing
    # material, so it takes the same, replayable, error path.
    try:
        listed = is_strae_key(cert, trusted)
    except TrustListError as e:
        raise SigningError(str(e)) from e

    if not listed:
        raise SigningError(
            f"Signing key {public_key_fingerprint(cert)} is not in the trust list"
        )


def encode_base64url(data: bytes) -> str:
    """Encode bytes as unpadded base64url, the encoding JSF uses for binary values.

    Args:
        data: The bytes to encode.

    Returns:
        The unpadded base64url string.
    """

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


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
    return [encode_base64url(der_bytes)]


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

    return encode_base64url(raw_signature)


def sign_report(report: Dict) -> Dict:
    """
    Sign the given CycloneDX report using ES256.

    Args:
        report (dict): The CycloneDX report to be signed.

    Returns:
        dict: The signed CycloneDX report with the signature added.

    Raises:
        SigningError: If the signing material can't be used to sign (see
            `validate_signing_material` and `check_signing_certificate`).
    """

    logger.debug("Starting report signing")

    report = copy.deepcopy(report)

    private_key = get_private_key()
    cert = get_certificate()

    validate_signing_material(key=private_key, cert=cert)
    check_signing_certificate(cert)

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

    Python's decoder ignores characters outside the alphabet, so the result is
    encoded again and must match `value`. This rejects anything but the one
    encoding of the bytes: other characters, padding, and standard base64.

    Args:
        value: The unpadded base64url string.

    Returns:
        The decoded bytes.

    Raises:
        ValueError: If `value` is not unpadded base64url.
    """

    padding = "=" * (-len(value) % 4)
    decoded = base64.urlsafe_b64decode(value + padding)

    if encode_base64url(decoded) != value:
        raise ValueError("Not unpadded base64url")

    return decoded


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
        public_key.verify(encode_dss_signature(r, s), data, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as e:
        raise SignatureVerificationError("Signature does not match") from e


def load_signer_certificate(report: Dict) -> x509.Certificate:
    """Load the first certificate of the report's `signature.certificatePath`.

    Args:
        report: The signed report.

    Returns:
        The signer's certificate.

    Raises:
        SignatureVerificationError: If the report has no certificate, or it
            can't be parsed.
    """

    signature = report.get("signature")
    cert_path = (
        signature.get("certificatePath") if isinstance(signature, dict) else None
    )
    if not isinstance(cert_path, list) or not cert_path:
        raise SignatureVerificationError("Signature has no certificate")

    try:
        return x509.load_der_x509_certificate(decode_base64url(cert_path[0]))
    except (TypeError, ValueError) as e:
        raise SignatureVerificationError(f"Invalid signing certificate: {e}") from e


def verify_signature(report: Dict) -> x509.Certificate:
    """
    Verify the ES256 signature of a CycloneDX report signed by `sign_report`.

    The signature is checked against the public key of the first
    certificate in `signature.certificatePath`, over the RFC8785 canonical
    JSON of the report without `signature.value`. This checks integrity
    only: use `verify_report` to also check who signed it.

    Args:
        report (dict): The signed CycloneDX report.

    Returns:
        The signer's certificate.

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

    cert = load_signer_certificate(report)

    public_key = cert.public_key()
    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise SignatureVerificationError("Signing certificate is not an EC key")

    # Canonicalize JSON (RFC8785), without the signature value, as when signing.
    # Python's JSON parser accepts NaN and Infinity, but RFC8785 does not.
    try:
        canonical_json = jcs.canonicalize(report)
    except ValueError as e:
        raise SignatureVerificationError(f"Report cannot be canonicalized: {e}") from e

    verify_data(public_key, canonical_json, signature_value)

    logger.debug("Report signature verified successfully")

    return cert


def verify_report(report: Dict) -> bool:
    """
    Verify the signature of a CycloneDX report, and check who signed it.

    The signature is checked first (see `verify_signature`), and only then is
    the signer's public key looked up in the trust list, so the result refers
    to the actual signer. The certificate's validity dates are not checked:
    documents signed before a certificate expired must still verify.

    Args:
        report (dict): The signed CycloneDX report.

    Returns:
        Whether the report is signed with a key in the trust list, i.e. by
        CoEvolution. A valid signature from any other key returns `False`.

    Raises:
        SignatureVerificationError: If the signature is missing, malformed or
            invalid.
        TrustListError: If the trust list is missing or malformed.
    """

    cert = verify_signature(report)

    return is_strae_key(cert)
