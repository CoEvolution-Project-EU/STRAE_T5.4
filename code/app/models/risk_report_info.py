from datetime import datetime
from typing import Dict, List, Literal

from pydantic import Field

from app.models.cyclonedx import (
    CamelModel,
    ComponentTypes,
    Property,
    SerialNumber,
    Signature,
)


class MetadataComponent(CamelModel):
    type: ComponentTypes
    name: str
    version: str | None = None
    properties: List[Property] | None = None


class Metadata(CamelModel):
    timestamp: str
    tools: Dict
    component: MetadataComponent


class Component(CamelModel):
    bom_ref: str = Field(..., min_length=1, alias="bom-ref")
    type: ComponentTypes
    name: str
    version: str | None = None
    properties: List[Property] | None = None
    cpe: str | None = None
    purl: str | None = None


class Vulnerability(CamelModel):
    bom_ref: str = Field(..., min_length=1, alias="bom-ref")
    id: str | None = None
    source: Dict | None = None
    ratings: List[Dict] | None = None
    cwes: List[int] | None = None
    description: str | None = None
    published: datetime | None = None
    updated: datetime | None = None
    affects: List[Dict] | None = None
    properties: List[Property] | None = None


class RiskReportInfo(CamelModel):
    bom_format: Literal["CycloneDX"]
    spec_version: Literal["1.6", "1.7"]
    serial_number: SerialNumber
    version: int = Field(
        1, ge=1, description="Document version, defaults to 1, must be >= 1"
    )
    metadata: Metadata
    components: List[Component]
    vulnerabilities: List[Vulnerability]
    signature: Signature
