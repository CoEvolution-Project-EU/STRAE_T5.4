from typing import Dict, List, Literal

from pydantic import Field

from app.models.cyclonedx import (
    CamelModel,
    ComponentTypes,
    Property,
    SerialNumber,
    Signature,
)


class Component(CamelModel):
    bom_ref: str = Field(..., min_length=1, alias="bom-ref")
    type: ComponentTypes
    name: str
    version: str | None = None
    description: str | None = None
    properties: List[Property] | None = None


class Tools(CamelModel):
    components: List[Component]


class Metadata(CamelModel):
    timestamp: str
    tools: Tools | None = None


class AssessmentInfo(CamelModel):
    bom_format: Literal["CycloneDX"]
    spec_version: Literal["1.7"]
    serial_number: SerialNumber
    version: int = Field(
        1, ge=1, description="Document version, defaults to 1, must be >= 1"
    )
    metadata: Metadata
    components: List[Dict] | None = None
    properties: List[Property] | None = None
    vulnerabilities: List[Dict] | None = None
    declarations: Dict | None = None
    signature: Signature
