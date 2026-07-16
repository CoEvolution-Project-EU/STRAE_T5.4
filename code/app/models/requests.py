from datetime import datetime

from pydantic import BaseModel, Field


class ReportDetails(BaseModel):
    id: str | None = Field(None, alias="_id")
    bucket: str | None = None
    filename: str | None = None
    download_url: str
    createdAt: datetime | None = None


class GenerationMetadata(BaseModel):
    risk_report: ReportDetails
    assessment_report: ReportDetails
    defence_report: ReportDetails
    gadgets_report: ReportDetails
    aimodelinfo_report: ReportDetails
    euaiact_report: ReportDetails
    datasets_report: ReportDetails

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
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
                }
            ]
        }
    }
