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


class StatusResponse(BaseModel):
    status: str
    version: str
