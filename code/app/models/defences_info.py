from datetime import datetime
from typing import Dict, List, Literal

from pydantic import AnyUrl, Field

from app.models.cyclonedx import (
    BomLinkDocument,
    BomLinkElement,
    CamelModel,
    ComponentTypes,
    Property,
    SerialNumber,
    Signature,
)


class ExternalReference(CamelModel):
    type: str
    url: AnyUrl | BomLinkDocument | BomLinkElement
    comment: str | None = None


class Component(CamelModel):
    bom_ref: str = Field(..., min_length=1, alias="bom-ref")
    type: ComponentTypes
    name: str
    group: str | None = None
    version: str | None = None
    supplier: Dict | None = None
    description: str | None = None
    properties: List[Property] | None = None
    external_references: List[ExternalReference] | None = None


class Metadata(CamelModel):
    timestamp: datetime


class DefencesInfo(CamelModel):
    bom_format: Literal["CycloneDX"]
    spec_version: Literal["1.7"]
    serial_number: SerialNumber
    version: int = Field(
        1, ge=1, description="Document version, defaults to 1, must be >= 1"
    )
    metadata: Metadata
    components: List[Component] | None = None
    signature: Signature
