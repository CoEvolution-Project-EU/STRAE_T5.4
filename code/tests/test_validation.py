import pytest
from app.services import validation

from tests.utils import AIMBOMS_DIR, load_json


def test_validate_aimbom_accepts_valid_cyclonedx_report():
    report = load_json(AIMBOMS_DIR / "aimbom.json")

    validation.cdx_validate_dict(report)


def test_validate_aimbom_rejects_missing_required_field():
    report = load_json(AIMBOMS_DIR / "aimbom.json")
    report.pop("bomFormat", None)

    with pytest.raises(ValueError, match="CycloneDX validation failed"):
        validation.cdx_validate_dict(report)
