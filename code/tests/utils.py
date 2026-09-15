import base64
import copy
import json
from pathlib import Path

import jcs
from app.utils.utils import ReportType
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from tests.mock_storage import MockStorageClient

REPORTS_DIR = Path(__file__).resolve().parent.parent / "data/reports"
AIMBOMS_DIR = Path(__file__).resolve().parent.parent / "data/aimboms"
MODEL_UUID = "4ff2dab7-bffe-414d-88a5-1826b9fea8df"
MODEL_VERSION = "1.0"


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_url_for_report_type(
    model_uuid: str, model_version: str, report_type: ReportType
):
    return f"reports/{model_uuid}/{model_version}/{report_type.value}.json"


def create_empty_mock_storage():
    storage = MockStorageClient()
    return storage


def create_new_mock_storage():
    storage = create_empty_mock_storage()

    for report_type in ReportType:
        storage.data[
            get_url_for_report_type(MODEL_UUID, MODEL_VERSION, report_type)
        ] = load_json(REPORTS_DIR / f"{report_type.value}.json")

    storage.data[
        f"reports/{MODEL_UUID}/{MODEL_VERSION}/assessment_report_updated.json"
    ] = load_json(REPORTS_DIR / "assessment_report_updated.json")

    storage.data[f"aimboms/{MODEL_UUID}/{MODEL_VERSION}/aimbom.json"] = load_json(
        AIMBOMS_DIR / "aimbom.json"
    )

    return storage


def get_generation_metadata(model_uuid: str, model_version: str):
    reports = {
        report_type.value: {
            "download_url": get_url_for_report_type(
                model_uuid, model_version, report_type
            )
        }
        for report_type in ReportType
    }

    return {"previous_aimbom": None, "reports": reports}


def get_generation_metadata_deprecation(model_uuid: str, model_version: str):

    return {
        "previous_aimbom": {
            "download_url": f"aimboms/{model_uuid}/{model_version}/aimbom.json"
        },
        "reports": {
            "assessment_report": {
                "download_url": f"reports/{model_uuid}/{model_version}/assessment_report_updated.json"
            },
        },
    }


# ============Signing utility functions for tests============


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
) -> ec.EllipticCurvePublicKey:
    cert_der = base64.b64decode(certificate_path[0])

    certificate = x509.load_der_x509_certificate(cert_der)

    return certificate.public_key()


def verify_signature(report: dict) -> bool:
    report = copy.deepcopy(report)

    signature = report["signature"]

    signature_value = signature.pop("value")

    public_key = get_public_key_from_certificate_path(signature["certificatePath"])

    data = jcs.canonicalize(report)

    return verify_es256_signature(
        public_key,
        data,
        signature_value,
    )
