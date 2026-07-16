import base64

from app.services.signing import (
    canonicalize_json,
    get_certificate_path,
    get_private_key,
    sign_data,
    sign_report,
)
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey

from tests.utils import REPORTS_DIR, load_json


def test_get_private_key_returns_ec_private_key():
    private_key = get_private_key()

    assert isinstance(private_key, EllipticCurvePrivateKey)
    assert private_key.curve.name == "secp256r1"


def test_get_certificate_path_returns_base64_der():
    certificate_path = get_certificate_path()

    assert isinstance(certificate_path, list)
    assert len(certificate_path) == 1

    der_bytes = base64.b64decode(certificate_path[0])
    assert isinstance(der_bytes, bytes)
    assert len(der_bytes) > 0


def test_canonicalize_json_produces_deterministic_order():
    data = {"b": 1, "a": {"d": 4, "c": 3}}
    canonical = canonicalize_json(data)

    assert canonical == b'{"a":{"c":3,"d":4},"b":1}'


def test_sign_data_returns_raw_es256_signature():
    private_key = get_private_key()
    signature = sign_data(private_key, b"payload")

    decoded = base64.b64decode(signature)

    assert isinstance(signature, str)
    assert len(decoded) == 64


def test_sign_report_adds_signature_and_preserves_report():
    report = load_json(REPORTS_DIR / "aimbom-aimodelinfo.json")
    report["signature"] = {"algorithm": "none", "certificatePath": [], "value": "old"}

    signed_report = sign_report(report)

    assert signed_report is not report
    assert "signature" in signed_report

    signature = signed_report["signature"]
    assert signature["algorithm"] == "ES256"
    assert isinstance(signature["certificatePath"], list)
    assert signature["certificatePath"]
    assert isinstance(signature["value"], str)
    assert base64.b64decode(signature["value"])
    assert signature["value"] != "old"
