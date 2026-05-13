import json
from pathlib import Path

from tests.mock_db import MockMinioDB

REPORTS_DIR = Path(__file__).resolve().parent.parent / "data/reports"
AIMBOMS_DIR = Path(__file__).resolve().parent.parent / "data/aimboms"
MODEL_UUID = "4ff2dab7-bffe-414d-88a5-1826b9fea8df"
MODEL_VERSION = "1.0"


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def seed_report(db: MockMinioDB, filename: str, object_name: str):
    data = load_json(REPORTS_DIR / filename)
    db.upload_json(
        "reports",
        f"{MODEL_UUID}/{MODEL_VERSION}/{object_name}",
        data,
    )


def create_empty_mock_minio():
    db = MockMinioDB()
    db.create_bucket("reports")
    db.create_bucket("aimboms")
    return db


def create_new_mock_minio():
    db = create_empty_mock_minio()

    seed_report(db, "aimbom-aimodelinfo.json", "aimodelinfo.json")
    seed_report(db, "aimbom-assessments.json", "assessments.json")
    seed_report(db, "aimbom-datasets.json", "datasets.json")
    seed_report(db, "aimbom-defences.json", "defences.json")
    seed_report(db, "aimbom-euaiact.json", "euaiact.json")
    seed_report(db, "aimbom-gadgets.json", "gadgets.json")
    seed_report(db, "aimbom-riskreport.json", "riskreport.json")

    return db
