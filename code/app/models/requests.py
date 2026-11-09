from datetime import datetime

from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self

from app.utils.utils import (
    ALLOWED_UPDATED_REPORT_SETS,
    REPORT_TYPES,
    UPDATABLE_REPORT_TYPES,
)


class ReportDetails(BaseModel):
    id: str | None = Field(None, alias="_id")
    bucket: str | None = None
    filename: str = Field(..., min_length=1)
    download_url: str = Field(..., min_length=1)
    createdAt: datetime | None = None


class Reports(BaseModel):
    risk_report: ReportDetails | None = None
    assessment_report: ReportDetails | None = None
    defence_report: ReportDetails | None = None
    gadgets_report: ReportDetails | None = None
    aimodelinfo_report: ReportDetails | None = None
    euaiact_report: ReportDetails | None = None
    datasets_report: ReportDetails | None = None

    # Reject unknown keys so a misspelled report (e.g. `gadget_report`) fails
    # validation instead of being silently dropped.
    model_config = {"extra": "forbid"}


class GenerationMetadata(BaseModel):
    model_uuid: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    previous_aimbom: ReportDetails | None = None
    reports: Reports

    @model_validator(mode="after")
    def _check_required_reports_present(self) -> Self:
        """Ensure exactly the reports required for this request's mode are present.

        - New generation (`previous_aimbom` is `None`): the generator builds
          the AIMBOM from scratch, so every report type must be present.
        - Update (`previous_aimbom` set): the generator only recomputes the
          changed reports and carries the rest over from the previous AIMBOM
          unchanged. Only the reports in `UPDATABLE_REPORT_TYPES` may change
          (any other report would be fetched but silently ignored downstream,
          so it's rejected here instead), and only in one of the combinations
          in `ALLOWED_UPDATED_REPORT_SETS`:
            1. the assessment and risk reports,
            2. the gadgets report alone, or
            3. all three.
        """

        # If no previous AIMBOM is provided, all report types must be present.
        if self.previous_aimbom is None:
            missing = [
                report_type.value
                for report_type in REPORT_TYPES
                if getattr(self.reports, report_type.value) is None
            ]
            if missing:
                raise ValueError(
                    f"reports fields required when previous_aimbom is not set: {missing}"
                )
            return self

        present = {
            report_type
            for report_type in REPORT_TYPES
            if getattr(self.reports, report_type.value) is not None
        }

        # Non-updatable report types must not be present, as they would be
        # ignored by the generator.
        unexpected = sorted(
            report_type.value
            for report_type in present
            if report_type not in UPDATABLE_REPORT_TYPES
        )
        if unexpected:
            raise ValueError(
                f"reports fields not allowed when previous_aimbom is set: {unexpected}"
            )

        # The updated reports must form one of the allowed combinations.
        if present not in ALLOWED_UPDATED_REPORT_SETS:
            allowed = [
                sorted(report_type.value for report_type in allowed_set)
                for allowed_set in ALLOWED_UPDATED_REPORT_SETS
            ]
            raise ValueError(
                "reports fields when previous_aimbom is set must be one of "
                f"{allowed}, got: {sorted(t.value for t in present)}"
            )

        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "model_uuid": "e6a0d3f2-085a-4a32-8844-454666b293b1",
                    "version": "v1.0",
                    "reports": {
                        "risk_report": {
                            "filename": "risk_report.json",
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/risk_report.json",
                        },
                        "assessment_report": {
                            "filename": "assessment_report.json",
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/assessment_report.json",
                        },
                        "defence_report": {
                            "filename": "defence_report.json",
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/defence_report.json",
                        },
                        "gadgets_report": {
                            "filename": "gadgets_report.json",
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/gadgets_report.json",
                        },
                        "aimodelinfo_report": {
                            "filename": "aimodelinfo_report.json",
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/aimodelinfo_report.json",
                        },
                        "euaiact_report": {
                            "filename": "euaiact_report.json",
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/euaiact_report.json",
                        },
                        "datasets_report": {
                            "filename": "datasets_report.json",
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/datasets_report.json",
                        },
                    },
                },
                {
                    "model_uuid": "e6a0d3f2-085a-4a32-8844-454666b293b1",
                    "version": "v1.0",
                    "previous_aimbom": {
                        "filename": "previous_aimbom.json",
                        "download_url": "aimboms/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/4707cbed-e4e7-4550-84bf-5e1e41c49786-v1.json",
                    },
                    "reports": {
                        "assessment_report": {
                            "filename": "assessment_report_2.json",
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/assessment_report_2.json",
                        },
                        "risk_report": {
                            "filename": "risk_report_2.json",
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/risk_report_2.json",
                        },
                    },
                },
                {
                    "model_uuid": "e6a0d3f2-085a-4a32-8844-454666b293b1",
                    "version": "v1.0",
                    "previous_aimbom": {
                        "filename": "previous_aimbom.json",
                        "download_url": "aimboms/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/4707cbed-e4e7-4550-84bf-5e1e41c49786-v1.json",
                    },
                    "reports": {
                        "assessment_report": {
                            "filename": "assessment_report_2.json",
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/assessment_report_2.json",
                        },
                        "risk_report": {
                            "filename": "risk_report_2.json",
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/risk_report_2.json",
                        },
                        "gadgets_report": {
                            "filename": "gadgets_report_2.json",
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/gadgets_report_2.json",
                        },
                    },
                },
            ]
        }
    }


class SigningFile(ReportDetails):
    # The orchestrator needs the original's ID to accept the signed copy.
    id: str = Field(..., min_length=1, alias="_id")


class SigningMetadata(BaseModel):
    """A signing request, in the format of the `strae_sign_requests` Kafka event.

    `tags` are sent with every signed copy, comma-separated. Other fields of
    the event (`event`, `model_name`, `pool`, ...) are not needed for signing
    and are ignored.
    """

    model_uuid: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    target_pool: str = Field(..., min_length=1)
    target_bucket: str = Field(..., min_length=1)
    tags: list[str] = []
    files: list[SigningFile] = Field(min_length=1)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "model_uuid": "e6a0d3f2-085a-4a32-8844-454666b293b1",
                    "version": "v1.0",
                    "target_pool": "RP",
                    "target_bucket": "user-assessments",
                    "tags": [],
                    "files": [
                        {
                            "_id": "6ae735e37ceea4671026265d",
                            "bucket": "user-assessments",
                            "filename": "user-assessments.json",
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/user-assessments.json",
                        },
                    ],
                }
            ]
        }
    }
