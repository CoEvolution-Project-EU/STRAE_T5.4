from datetime import datetime

from pydantic import BaseModel, Field


class ReportDetails(BaseModel):
    id: str = Field(alias="_id")
    bucket: str
    filename: str
    download_url: str
    createdAt: datetime


class ReportsMetadata(BaseModel):
    risk_report: ReportDetails
    assessment_report: ReportDetails
    defence_report: ReportDetails
    gadgets_report: ReportDetails
    aimodelinfo_report: ReportDetails
    euaiact_report: ReportDetails
    datasets_report: ReportDetails
