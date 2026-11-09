import os
from datetime import datetime, timedelta, timezone

import pytest
from app.core.config import settings
from app.services.signing import (
    SignatureVerificationError,
    SigningError,
    decode_base64url,
    encode_base64url,
    get_certificate_path,
    load_if_changed,
    sign_report,
    validate_signing_material,
    verify_report,
)
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.x509.oid import NameOID

from tests.utils import JSF_DIR, REPORTS_DIR, load_json


def _generate_key_and_cert_bytes(private_key=None):
    """Generate a P-256 key (or use the given one) and a matching self-signed
    certificate, returning their PEM-encoded bytes."""

    private_key = private_key or ec.generate_private_key(ec.SECP256R1())

    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "STRAE Test Signing Certificate")]
    )
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(private_key, hashes.SHA256())
    )

    key_bytes = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    cert_bytes = certificate.public_bytes(serialization.Encoding.PEM)

    return private_key, key_bytes, cert_bytes


def _bump_mtime(path):
    """Force a distinct, later mtime on `path`, regardless of filesystem
    timestamp resolution or how quickly the test writes files."""

    new_mtime = os.stat(path).st_mtime + 5
    os.utime(path, (new_mtime, new_mtime))


def test_get_certificate_path_returns_base64url_der():
    certificate_path = get_certificate_path()

    assert isinstance(certificate_path, list)
    assert len(certificate_path) == 1

    # JSF encodes binary values as unpadded base64url.
    assert not set("+/=") & set(certificate_path[0])

    der_bytes = decode_base64url(certificate_path[0])
    with open(settings.SIGNING_CERTIFICATE_PATH, "rb") as f:
        expected = x509.load_pem_x509_certificate(f.read())
    assert x509.load_der_x509_certificate(der_bytes) == expected


def test_validate_signing_material_raises_signing_error_on_mismatch():
    key, _, _ = _generate_key_and_cert_bytes()
    _, _, other_cert_bytes = _generate_key_and_cert_bytes()
    mismatched_cert = x509.load_pem_x509_certificate(other_cert_bytes)

    with pytest.raises(SigningError, match="do not match"):
        validate_signing_material(key=key, cert=mismatched_cert)


# ============ verify_report ============


def test_verify_report_accepts_signed_report():
    signed_report = sign_report(load_json(REPORTS_DIR / "aimodelinfo_report.json"))

    verify_report(signed_report)


def test_verify_report_rejects_modified_report():
    signed_report = sign_report(load_json(REPORTS_DIR / "aimodelinfo_report.json"))
    signed_report["metadata"] = "tampered"

    with pytest.raises(SignatureVerificationError, match="does not match"):
        verify_report(signed_report)


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_verify_report_rejects_non_finite_number(value):
    report = load_json(REPORTS_DIR / "risk_report.json")
    report["vulnerabilities"][0]["ratings"][0]["score"] = value

    with pytest.raises(SignatureVerificationError, match="canonicalized"):
        verify_report(report)


def test_verify_report_rejects_unsigned_report():
    report = load_json(REPORTS_DIR / "aimodelinfo_report.json")
    report.pop("signature")

    with pytest.raises(SignatureVerificationError, match="not signed"):
        verify_report(report)


def test_verify_report_rejects_unsupported_algorithm():
    signed_report = sign_report(load_json(REPORTS_DIR / "aimodelinfo_report.json"))
    signed_report["signature"]["algorithm"] = "RS256"

    with pytest.raises(SignatureVerificationError, match="Unsupported"):
        verify_report(signed_report)


def test_verify_report_rejects_missing_certificate():
    signed_report = sign_report(load_json(REPORTS_DIR / "aimodelinfo_report.json"))
    signed_report["signature"]["certificatePath"] = []

    with pytest.raises(SignatureVerificationError, match="no certificate"):
        verify_report(signed_report)


def test_verify_report_rejects_signature_from_other_key():
    signed_report = sign_report(load_json(REPORTS_DIR / "aimodelinfo_report.json"))
    _, _, other_cert_bytes = _generate_key_and_cert_bytes()
    other_cert = x509.load_pem_x509_certificate(other_cert_bytes)
    signed_report["signature"]["certificatePath"] = get_certificate_path(other_cert)

    with pytest.raises(SignatureVerificationError, match="does not match"):
        verify_report(signed_report)


def test_verify_report_rejects_der_encoded_signature():
    # A valid signature, but base64url DER instead of base64url raw r||s.
    signed_report = sign_report(load_json(REPORTS_DIR / "aimodelinfo_report.json"))
    raw_signature = decode_base64url(signed_report["signature"]["value"])
    der_signature = encode_dss_signature(
        int.from_bytes(raw_signature[:32], "big"),
        int.from_bytes(raw_signature[32:], "big"),
    )
    signed_report["signature"]["value"] = encode_base64url(der_signature)

    with pytest.raises(SignatureVerificationError, match="must be 64 bytes"):
        verify_report(signed_report)


@pytest.mark.parametrize(
    "value",
    [
        "+/+/",  # Standard base64 alphabet
        "AA==",  # Padding
        "!!!!AAAA",  # Characters outside the alphabet
        "AAAA\n",  # Trailing newline
        "AB",  # Non-zero unused bits: the same byte as "AA"
        "A",  # Impossible length
    ],
)
def test_decode_base64url_rejects_other_encodings(value):
    with pytest.raises(ValueError):
        decode_base64url(value)


def test_verify_report_rejects_junk_in_signature_value():
    signed_report = sign_report(load_json(REPORTS_DIR / "aimodelinfo_report.json"))
    signed_report["signature"]["value"] = "!!!!" + signed_report["signature"]["value"]

    with pytest.raises(SignatureVerificationError, match="not valid base64url"):
        verify_report(signed_report)


def test_verify_report_rejects_certificate_not_in_base64url():
    signed_report = sign_report(load_json(REPORTS_DIR / "aimodelinfo_report.json"))
    certificate = signed_report["signature"]["certificatePath"][0]
    signed_report["signature"]["certificatePath"] = ["!!!!" + certificate]

    with pytest.raises(SignatureVerificationError, match="Invalid signing certificate"):
        verify_report(signed_report)


# ============ JSF specification example ============
#
# `p256#es256@cer.json` from https://cyberphone.github.io/doc/security/jsf.html:
# an ES256 signature with a certificatePath, signed with the specification's
# P-256 test key.


def test_verify_report_accepts_jsf_specification_example():
    verify_report(load_json(JSF_DIR / "p256_es256_certificate_path.json"))


# ============ load_if_changed: hot-reload on file change ============
#
# get_private_key/get_certificate bind their watched path to
# settings.SIGNING_*_PATH once, at decoration (import) time -- matching how
# they're actually used, since that configured path never changes at
# runtime. That means they can't be redirected to a temp file from within a
# test. So these tests exercise `load_if_changed` directly, decorating fresh
# temp-file-backed loaders the same way the real functions are decorated,
# which covers the exact same reload mechanism.


def test_load_if_changed_returns_cached_object_when_file_unchanged(tmp_path):
    path = tmp_path / "value.txt"
    path.write_text("v1")
    calls = []

    @load_if_changed(path=str(path))
    def load():
        calls.append(1)
        return path.read_text()

    first = load()
    second = load()

    assert second is first
    assert len(calls) == 1


def test_load_if_changed_reloads_when_file_changes(tmp_path):
    path = tmp_path / "value.txt"
    path.write_text("v1")

    @load_if_changed(path=str(path))
    def load():
        return path.read_text()

    assert load() == "v1"

    path.write_text("v2")
    _bump_mtime(path)

    assert load() == "v2"
