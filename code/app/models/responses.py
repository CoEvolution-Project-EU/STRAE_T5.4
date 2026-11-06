from typing import Literal

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


class SignedFile(BaseModel):
    original_file_id: str = Field(..., min_length=1)
    filename: str = Field(..., min_length=1)


class SignedReportResponse(BaseModel):
    detail: str
    model_uuid: str = Field(..., min_length=1)
    model_version: str = Field(..., min_length=1)
    target_pool: str = Field(..., min_length=1)
    target_bucket: str = Field(..., min_length=1)
    files: list[SignedFile]
    # Files signed by this request, and files that had already been signed.
    signed: int = Field(..., ge=0)
    already_signed: int = Field(..., ge=0)


class StatusResponse(BaseModel):
    status: str
    version: str


class AIMBOMValidationResponse(BaseModel):
    detail: str
    model_uuid: str = Field(..., min_length=1)
    model_version: str = Field(..., min_length=1)
    status: Literal["VALID", "INVALID"] = Field(
        ..., description="Validation status of the AIMBOM."
    )
