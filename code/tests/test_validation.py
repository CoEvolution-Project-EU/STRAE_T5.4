import pytest
from app.services import cyclonedx_validation

from tests.utils import AIMBOMS_DIR, load_json


def test_validate_aimbom_accepts_valid_cyclonedx_report():
    report = load_json(AIMBOMS_DIR / "aimbom.json")

    cyclonedx_validation.cdx_validate_dict(report)


def test_validate_aimbom_rejects_missing_required_field():
    report = load_json(AIMBOMS_DIR / "aimbom.json")
    report.pop("bomFormat", None)

    with pytest.raises(ValueError, match="CycloneDX validation failed") as exc_info:
        cyclonedx_validation.cdx_validate_dict(report)

    assert "bomFormat" in str(exc_info.value)


def test_validate_aimbom_rejects_siganture():
    report = load_json(AIMBOMS_DIR / "aimbom.json")
    report["signature"]["algorithm"] = "Invalid Alg"

    with pytest.raises(ValueError, match="CycloneDX validation failed") as exc_info:
        cyclonedx_validation.cdx_validate_dict(report)

    assert "signature" in str(exc_info.value)
