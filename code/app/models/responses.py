from typing import Dict

from pydantic import BaseModel, Field


class ReportSavedResponse(BaseModel):
    detail: str
    id: str = Field(..., min_length=1)
    report_name: str = Field(..., min_length=1)
    model_id: str = Field(..., min_length=1)


class AIMBOMGeneratedResponse(BaseModel):
    detail: str
    id: str = Field(..., min_length=1)
    model_id: str = Field(..., min_length=1)


class SignedReportResponse(BaseModel):
    detail: str
    signed_report: Dict


class StatusResponse(BaseModel):
    status: str
    version: str
