from typing import Any, Literal, Union

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


class ErrorResponse(BaseModel):
    """Body of an error response."""

    detail: str = Field(..., description="Human-readable description of the error.")


class ValidationErrorItem(BaseModel):
    loc: list[Union[str, int]]
    msg: str
    type: str
    input: Any = None


class UnprocessableEntityResponse(BaseModel):
    """Body of a 422 response.

    `detail` is a list of errors when the request itself fails validation,
    and a string when a report or AIMBOM it refers to is invalid.
    """

    detail: Union[str, list[ValidationErrorItem]]
