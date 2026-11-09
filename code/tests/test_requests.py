import pytest
from app.models.requests import GenerationMetadata, SigningMetadata
from app.utils.utils import ReportType
from pydantic import ValidationError

from tests.utils import get_signing_event


def _ids():
    return {"model_uuid": "x", "version": "1.0"}


def test_new_generation_metadata_missing_all_reports_is_invalid():
    with pytest.raises(ValidationError) as exc_info:
        GenerationMetadata(**_ids(), reports={})

    for report_type in ReportType:
        assert report_type.value in str(exc_info.value)


def _update_metadata(*report_types):
    return GenerationMetadata(
        **_ids(),
        previous_aimbom={
            "filename": "aimbom.json",
            "download_url": "aimboms/x/1.0/aimbom.json",
        },
        reports={
            report_type.value: {
                "filename": f"{report_type.value}.json",
                "download_url": f"reports/x/1.0/{report_type.value}.json",
            }
            for report_type in report_types
        },
    )


@pytest.mark.parametrize(
    "report_types",
    [
        (ReportType.ASSESSMENTS, ReportType.RISK_REPORT),
        (ReportType.GADGETS,),
        (ReportType.ASSESSMENTS, ReportType.RISK_REPORT, ReportType.GADGETS),
    ],
)
def test_update_metadata_with_allowed_reports_is_valid(report_types):
    _update_metadata(*report_types)


@pytest.mark.parametrize(
    "report_types",
    [
        (),
        (ReportType.ASSESSMENTS,),
        (ReportType.RISK_REPORT,),
        (ReportType.ASSESSMENTS, ReportType.GADGETS),
        (ReportType.RISK_REPORT, ReportType.GADGETS),
    ],
)
def test_update_metadata_with_disallowed_report_combination_is_invalid(
    report_types,
):
    with pytest.raises(ValidationError, match="must be one of"):
        _update_metadata(*report_types)


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
            **_ids(),
            previous_aimbom={
                "filename": "aimbom.json",
                "download_url": "aimboms/x/1.0/aimbom.json",
            },
            reports={
                "assessment_report": {
                    "filename": "a.json",
                    "download_url": "reports/x/1.0/a.json",
                },
                "risk_report": {
                    "filename": "r.json",
                    "download_url": "reports/x/1.0/r.json",
                },
                "gadgets_report": {
                    "filename": "g.json",
                    "download_url": "reports/x/1.0/g.json",
                },
                report_type.value: {
                    "filename": "x.json",
                    "download_url": "reports/x/1.0/x.json",
                },
            },
        )


def test_reports_with_unknown_key_is_invalid():
    # A misspelled report key must be rejected rather than silently dropped.
    with pytest.raises(ValidationError, match="gadget_report"):
        GenerationMetadata(
            **_ids(),
            previous_aimbom={
                "filename": "aimbom.json",
                "download_url": "aimboms/x/1.0/aimbom.json",
            },
            reports={
                "assessment_report": {
                    "filename": "a.json",
                    "download_url": "reports/x/1.0/a.json",
                },
                "risk_report": {
                    "filename": "r.json",
                    "download_url": "reports/x/1.0/r.json",
                },
                "gadget_report": {
                    "filename": "g.json",
                    "download_url": "reports/x/1.0/g.json",
                },
            },
        )


def test_signing_event_without_files_is_invalid():
    event = get_signing_event()

    with pytest.raises(ValidationError, match="files"):
        SigningMetadata.model_validate(event)


def test_signing_event_without_tags_is_valid():
    event = get_signing_event("reports/a.json")
    del event["tags"]

    assert SigningMetadata.model_validate(event).tags == []


def test_signing_metadata_example_is_valid():
    for example in SigningMetadata.model_json_schema()["examples"]:
        SigningMetadata.model_validate(example)
