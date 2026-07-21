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

from tests.mock_db import MockMinioClient

REPORTS_DIR = Path(__file__).resolve().parent.parent / "data/reports"
AIMBOMS_DIR = Path(__file__).resolve().parent.parent / "data/aimboms"
MODEL_UUID = "4ff2dab7-bffe-414d-88a5-1826b9fea8df"
MODEL_VERSION = "1.0"


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def seed_report(db: MockMinioClient, filename: str, object_name: str):
    data = load_json(REPORTS_DIR / filename)
    db.upload_json(
        "reports",
        f"{MODEL_UUID}/{MODEL_VERSION}/{object_name}",
        data,
    )


def create_empty_mock_minio():
    db = MockMinioClient()
    db.create_bucket("reports")
    db.create_bucket("aimboms")
    return db


def create_new_mock_minio():
    db = create_empty_mock_minio()

    seed_report(db, "aimbom-aimodelinfo.json", f"{ReportType.AI_MODEL_INFO.value}.json")
    seed_report(db, "aimbom-assessments.json", f"{ReportType.ASSESSMENTS.value}.json")
    seed_report(db, "aimbom-datasets.json", f"{ReportType.DATASETS.value}.json")
    seed_report(db, "aimbom-defences.json", f"{ReportType.DEFENCES.value}.json")
    seed_report(db, "aimbom-euaiact.json", f"{ReportType.EU_AI_ACT.value}.json")
    seed_report(db, "aimbom-gadgets.json", f"{ReportType.GADGETS.value}.json")
    seed_report(db, "aimbom-riskreport.json", f"{ReportType.RISK_REPORT.value}.json")

    return db


def get_generation_metadata():
    return {
        f"{ReportType.RISK_REPORT.value}": {
            "download_url": f"reports/{MODEL_UUID}/{MODEL_VERSION}/{ReportType.RISK_REPORT.value}.json",
        },
        f"{ReportType.ASSESSMENTS.value}": {
            "download_url": f"reports/{MODEL_UUID}/{MODEL_VERSION}/{ReportType.ASSESSMENTS.value}.json",
        },
        f"{ReportType.DEFENCES.value}": {
            "download_url": f"reports/{MODEL_UUID}/{MODEL_VERSION}/{ReportType.DEFENCES.value}.json",
        },
        f"{ReportType.GADGETS.value}": {
            "download_url": f"reports/{MODEL_UUID}/{MODEL_VERSION}/{ReportType.GADGETS.value}.json",
        },
        f"{ReportType.AI_MODEL_INFO.value}": {
            "download_url": f"reports/{MODEL_UUID}/{MODEL_VERSION}/{ReportType.AI_MODEL_INFO.value}.json",
        },
        f"{ReportType.EU_AI_ACT.value}": {
            "download_url": f"reports/{MODEL_UUID}/{MODEL_VERSION}/{ReportType.EU_AI_ACT.value}.json",
        },
        f"{ReportType.DATASETS.value}": {
            "download_url": f"reports/{MODEL_UUID}/{MODEL_VERSION}/{ReportType.DATASETS.value}.json",
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


def verify_report(report: dict) -> bool:
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
