from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import AnyUrl, Field

from app.models.aimbom import CamelModel
from app.models.cyclonedx import (
    BomLinkDocument,
    BomLinkElement,
    Hash,
    License,
    LicenseExpression,
    SerialNumber,
    Signature,
)


class ExternalReference(CamelModel):
    url: AnyUrl | BomLinkDocument | BomLinkElement
    type: Literal["website", "documentation", "vcs"]  # Add more types as needed
    comment: Optional[str] = None


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
    hashes: List[Hash]
    licenses: List[License | LicenseExpression]
    pedigree: Pedigree
    model_card: Dict  # TODO: Define a proper model for the model card
    external_references: List[ExternalReference]


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
