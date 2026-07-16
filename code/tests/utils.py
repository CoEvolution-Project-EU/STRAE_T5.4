import json
from pathlib import Path

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

    seed_report(db, "aimbom-aimodelinfo.json", "aimodelinfo_report.json")
    seed_report(db, "aimbom-assessments.json", "assessment_report.json")
    seed_report(db, "aimbom-datasets.json", "datasets_report.json")
    seed_report(db, "aimbom-defences.json", "defence_report.json")
    seed_report(db, "aimbom-euaiact.json", "euaiact_report.json")
    seed_report(db, "aimbom-gadgets.json", "gadgets_report.json")
    seed_report(db, "aimbom-riskreport.json", "risk_report.json")

    return db


def get_generation_metadata():
    return {
        "risk_report": {
            "download_url": f"reports/{MODEL_UUID}/{MODEL_VERSION}/risk_report.json",
        },
        "assessment_report": {
            "download_url": f"reports/{MODEL_UUID}/{MODEL_VERSION}/assessment_report.json",
        },
        "defence_report": {
            "download_url": f"reports/{MODEL_UUID}/{MODEL_VERSION}/defence_report.json",
        },
        "gadgets_report": {
            "download_url": f"reports/{MODEL_UUID}/{MODEL_VERSION}/gadgets_report.json",
        },
        "aimodelinfo_report": {
            "download_url": f"reports/{MODEL_UUID}/{MODEL_VERSION}/aimodelinfo_report.json",
        },
        "euaiact_report": {
            "download_url": f"reports/{MODEL_UUID}/{MODEL_VERSION}/euaiact_report.json",
        },
        "datasets_report": {
            "download_url": f"reports/{MODEL_UUID}/{MODEL_VERSION}/datasets_report.json",
        },
    }
