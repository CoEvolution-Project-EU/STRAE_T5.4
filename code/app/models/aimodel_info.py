from datetime import datetime
from typing import Dict, List, Literal

from pydantic import AnyUrl, Field

from app.models.aimbom import CamelModel
from app.models.cyclonedx import (
    BomLinkDocument,
    BomLinkElement,
    Hash,
    License,
    LicenseExpression,
    Property,
    SerialNumber,
    Signature,
)


class ModelParameters(CamelModel):
    approach: Dict | None = None
    architecture_family: str | None = None
    task: str | None = None
    datasets: List[Dict] | None = None
    model_architecture: str | None = None
    inputs: List[Dict] | None = None
    outputs: List[Dict] | None = None


class ModelCard(CamelModel):
    bom_ref: str = Field(..., min_length=1, alias="bom-ref")
    model_parameters: ModelParameters | None = None
    quantitative_analysis: Dict | None = None
    considerations: Dict | None = None
    properties: List[Property] | None = None


class ExternalReference(CamelModel):
    url: AnyUrl | BomLinkDocument | BomLinkElement
    type: Literal["website", "documentation", "vcs"]  # Add more types as needed
    comment: str | None = None


class Ancestor(CamelModel):
    bom_ref: str = Field(..., min_length=1, alias="bom-ref")
    type: Literal["machine-learning-model"]
    name: str
    version: str


class Pedigree(CamelModel):
    ancestors: List[Ancestor]


class AIModelInfoComponent(CamelModel):
    bom_ref: str = Field(..., min_length=1, alias="bom-ref")
    type: Literal["machine-learning-model"]
    name: str
    version: str
    description: str
    hashes: List[Hash] | None = None
    licenses: List[License | LicenseExpression] | None = None
    pedigree: Pedigree | None = None
    model_card: ModelCard | None = None
    external_references: List[ExternalReference] | None = None


class AIModelInfoMetadata(CamelModel):
    timestamp: datetime
    component: AIModelInfoComponent


class AIModelInfo(CamelModel):
    bom_format: Literal["CycloneDX"]
    spec_version: Literal["1.7"]
    serial_number: SerialNumber
    version: int = Field(
        1, ge=1, description="Document version, defaults to 1, must be >= 1"
    )
    metadata: AIModelInfoMetadata
    dependencies: List[Dict]
    components: List[Dict]
    signature: Signature
