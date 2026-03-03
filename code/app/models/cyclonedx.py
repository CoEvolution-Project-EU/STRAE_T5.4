from datetime import datetime
from enum import Enum
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
# Enums
# ============================================================
class ReportOrigin(str, Enum):
    STR_Defence_Framework = "STR Defence Framework"
    STAE = "STAE"
    RAGRE = "RAGRE"


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


class BaseCycloneDX(CamelModel):
    """
    Base class for all CycloneDX-based reports.
    """

    bom_format: Literal["CycloneDX"]
    spec_version: Literal["1.7"]
    serial_number: SerialNumber
    version: int = Field(
        1, ge=1, description="Document version, defaults to 1, must be >= 1"
    )
    metadata: Metadata
    annotations: List[Annotation]

    def get_model_id(self) -> str:
        """
        Returns the BOM reference of the primary subject component
        (CycloneDX metadata.component).
        """
        return self.metadata.component.bom_ref


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


# ============================================================
# Specialized CycloneDX report types
# ============================================================
class DefenceReport(BaseCycloneDX):
    components: List[Component]


class AssessmentReport(BaseCycloneDX):
    external_references: List[ExternalReference]
    properties: List[Property]


class RiskAssessmentReport(BaseCycloneDX):
    external_references: List[ExternalReference]
    vulnerabilities: List[Vulnerability]


# ============================================================
# AI Model Bill of Materials (AIMBOM)
# ============================================================
class AIMBOM(BaseCycloneDX):
    components: List[Component]
    external_references: List[ExternalReference]
    properties: List[Property]
    vulnerabilities: List[Vulnerability]


# ============================================================
# Union type for all supported security reports
# ============================================================
SecurityReport = AssessmentReport | DefenceReport | RiskAssessmentReport
