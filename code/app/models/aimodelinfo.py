from datetime import datetime
from typing import Dict, List, Literal

from pydantic import Field

from app.models.aimbom import CamelModel
from app.models.cyclonedx import Hash, License, LicenseExpression, SerialNumber


class AIModelInfoComponent(CamelModel):
    bom_ref: str = Field(..., min_length=1, alias="bom-ref")
    type: Literal["machine-learning-model"]
    name: str
    version: str = Field(..., min_length=1)
    description: str
    hashes: List[Hash]
    licenses: List[License | LicenseExpression]
    pedigree: Dict
    model_card: Dict
    external_references: List[Dict]


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
