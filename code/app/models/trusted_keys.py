import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

SHA256_HEX = re.compile(r"[0-9a-f]{64}")


class TrustedKey(BaseModel):
    """A key STRAE signs, or has signed, with."""

    sha256: str = Field(
        ...,
        description=(
            "SHA-256 of the public key's DER SubjectPublicKeyInfo encoding, as "
            "lowercase hex. Colons are removed and the value is lowercased on load."
        ),
    )
    in_use_from: datetime = Field(
        ..., description="When the key went into use. Audit only."
    )
    retired_at: datetime | None = Field(
        None,
        description=(
            "When the key was replaced. Audit only: a retired key is still "
            "trusted, so documents signed before the rotation still verify."
        ),
    )
    note: str | None = None

    @field_validator("sha256", mode="before")
    @classmethod
    def normalize_sha256(cls, value: object) -> object:
        """Remove colons and lowercase the fingerprint, then check that it is
        64 hex characters.

        Args:
            value: The fingerprint as given in the file.

        Returns:
            The normalized fingerprint.

        Raises:
            ValueError: If the normalized value is not 64 hex characters.
        """

        if not isinstance(value, str):
            return value

        normalized = value.replace(":", "").strip().lower()
        if not SHA256_HEX.fullmatch(normalized):
            raise ValueError("sha256 must be 64 hex characters")

        return normalized


class TrustedKeys(BaseModel):
    """The trust list: every key STRAE has ever signed with."""

    keys: list[TrustedKey]

    @model_validator(mode="after")
    def check_unique(self) -> "TrustedKeys":
        """Reject a list where the same fingerprint appears twice.

        Returns:
            The validated list.

        Raises:
            ValueError: If a fingerprint appears more than once.
        """

        seen: set[str] = set()
        for key in self.keys:
            if key.sha256 in seen:
                raise ValueError(f"Duplicate key {key.sha256}")
            seen.add(key.sha256)

        return self
