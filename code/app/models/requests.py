from datetime import datetime

from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self

from app.utils.utils import UPDATABLE_REPORT_TYPES, ReportType


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


class GenerationMetadata(BaseModel):
    previous_aimbom: ReportDetails | None = None
    reports: Reports

    @model_validator(mode="after")
    def _check_required_reports_present(self) -> Self:
        """Ensure the reports required for this request's mode are present.

        - New generation (`previous_aimbom` is `None`): the generator builds
          the AIMBOM from scratch, so every report type must be present.
        - Update (`previous_aimbom` set): the generator only recomputes the
          reports in `UPDATABLE_REPORT_TYPES` (currently the assessment and
          risk reports) and carries the rest over from the previous AIMBOM
          unchanged, so only those need be present.
        """

        if self.previous_aimbom is None:
            required_report_types = tuple(ReportType)
            mode = "previous_aimbom is not set"
        else:
            required_report_types = UPDATABLE_REPORT_TYPES
            mode = "previous_aimbom is set"

        missing = [
            report_type.value
            for report_type in required_report_types
            if getattr(self.reports, report_type.value) is None
        ]

        if missing:
            raise ValueError(f"reports fields required when {mode}: {missing}")

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
                        "download_url": "aimboms/e6a0d3f2-085a-4a32-8844-454666b293b1/v1.0/4707cbed-e4e7-4550-84bf-5e1e41c49786-v1-tier-3.json"
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
            ]
        }
    }
