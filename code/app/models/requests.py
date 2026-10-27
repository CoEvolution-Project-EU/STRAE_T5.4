from datetime import datetime

from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self

from app.utils.utils import (
    OPTIONAL_UPDATABLE_REPORT_TYPES,
    REPORT_TYPES,
    REQUIRED_UPDATABLE_REPORT_TYPES,
)


class ReportDetails(BaseModel):
    id: str | None = Field(None, alias="_id")
    bucket: str | None = None
    filename: str | None = None
    download_url: str
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
    previous_aimbom: ReportDetails | None = None
    reports: Reports

    @model_validator(mode="after")
    def _check_required_reports_present(self) -> Self:
        """Ensure exactly the reports required for this request's mode are present.

        - New generation (`previous_aimbom` is `None`): the generator builds
          the AIMBOM from scratch, so every report type must be present.
        - Update (`previous_aimbom` set): the generator only recomputes the
          changed reports and carries the rest over from the previous AIMBOM
          unchanged. The reports in `REQUIRED_UPDATABLE_REPORT_TYPES`
          (currently the assessment and risk reports) must be present, and
          the reports in `OPTIONAL_UPDATABLE_REPORT_TYPES` (currently the
          gadgets report) may be present. Any other report field would be
          fetched but silently ignored downstream, so it's rejected here
          instead.
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

        # If a previous AIMBOM is provided, the required updatable report types must be present.
        missing = [
            report_type.value
            for report_type in REQUIRED_UPDATABLE_REPORT_TYPES
            if getattr(self.reports, report_type.value) is None
        ]
        if missing:
            raise ValueError(
                f"reports fields required when previous_aimbom is set: {missing}"
            )

        # Optional updatable report types may be present. Any other report types
        # must not be present, as they will be ignored by the generator.
        updatable_types = (
            REQUIRED_UPDATABLE_REPORT_TYPES + OPTIONAL_UPDATABLE_REPORT_TYPES
        )
        unexpected = [
            report_type.value
            for report_type in REPORT_TYPES
            if report_type not in updatable_types
            and getattr(self.reports, report_type.value) is not None
        ]
        if unexpected:
            raise ValueError(
                f"reports fields not allowed when previous_aimbom is set: {unexpected}"
            )

        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "reports": {
                        "risk_report": {
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/risk_report.json",
                        },
                        "assessment_report": {
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/assessment_report.json",
                        },
                        "defence_report": {
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/defence_report.json",
                        },
                        "gadgets_report": {
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/gadgets_report.json",
                        },
                        "aimodelinfo_report": {
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/aimodelinfo_report.json",
                        },
                        "euaiact_report": {
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/euaiact_report.json",
                        },
                        "datasets_report": {
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/datasets_report.json",
                        },
                    },
                },
                {
                    "previous_aimbom": {
                        "download_url": "aimboms/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/4707cbed-e4e7-4550-84bf-5e1e41c49786-v1.json"
                    },
                    "reports": {
                        "assessment_report": {
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/assessment_report_2.json"
                        },
                        "risk_report": {
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/risk_report_2.json"
                        },
                    },
                },
                {
                    "previous_aimbom": {
                        "download_url": "aimboms/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/4707cbed-e4e7-4550-84bf-5e1e41c49786-v1.json"
                    },
                    "reports": {
                        "assessment_report": {
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/assessment_report_2.json"
                        },
                        "risk_report": {
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/risk_report_2.json"
                        },
                        "gadgets_report": {
                            "download_url": "reports/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/gadgets_report_2.json"
                        },
                    },
                },
            ]
        }
    }
