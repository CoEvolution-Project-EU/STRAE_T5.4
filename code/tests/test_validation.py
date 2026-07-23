import pytest
from app.services import validation

from tests.utils import AIMBOMS_DIR, load_json


def test_validate_aimbom_accepts_valid_cyclonedx_report():
    report = load_json(AIMBOMS_DIR / "aimbom.json")

    validation.cdx_validate_dict(report)


def test_validate_aimbom_rejects_empty_dict():
    with pytest.raises(ValueError, match="CycloneDX validation failed"):
        validation.cdx_validate_dict({})


def test_validate_aimbom_rejects_missing_required_field():
    report = load_json(AIMBOMS_DIR / "aimbom.json")
    report.pop("bomFormat", None)

    with pytest.raises(ValueError, match="CycloneDX validation failed") as exc_info:
        validation.cdx_validate_dict(report)

    assert "bomFormat" in str(exc_info.value)


def test_validate_aimbom_rejects_siganture():
    report = load_json(AIMBOMS_DIR / "aimbom.json")
    report["signature"]["algorithm"] = "Invalid Alg"

    with pytest.raises(ValueError, match="CycloneDX validation failed") as exc_info:
        validation.cdx_validate_dict(report)

    assert "signature" in str(exc_info.value)


def test_validate_aimbom_accepts_siganture():
    report = load_json(AIMBOMS_DIR / "aimbom.json")
    report["signature"]["algorithm"] = "test:test:test"

    validation.cdx_validate_dict(report)
