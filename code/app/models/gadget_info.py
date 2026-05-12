from typing import List, Literal

from pydantic import Field

from app.models.cyclonedx import CamelModel, Hash, SerialNumber, Signature


class Component(CamelModel):
    type: Literal[
        "application",
        "machine-learning-model",
    ]
    name: str
    version: str | None = None
    description: str | None = None
    hashes: List[Hash] | None = None


class GadgetInfo(CamelModel):
    bom_format: Literal["CycloneDX"]
    spec_version: Literal["1.7"]
    serial_number: SerialNumber
    version: int = Field(
        1, ge=1, description="Document version, defaults to 1, must be >= 1"
    )
    components: List[Component]
    signature: Signature
