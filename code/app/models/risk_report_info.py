from typing import Dict, List, Literal

from pydantic import Field

from app.models.cyclonedx import CamelModel, SerialNumber, Signature


class RiskReportInfo(CamelModel):
    bom_format: Literal["CycloneDX"]
    spec_version: Literal["1.6", "1.7"]
    serial_number: SerialNumber
    version: int = Field(
        1, ge=1, description="Document version, defaults to 1, must be >= 1"
    )
    metadata: Dict
    components: List[Dict]
    vulnerabilities: List[Dict]
    signature: Signature
