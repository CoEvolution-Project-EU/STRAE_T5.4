"""Helpers for tests that need other keys and certificates than the example
signing material, or documents signed by someone other than STRAE."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.core.config import settings
from app.models.trusted_keys import TrustedKey
from app.services import signing
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def example_key() -> ec.EllipticCurvePrivateKey:
    """The example signing key (`SIGNING_PRIVATE_KEY_PATH` in tests)."""

    with open(settings.SIGNING_PRIVATE_KEY_PATH, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def make_certificate(
    key: ec.EllipticCurvePrivateKey,
    not_valid_before: datetime | None = None,
    not_valid_after: datetime | None = None,
) -> x509.Certificate:
    """Issue a self-signed certificate for `key`, valid from a day ago for a
    year unless other dates are given."""

    now = datetime.now(timezone.utc)
    name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "STRAE Test Signing Certificate")]
    )

    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_valid_before or now - timedelta(days=1))
        .not_valid_after(not_valid_after or now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )


def expired_example_certificate() -> x509.Certificate:
    """A certificate for the example key that expired yesterday."""

    now = datetime.now(timezone.utc)
    return make_certificate(
        example_key(),
        not_valid_before=now - timedelta(days=365),
        not_valid_after=now - timedelta(days=1),
    )


def trust_list(*certs: x509.Certificate, retired: bool = False) -> dict:
    """A trust list, as `signing.get_trusted_keys` returns it, holding the
    public key of each certificate."""

    now = datetime.now(timezone.utc)
    entries = [
        TrustedKey(
            sha256=signing.public_key_fingerprint(cert),
            in_use_from=now - timedelta(days=365),
            retired_at=now if retired else None,
        )
        for cert in certs
    ]
    return {entry.sha256: entry for entry in entries}


def sign_with(
    report: dict, key: ec.EllipticCurvePrivateKey, cert: x509.Certificate
) -> dict:
    """Sign `report` with any key and certificate, as someone other than STRAE
    could. The signing checks (dates, trust list) are skipped."""

    with (
        patch("app.services.signing.get_private_key", return_value=key),
        patch("app.services.signing.get_certificate", return_value=cert),
        patch("app.services.signing.check_signing_certificate"),
    ):
        return signing.sign_report(report)


def sign_with_foreign_key(report: dict) -> dict:
    """Sign `report` with a new key that is not in the trust list."""

    key = ec.generate_private_key(ec.SECP256R1())
    return sign_with(report, key, make_certificate(key))
