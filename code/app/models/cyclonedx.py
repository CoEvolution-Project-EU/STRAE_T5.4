from typing import Annotated, List, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints
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
        extra="forbid",
    )


SerialNumber = Annotated[
    str,
    StringConstraints(
        pattern=r"^urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    ),
]

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


class Hash(CamelModel):
    alg: Literal["SHA-256"]
    content: str


class LicenseID(CamelModel):
    id: str


class License(CamelModel):
    license: LicenseID


class LicenseExpression(CamelModel):
    expression: str


class Signature(CamelModel):
    algorithm: Literal["ES256"]
    certificate_path: List[str]
    value: str
