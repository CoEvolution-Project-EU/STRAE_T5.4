from datetime import datetime
from enum import Enum
from typing import Annotated, List, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel


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


# ============================================================
# Base Pydantic model with camelCase aliasing
# ============================================================
class CamelModel(BaseModel):
    """
    Base model that automatically converts snake_case fields
    to camelCase when serializing/deserializing.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
    )


SerialNumber = Annotated[
    str,
    StringConstraints(
        pattern=r"^urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    ),
]

BomLinkDocument = Annotated[
    str,
    StringConstraints(
        pattern=r"^urn:cdx:[0-9a-f]{8}-"
        r"[0-9a-f]{4}-"
        r"[0-9a-f]{4}-"
        r"[0-9a-f]{4}-"
        r"[0-9a-f]{12}/[1-9][0-9]*$"
    ),
]

BomLinkElement = Annotated[
    str,
    StringConstraints(
        pattern=r"^urn:cdx:[0-9a-f]{8}-"
        r"[0-9a-f]{4}-"
        r"[0-9a-f]{4}-"
        r"[0-9a-f]{4}-"
        r"[0-9a-f]{12}/[1-9][0-9]*#.+$"
    ),
]


class Tool(CamelModel):
    vendor: str
    name: str
    version: str


class Supplier(CamelModel):
    name: str


class Hash(CamelModel):
    alg: Literal["SHA-256"]
    content: str


class LicenseID(CamelModel):
    id: str


class License(CamelModel):
    license: LicenseID


class LicenseExpression(CamelModel):
    expression: str


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


class Signature(CamelModel):
    algorithm: Literal["ES256"]
    certificate_path: List[str]
    value: str


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
