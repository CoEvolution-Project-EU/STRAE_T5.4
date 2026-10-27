import pytest
from app.models.requests import GenerationMetadata
from app.utils.utils import ReportType
from pydantic import ValidationError


def _all_reports():
    return {
        report_type.value: {"download_url": f"reports/x/1.0/{report_type.value}.json"}
        for report_type in ReportType
    }


def test_new_generation_metadata_with_all_reports_is_valid():
    GenerationMetadata(reports=_all_reports())


def test_new_generation_metadata_missing_one_report_is_invalid():
    reports = _all_reports()
    del reports["aimodelinfo_report"]

    with pytest.raises(ValidationError, match="aimodelinfo_report"):
        GenerationMetadata(reports=reports)


def test_new_generation_metadata_missing_all_reports_is_invalid():
    with pytest.raises(ValidationError) as exc_info:
        GenerationMetadata(reports={})

    for report_type in ReportType:
        assert report_type.value in str(exc_info.value)


def test_update_metadata_with_all_updatable_reports_is_valid():
    GenerationMetadata(
        previous_aimbom={"download_url": "aimboms/x/1.0/aimbom.json"},
        reports={
            "assessment_report": {"download_url": "reports/x/1.0/a.json"},
            "risk_report": {"download_url": "reports/x/1.0/r.json"},
        },
    )


def test_update_metadata_with_optional_gadgets_report_is_valid():
    metadata = GenerationMetadata(
        previous_aimbom={"download_url": "aimboms/x/1.0/aimbom.json"},
        reports={
            "assessment_report": {"download_url": "reports/x/1.0/a.json"},
            "risk_report": {"download_url": "reports/x/1.0/r.json"},
            "gadgets_report": {"download_url": "reports/x/1.0/g.json"},
        },
    )

    assert metadata.reports.gadgets_report is not None


def test_update_metadata_with_only_gadgets_report_is_invalid():
    # The gadgets report is optional, but it doesn't replace the required ones.
    with pytest.raises(ValidationError) as exc_info:
        GenerationMetadata(
            previous_aimbom={"download_url": "aimboms/x/1.0/aimbom.json"},
            reports={
                "gadgets_report": {"download_url": "reports/x/1.0/g.json"},
            },
        )

    assert "assessment_report" in str(exc_info.value)
    assert "risk_report" in str(exc_info.value)


def test_update_metadata_missing_assessment_report_is_invalid():
    with pytest.raises(ValidationError, match="assessment_report"):
        GenerationMetadata(
            previous_aimbom={"download_url": "aimboms/x/1.0/aimbom.json"},
            reports={
                "risk_report": {"download_url": "reports/x/1.0/r.json"},
            },
        )


def test_update_metadata_missing_risk_report_is_invalid():
    with pytest.raises(ValidationError, match="risk_report"):
        GenerationMetadata(
            previous_aimbom={"download_url": "aimboms/x/1.0/aimbom.json"},
            reports={
                "assessment_report": {"download_url": "reports/x/1.0/a.json"},
            },
        )


def test_update_metadata_missing_both_updatable_reports_is_invalid():
    with pytest.raises(ValidationError) as exc_info:
        GenerationMetadata(
            previous_aimbom={"download_url": "aimboms/x/1.0/aimbom.json"},
            reports={},
        )

    assert "assessment_report" in str(exc_info.value)
    assert "risk_report" in str(exc_info.value)


def test_update_metadata_with_extra_non_updatable_report_is_invalid():
    with pytest.raises(ValidationError, match="defence_report"):
        GenerationMetadata(
            previous_aimbom={"download_url": "aimboms/x/1.0/aimbom.json"},
            reports={
                "assessment_report": {"download_url": "reports/x/1.0/a.json"},
                "risk_report": {"download_url": "reports/x/1.0/r.json"},
                "defence_report": {"download_url": "reports/x/1.0/d.json"},
            },
        )


@pytest.mark.parametrize(
    "report_type",
    [
        report_type
        for report_type in ReportType
        if report_type
        not in (ReportType.ASSESSMENTS, ReportType.RISK_REPORT, ReportType.GADGETS)
    ],
)
def test_update_metadata_with_any_non_updatable_report_is_invalid(report_type):
    with pytest.raises(ValidationError, match=report_type.value):
        GenerationMetadata(
            previous_aimbom={"download_url": "aimboms/x/1.0/aimbom.json"},
            reports={
                "assessment_report": {"download_url": "reports/x/1.0/a.json"},
                "risk_report": {"download_url": "reports/x/1.0/r.json"},
                "gadgets_report": {"download_url": "reports/x/1.0/g.json"},
                report_type.value: {"download_url": "reports/x/1.0/x.json"},
            },
        )


def test_reports_with_unknown_key_is_invalid():
    # A misspelled report key must be rejected rather than silently dropped.
    with pytest.raises(ValidationError, match="gadget_report"):
        GenerationMetadata(
            previous_aimbom={"download_url": "aimboms/x/1.0/aimbom.json"},
            reports={
                "assessment_report": {"download_url": "reports/x/1.0/a.json"},
                "risk_report": {"download_url": "reports/x/1.0/r.json"},
                "gadget_report": {"download_url": "reports/x/1.0/g.json"},
            },
        )
