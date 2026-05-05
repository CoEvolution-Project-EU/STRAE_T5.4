from datetime import datetime
from typing import Annotated, List, Literal, Optional

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic.alias_generators import to_camel


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


# ============================================================
# Generic / reusable value models
# ============================================================
class Property(CamelModel):
    name: str
    value: Optional[str] = None


# ============================================================
# Dataset & model description (Model Card)
# ============================================================
class Contents(CamelModel):
    url: AnyUrl


class Dataset(CamelModel):
    type: Literal["source-code", "configuration", "dataset", "definition", "other"]
    name: str
    contents: Contents


class ModelParameters(CamelModel):
    architecture_family: str
    task: str
    datasets: List[Dataset]


class ModelCard(CamelModel):
    model_parameters: ModelParameters


# ============================================================
# CycloneDX Component models
# ============================================================
ComponentTypes = Literal[
    "application",
    "framework",
    "library",
    "container",
    "platform",
    "operating-system",
    "device",
    "device-driver",
    "firmware",
    "file",
    "machine-learning-model",
    "data",
    "cryptographic-asset",
]


class Component(CamelModel):
    bom_ref: str = Field(..., min_length=1, alias="bom-ref")
    type: ComponentTypes
    name: str
    version: str = Field(
        ...,
        max_length=1024,
        description="Version of the component, must be at most 1024 characters",
    )
    properties: Optional[List[Property]] = None


class MetadataComponent(Component):
    """
    Primary CycloneDX component describing the AI model itself.
    """

    description: str
    model_card: ModelCard


# ============================================================
# Tooling & service metadata
# ============================================================
class ToolComponent(CamelModel):
    type: ComponentTypes
    name: str


class ServiceProvider(CamelModel):
    name: str


class ToolService(CamelModel):
    name: str
    version: str
    provider: ServiceProvider


class Tools(CamelModel):
    """
    CycloneDX tools container.
    Exactly one of `components` or `services` must be provided.
    """

    components: Optional[List[ToolComponent]] = None
    services: Optional[List[ToolService]] = None

    @model_validator(mode="after")
    def validate_tools(self):
        if not self.components and not self.services:
            raise ValueError(
                "tools must contain at least one of: components or services"
            )
        elif self.components and self.services:
            raise ValueError("tools must contain only one of: components or services")
        return self


# ============================================================
# Metadata & annotations
# ============================================================
class Metadata(CamelModel):
    timestamp: datetime
    tools: Tools
    component: MetadataComponent


class Annotator(CamelModel):
    """
    Identifies the entity that produced an annotation.
    """

    component: Optional[ToolComponent] = None
    service: Optional[ToolService] = None

    @model_validator(mode="after")
    def validate_tools(self):
        if not self.component and not self.service:
            raise ValueError("tools must contain at least one of: component or service")
        elif self.component and self.service:
            raise ValueError("tools must contain only one of: component or service")
        return self


class Annotation(CamelModel):
    subjects: List[str]
    annotator: Annotator
    timestamp: datetime
    text: str


# ============================================================
# Base CycloneDX document
# ============================================================
SerialNumber = Annotated[
    str,
    StringConstraints(
        pattern=r"^urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    ),
]


# ============================================================
# External references & security-related models
# ============================================================
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


class ExternalReference(CamelModel):
    url: AnyUrl | BomLinkDocument | BomLinkElement
    type: Literal["website", "risk-assessment"]  # Add more types as needed
    comment: Optional[str] = None


class Rating(CamelModel):
    severity: Literal["low", "medium", "high", "critical", "info", "unknown", "none"]


class AffectedComponent(CamelModel):
    ref: str = Field(
        ...,
        min_length=1,
        description="Reference of the affected component (at least 1 character)",
    )


class Vulnerability(CamelModel):
    id: str
    ratings: List[Rating]
    description: str
    affects: List[AffectedComponent]
