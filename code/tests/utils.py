import json
from pathlib import Path

from tests.mock_db import MockMinioDB


def get_model_info():
    model_info = {
        "component": {
            "type": "machine-learning-model",
            "name": "Projected LiDAR Range-Image Semantic Segmentation Model",
            "version": "1.4.0",
            "description": "Deep-learning semantic segmentation model that ingests projected LiDAR range images and outputs dense semantic labels (class logits/masks) for 3D scene understanding in autonomous/robotic perception pipelines.",
            "supplier": {"name": "AviSense.AI"},
            "hashes": [
                {
                    "alg": "SHA-256",
                    "content": "6fce8a2c0b7a31c21db94c76fd43b1c4f0f16fabc4e7e984f3e9b82c50a2f3ab",
                }
            ],
            "licenses": [{"license": {"id": "Apache-2.0"}}],
            "purl": "pkg:mlmodel/avisense/lidarguard@1.4.0",
        },
        "authors": [{"name": "Alexandros Gkillas", "organization": "AviSense.AI"}],
    }
    return model_info


REPORTS_DIR = Path(__file__).resolve().parent.parent / "data/reports"


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def seed_report(db, filename, object_name):
    data = load_json(REPORTS_DIR / filename)
    db.upload_json(
        "reports",
        f"4ff2dab7-bffe-414d-88a5-1826b9fea8df/{object_name}",
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
    seed_report(db, "aimbom-euaiact.json", "euaiact.json")
    seed_report(db, "aimbom-gadgets.json", "gadgets.json")

    return db
