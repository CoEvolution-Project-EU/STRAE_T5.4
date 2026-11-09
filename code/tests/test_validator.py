import pytest
from app.services.validator import (
    ValidatorLinkValidationError,
    check_links,
    validate_report,
    validate_reports,
)
from app.utils.utils import REPORT_TYPES, BOMType, ReportType

from tests.utils import AIMBOMS_DIR, REPORTS_DIR, load_json


def load_aimbom():
    return validate_report(BOMType.AIMBOM, load_json(AIMBOMS_DIR / "aimbom.json"))


def load_reports():
    return validate_reports(
        {
            report_type.value: load_json(REPORTS_DIR / f"{report_type.value}.json")
            for report_type in REPORT_TYPES
        },
        REPORT_TYPES,
    )


def test_check_links_accepts_matching_references():
    check_links(load_aimbom(), load_reports())


def test_check_links_rejects_unknown_report_type():
    aimbom = load_aimbom()
    aimbom.external_references[0].comment = "Unknown Report"

    with pytest.raises(ValidatorLinkValidationError, match="unknown report type"):
        check_links(aimbom, load_reports())


def test_check_links_rejects_duplicate_reference():
    aimbom = load_aimbom()
    aimbom.external_references.append(aimbom.external_references[0])

    with pytest.raises(ValidatorLinkValidationError, match="more than once"):
        check_links(aimbom, load_reports())


def test_check_links_rejects_missing_report():
    reports = load_reports()
    del reports[ReportType.RISK_REPORT]

    with pytest.raises(
        ValidatorLinkValidationError, match="risk_report, but it is missing"
    ):
        check_links(load_aimbom(), reports)


def test_check_links_rejects_unreferenced_report():
    aimbom = load_aimbom()
    aimbom.external_references = [
        ref for ref in aimbom.external_references if ref.comment != "Risk Assessment"
    ]

    with pytest.raises(
        ValidatorLinkValidationError, match="does not reference risk_report"
    ):
        check_links(aimbom, load_reports())


def test_check_links_rejects_wrong_report_version():
    reports = load_reports()
    reports[ReportType.RISK_REPORT].version = 2

    with pytest.raises(ValidatorLinkValidationError, match="risk_report as"):
        check_links(load_aimbom(), reports)


def test_check_links_rejects_wrong_report_serial_number():
    reports = load_reports()
    reports[
        ReportType.RISK_REPORT
    ].serial_number = "urn:uuid:00000000-0000-0000-0000-000000000000"

    with pytest.raises(ValidatorLinkValidationError, match="risk_report as"):
        check_links(load_aimbom(), reports)
