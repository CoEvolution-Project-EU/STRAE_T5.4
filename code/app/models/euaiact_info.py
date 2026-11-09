from typing import Dict, List, Literal

from pydantic import Field

from app.models.cyclonedx import (
    CamelModel,
    ComponentTypes,
    Property,
    SerialNumber,
    Signature,
)


class ToolComponent(CamelModel):
    bom_ref: str = Field(..., min_length=1, alias="bom-ref")
    type: ComponentTypes
    name: str
    version: str | None = None
    properties: List[Property] | None = None


class Tools(CamelModel):
    components: List[ToolComponent]


class MetadataComponent(CamelModel):
    bom_ref: str = Field(..., min_length=1, alias="bom-ref")
    type: ComponentTypes
    name: str
    version: str | None = None


class Metadata(CamelModel):
    timestamp: str
    tools: Tools | None = None
    component: MetadataComponent | None = None


class Requirement(CamelModel):
    bom_ref: str = Field(..., min_length=1, alias="bom-ref")
    identifier: str | None = None
    title: str | None = None
    text: str | None = None


class Standard(CamelModel):
    bom_ref: str = Field(..., min_length=1, alias="bom-ref")
    name: str | None = None
    version: str | None = None
    description: str | None = None
    requirements: List[Requirement] | None = None


class Definitions(CamelModel):
    standards: List[Standard] | None = None


class Claim(CamelModel):
    bom_ref: str = Field(..., min_length=1, alias="bom-ref")
    target: str | None = None
    predicate: str | None = None
    reasoning: str | None = None


class AttestationMapEntry(CamelModel):
    requirement: str | None = None
    claims: List[str] | None = None


class Attestation(CamelModel):
    summary: str | None = None
    map: List[AttestationMapEntry] | None = None


class Declarations(CamelModel):
    claims: List[Claim] | None = None
    attestations: List[Attestation] | None = None


class EUAIActInfo(CamelModel):
    bom_format: Literal["CycloneDX"]
    spec_version: Literal["1.7"]
    serial_number: SerialNumber
    version: int = Field(
        1, ge=1, description="Document version, defaults to 1, must be >= 1"
    )
    metadata: Metadata | None = None
    definitions: Definitions | None = None
    declarations: Declarations | None = None
    properties: List[Property] | None = None
    dependencies: List[Dict] | None = None
    signature: Signature
