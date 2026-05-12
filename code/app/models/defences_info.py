from typing import Dict, List, Literal

from pydantic import Field

from app.models.cyclonedx import CamelModel, SerialNumber, Signature


class DefencesInfo(CamelModel):
    bom_format: Literal["CycloneDX"]
    spec_version: Literal["1.7"]
    serial_number: SerialNumber
    version: int = Field(
        1, ge=1, description="Document version, defaults to 1, must be >= 1"
    )
    components: List[Dict]
    signature: Signature
