from datetime import datetime
from typing import Dict, List, Literal

from pydantic import AnyUrl, Field

from app.models.cyclonedx import CamelModel, Hash, Property, SerialNumber, Signature


class Data(CamelModel):
    type: Literal["dataset"]
    name: str
    contents: Dict | None = None
    classification: str | None = None
    sensitive_data: List[str] | None = None
    description: str | None = None


class LicenseName(CamelModel):
    name: str
    url: AnyUrl | None = None


class License(CamelModel):
    license: LicenseName


class Component(CamelModel):
    bom_ref: str = Field(..., min_length=1, alias="bom-ref")
    type: Literal["data"]
    name: str
    version: str | None = None
    description: str | None = None
    licenses: List[License] | None = None
    hashes: List[Hash] | None = None
    data: List[Data] | None = None
    properties: List[Property] | None = None


class Metadata(CamelModel):
    timestamp: datetime
    authors: List[Dict] | None = None
    supplier: Dict | None = None
    properties: List[Property] | None = None


class DatasetInfo(CamelModel):
    bom_format: Literal["CycloneDX"]
    spec_version: Literal["1.7"]
    serial_number: SerialNumber
    version: int = Field(
        1, ge=1, description="Document version, defaults to 1, must be >= 1"
    )
    metadata: Metadata
    components: List[Component] | None = None
    signature: Signature
