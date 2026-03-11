from datetime import datetime
from enum import Enum
from typing import Annotated, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel


# ============================================================
# Enums
# ============================================================
class ReportType(str, Enum):
    AI_MODEL_INFO = "aimodelinfo"
    ASSESSMENTS = "assessments"
    DATASETS = "datasets"
    EU_AI_ACT = "euaiact"
    GADGETS = "gadgets"


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


class Tool(CamelModel):
    name: str
    version: str
    vendor: str


class Component(CamelModel):
    bom_ref: str = Field(..., min_length=1, alias="bom-ref")
    type: Literal["machine-learning-model"]
    name: str
    version: str = Field(
        ...,
        max_length=1024,
        description="Version of the component, must be at most 1024 characters",
    )


class Metadata(CamelModel):
    timestamp: datetime
    tools: List[Tool]
    component: Component


class AIMBOM(CamelModel):
    bom_format: Literal["CycloneDX"]
    spec_version: Literal["1.7"]
    serial_number: SerialNumber
    version: int = Field(
        1, ge=1, description="Document version, defaults to 1, must be >= 1"
    )
    metadata: Dict
    external_references: List[Dict]
    signature: Dict
