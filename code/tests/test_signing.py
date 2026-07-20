import base64
import copy

import jcs
import pytest
from app.services.signing import (
    get_certificate_path,
    get_private_key,
    sign_data,
    sign_report,
)
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from tests.utils import REPORTS_DIR, load_json

# ====================Helpers====================


def decode_base64url(value: str) -> bytes:
    """Decode unpadded Base64URL."""

    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def verify_es256_signature(
    public_key: ec.EllipticCurvePublicKey,
    data: bytes,
    signature_value: str,
) -> bool:
    raw_signature = decode_base64url(signature_value)

    if len(raw_signature) != 64:
        return False

    r = int.from_bytes(raw_signature[:32], "big")
    s = int.from_bytes(raw_signature[32:], "big")

    der_signature = encode_dss_signature(r, s)

    public_key.verify(
        der_signature,
        data,
        ec.ECDSA(hashes.SHA256()),
    )

    return True


def get_public_key_from_certificate_path(
    certificate_path: list[str],
):
    cert_der = base64.b64decode(certificate_path[0])

    certificate = x509.load_der_x509_certificate(cert_der)

    return certificate.public_key()


# ====================Tests====================


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
    report = load_json(REPORTS_DIR / "aimbom-aimodelinfo.json")
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
    report = load_json(REPORTS_DIR / "aimbom-aimodelinfo.json")

    signed_report = sign_report(report)

    signed_copy = copy.deepcopy(signed_report)

    signature = signed_copy.pop("signature")

    signed_copy["signature"] = {
        "algorithm": signature["algorithm"],
        "certificatePath": signature["certificatePath"],
    }

    canonical = jcs.canonicalize(signed_copy)

    public_key = get_public_key_from_certificate_path(signature["certificatePath"])

    assert verify_es256_signature(
        public_key,
        canonical,
        signature["value"],
    )


def test_modified_report_fails_signature_verification():
    report = load_json(REPORTS_DIR / "aimbom-aimodelinfo.json")

    signed_report = sign_report(report)

    signed_copy = copy.deepcopy(signed_report)

    signed_copy["metadata"] = "tampered"

    signature = signed_copy.pop("signature")

    signed_copy["signature"] = {
        "algorithm": signature["algorithm"],
        "certificatePath": signature["certificatePath"],
    }

    canonical = jcs.canonicalize(signed_copy)

    public_key = get_public_key_from_certificate_path(signature["certificatePath"])

    with pytest.raises(InvalidSignature):
        verify_es256_signature(
            public_key,
            canonical,
            signature["value"],
        )
