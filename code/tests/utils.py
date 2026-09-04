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


def create_empty_mock_storage():
    storage = MockStorageClient()
    return storage


def create_new_mock_storage():
    storage = create_empty_mock_storage()

    storage.reports[(MODEL_UUID, MODEL_VERSION)] = {
        ReportType.AI_MODEL_INFO.value: load_json(
            REPORTS_DIR / "aimbom-aimodelinfo.json"
        ),
        ReportType.DATASETS.value: load_json(REPORTS_DIR / "aimbom-datasets.json"),
        ReportType.ASSESSMENTS.value: load_json(
            REPORTS_DIR / "aimbom-assessments.json"
        ),
        ReportType.DEFENCES.value: load_json(REPORTS_DIR / "aimbom-defences.json"),
        ReportType.EU_AI_ACT.value: load_json(REPORTS_DIR / "aimbom-euaiact.json"),
        ReportType.GADGETS.value: load_json(REPORTS_DIR / "aimbom-gadgets.json"),
        ReportType.RISK_REPORT.value: load_json(REPORTS_DIR / "aimbom-riskreport.json"),
    }

    return storage


def get_generation_metadata(model_uuid: str, model_version: str):
    return {
        "previous_aimbom": None,
        "reports": {
            ReportType.RISK_REPORT.value: {
                "download_url": f"reports/{model_uuid}/{model_version}/{ReportType.RISK_REPORT.value}.json",
            },
            ReportType.ASSESSMENTS.value: {
                "download_url": f"reports/{model_uuid}/{model_version}/{ReportType.ASSESSMENTS.value}.json",
            },
            ReportType.DEFENCES.value: {
                "download_url": f"reports/{model_uuid}/{model_version}/{ReportType.DEFENCES.value}.json",
            },
            ReportType.GADGETS.value: {
                "download_url": f"reports/{model_uuid}/{model_version}/{ReportType.GADGETS.value}.json",
            },
            ReportType.AI_MODEL_INFO.value: {
                "download_url": f"reports/{model_uuid}/{model_version}/{ReportType.AI_MODEL_INFO.value}.json",
            },
            ReportType.EU_AI_ACT.value: {
                "download_url": f"reports/{model_uuid}/{model_version}/{ReportType.EU_AI_ACT.value}.json",
            },
            ReportType.DATASETS.value: {
                "download_url": f"reports/{model_uuid}/{model_version}/{ReportType.DATASETS.value}.json",
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
