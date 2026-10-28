from typing import Dict

from pydantic import BaseModel, Field


class ReportSavedResponse(BaseModel):
    detail: str
    id: str = Field(..., min_length=1)
    report_name: str = Field(..., min_length=1)
    model_uuid: str = Field(..., min_length=1)
    model_version: str = Field(..., min_length=1)


class AIMBOMGeneratedResponse(BaseModel):
    detail: str
    aimbom_uuid: str = Field(..., min_length=1)
    aimbom_version: int = Field(..., ge=1)
    model_uuid: str = Field(..., min_length=1)
    model_version: str = Field(..., min_length=1)


class SignedReportResponse(BaseModel):
    detail: str
    model_uuid: str = Field(..., min_length=1)
    model_version: str = Field(..., min_length=1)
    filename: str = Field(..., min_length=1)
    pool: str = Field(..., min_length=1)
    bucket: str = Field(..., min_length=1)


class StatusResponse(BaseModel):
    status: str
    version: str
