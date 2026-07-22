import base64

import pytest
from app.services.signing import (
    get_certificate_path,
    get_private_key,
    sign_data,
    sign_report,
)
from cryptography.exceptions import InvalidSignature

from tests.utils import (
    REPORTS_DIR,
    decode_base64url,
    load_json,
    verify_signature,
)


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

    assert verify_signature(signed_report) is True


def test_modified_report_fails_signature_verification():
    report = load_json(REPORTS_DIR / "aimbom-aimodelinfo.json")

    signed_report = sign_report(report)

    signed_report["metadata"] = "tampered"

    with pytest.raises(InvalidSignature):
        verify_signature(signed_report)
