import base64
import os
from datetime import datetime, timedelta, timezone

import pytest
from app.services.signing import (
    get_certificate_path,
    get_private_key,
    load_if_changed,
    sign_data,
    sign_report,
)
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from tests.utils import (
    REPORTS_DIR,
    decode_base64url,
    load_json,
    verify_signature,
)


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


def test_get_certificate_path_returns_base64_der():
    certificate_path = get_certificate_path()

    assert isinstance(certificate_path, list)
    assert len(certificate_path) == 1

    der_bytes = base64.b64decode(certificate_path[0])
    assert isinstance(der_bytes, bytes)
    assert len(der_bytes) > 0


def test_sign_data_returns_raw_es256_signature():
    private_key = get_private_key()
    signature = sign_data(private_key, b"payload")

    decoded = decode_base64url(signature)

    assert isinstance(signature, str)
    assert len(decoded) == 64


def test_sign_report_adds_signature_and_preserves_report():
    report = load_json(REPORTS_DIR / "aimodelinfo_report.json")
    report["signature"] = {
        "algorithm": "none",
        "certificatePath": [],
        "value": "old",
    }

    signed_report = sign_report(report)

    assert signed_report is not report
    assert "signature" in signed_report

    signature = signed_report["signature"]

    assert signature["algorithm"] == "ES256"
    assert isinstance(signature["certificatePath"], list)
    assert signature["certificatePath"]
    assert isinstance(signature["value"], str)

    decoded_signature = decode_base64url(signature["value"])

    assert len(decoded_signature) == 64
    assert signature["value"] != "old"


def test_sign_report_signature_valid():
    report = load_json(REPORTS_DIR / "aimodelinfo_report.json")

    signed_report = sign_report(report)

    assert verify_signature(signed_report) is True


def test_modified_report_fails_signature_verification():
    report = load_json(REPORTS_DIR / "aimodelinfo_report.json")

    signed_report = sign_report(report)

    signed_report["metadata"] = "tampered"

    with pytest.raises(InvalidSignature):
        verify_signature(signed_report)


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


def test_load_if_changed_cache_clear_forces_reload(tmp_path):
    path = tmp_path / "value.txt"
    path.write_text("v1")
    calls = []

    @load_if_changed(path=str(path))
    def load():
        calls.append(1)
        return path.read_text()

    load()
    load()
    assert len(calls) == 1

    load.cache_clear()
    load()

    assert len(calls) == 2


def test_decorated_private_key_and_certificate_reload_on_rotation(tmp_path):
    """End-to-end version of the reload tests above, using real PEM key/cert
    loading (mirroring get_private_key/get_certificate's own bodies) instead
    of a dummy string loader."""

    private_key, key_bytes, cert_bytes = _generate_key_and_cert_bytes()
    key_path = tmp_path / "key.pem"
    cert_path = tmp_path / "cert.pem"
    key_path.write_bytes(key_bytes)
    cert_path.write_bytes(cert_bytes)

    @load_if_changed(path=str(key_path))
    def load_key():
        with open(key_path, "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)

    @load_if_changed(path=str(cert_path))
    def load_cert():
        with open(cert_path, "rb") as f:
            return x509.load_pem_x509_certificate(f.read())

    loaded_key = load_key()
    loaded_cert = load_cert()

    assert loaded_key.private_numbers() == private_key.private_numbers()
    assert load_key() is loaded_key
    assert load_cert() is loaded_cert

    new_key, new_key_bytes, new_cert_bytes = _generate_key_and_cert_bytes()
    key_path.write_bytes(new_key_bytes)
    cert_path.write_bytes(new_cert_bytes)
    _bump_mtime(key_path)
    _bump_mtime(cert_path)

    reloaded_key = load_key()
    reloaded_cert = load_cert()

    assert reloaded_key is not loaded_key
    assert reloaded_key.private_numbers() == new_key.private_numbers()
    assert reloaded_cert is not loaded_cert
    assert reloaded_cert.public_bytes(
        serialization.Encoding.DER
    ) == x509.load_pem_x509_certificate(new_cert_bytes).public_bytes(
        serialization.Encoding.DER
    )
