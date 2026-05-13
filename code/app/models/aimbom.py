from datetime import datetime
from enum import Enum
from typing import List, Literal

from pydantic import Field

from app.models.cyclonedx import (
    BomLinkDocument,
    BomLinkElement,
    CamelModel,
    Hash,
    License,
    LicenseExpression,
    SerialNumber,
    Signature,
)


# ============================================================
# Enums
# ============================================================
class ReportType(str, Enum):
    AI_MODEL_INFO = "aimodelinfo"
    ASSESSMENTS = "assessments"
    DATASETS = "datasets"
    DEFENCES = "defences"
    EU_AI_ACT = "euaiact"
    GADGETS = "gadgets"
    RISK_REPORT = "riskreport"


class Tool(CamelModel):
    vendor: str
    name: str
    version: str


class Supplier(CamelModel):
    name: str


class Component(CamelModel):
    bom_ref: str = Field(..., min_length=1, alias="bom-ref")
    type: Literal["machine-learning-model"]
    name: str
    version: str = Field(
        ...,
        max_length=1024,
        description="Version of the component, must be at most 1024 characters",
    )
    description: str
    # supplier: Supplier
    hashes: List[Hash]
    licenses: List[License | LicenseExpression]


class Metadata(CamelModel):
    timestamp: datetime
    component: Component
    supplier: Supplier
    tools: List[Tool]


class ExternalReference(CamelModel):
    type: Literal["bom"]
    url: BomLinkDocument | BomLinkElement
    comment: str


class AIMBOM(CamelModel):
    bom_format: Literal["CycloneDX"]
    spec_version: Literal["1.7"]
    serial_number: SerialNumber
    version: int = Field(
        1, ge=1, description="Document version, defaults to 1, must be >= 1"
    )
    metadata: Metadata
    external_references: List[ExternalReference]
    signature: Signature | None = None
