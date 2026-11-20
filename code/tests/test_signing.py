import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from app.core.config import settings
from app.models.trusted_keys import TrustedKeys
from app.services.signing import (
    SignatureVerificationError,
    SigningError,
    TrustListError,
    check_signing_certificate,
    decode_base64url,
    encode_base64url,
    get_certificate,
    get_certificate_path,
    get_trusted_keys,
    is_strae_key,
    load_if_changed,
    load_trusted_keys,
    public_key_fingerprint,
    sign_report,
    validate_signing_material,
    verify_report,
    verify_signature,
)
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.x509.oid import NameOID
from pydantic import ValidationError

from tests.signing_utils import (
    example_key,
    expired_example_certificate,
    make_certificate,
    sign_with,
    sign_with_foreign_key,
    trust_list,
)
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
    # The specification's key is not STRAE's, so only integrity is checked.
    verify_signature(load_json(JSF_DIR / "p256_es256_certificate_path.json"))


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


# ============ Signing certificate checks ============

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _certificate(not_valid_before, not_valid_after):
    return make_certificate(
        example_key(),
        not_valid_before=not_valid_before,
        not_valid_after=not_valid_after,
    )


def test_check_signing_certificate_rejects_expired_certificate():
    cert = _certificate(NOW - timedelta(days=10), NOW - timedelta(days=1))

    with pytest.raises(SigningError, match="expired on 2029-12-31"):
        check_signing_certificate(cert, trusted=trust_list(cert), now=NOW)


def test_check_signing_certificate_rejects_not_yet_valid_certificate():
    cert = _certificate(NOW + timedelta(days=1), NOW + timedelta(days=10))

    with pytest.raises(SigningError, match="not valid until 2030-01-02"):
        check_signing_certificate(cert, trusted=trust_list(cert), now=NOW)


def test_check_signing_certificate_rejects_unlisted_key():
    cert = _certificate(NOW - timedelta(days=1), NOW + timedelta(days=1))
    other_key = ec.generate_private_key(ec.SECP256R1())
    trusted = trust_list(make_certificate(other_key))

    with pytest.raises(SigningError, match=public_key_fingerprint(cert)):
        check_signing_certificate(cert, trusted=trusted, now=NOW)


def test_check_signing_certificate_turns_trust_list_error_into_signing_error():
    with patch(
        "app.services.signing.get_trusted_keys",
        side_effect=TrustListError("Trust list x can't be read"),
    ):
        with pytest.raises(SigningError, match="can't be read"):
            check_signing_certificate(get_certificate())


# ============ Verifying who signed ============


def test_verify_report_returns_false_for_unknown_key():
    report = sign_with_foreign_key(load_json(REPORTS_DIR / "risk_report.json"))

    assert verify_report(report) is False


def test_verify_report_accepts_expired_certificate_for_listed_key():
    report = sign_with(
        load_json(REPORTS_DIR / "risk_report.json"),
        example_key(),
        expired_example_certificate(),
    )

    assert verify_report(report) is True


def test_is_strae_key_rejects_key_with_empty_list():
    assert is_strae_key(get_certificate(), trusted={}) is False


# ============ Trust list ============


def _entry(sha256):
    return {"sha256": sha256, "in_use_from": "2026-01-01T00:00:00Z"}


def test_trust_list_normalizes_openssl_style_fingerprint():
    fingerprint = public_key_fingerprint(get_certificate())
    with_colons = ":".join(
        fingerprint[i : i + 2] for i in range(0, len(fingerprint), 2)
    ).upper()

    trusted = TrustedKeys.model_validate({"keys": [_entry(with_colons)]})

    assert trusted.keys[0].sha256 == fingerprint


@pytest.mark.parametrize("sha256", ["z" * 64, "a" * 63])
def test_trust_list_rejects_malformed_fingerprint(sha256):
    with pytest.raises(ValidationError, match="64 hex"):
        TrustedKeys.model_validate({"keys": [_entry(sha256)]})


def test_trust_list_rejects_duplicate_fingerprint():
    with pytest.raises(ValidationError, match="Duplicate"):
        TrustedKeys.model_validate({"keys": [_entry("a" * 64), _entry("A" * 64)]})


def test_get_trusted_keys_raises_trust_list_error_when_file_is_missing():
    # `load_if_changed` stats the file before the loader runs.
    with patch(
        "app.services.signing.load_trusted_keys",
        side_effect=FileNotFoundError("No such file"),
    ):
        with pytest.raises(TrustListError, match="can't be read"):
            get_trusted_keys()


@pytest.mark.parametrize("content", ["not json", '{"keys": [{"sha256": "abc"}]}'])
def test_load_trusted_keys_raises_trust_list_error_when_file_is_malformed(
    tmp_path, content
):
    path = tmp_path / "trusted-keys.json"
    path.write_text(content)

    # The watched path is bound at import time, but the loader reads the
    # path from the settings, so the undecorated loader can be pointed at it.
    with patch.object(settings, "TRUSTED_KEYS_PATH", str(path)):
        with pytest.raises(TrustListError, match="is invalid"):
            load_trusted_keys.__wrapped__()
