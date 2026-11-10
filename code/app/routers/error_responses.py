"""Helpers for documenting error responses in the OpenAPI schema (Swagger UI).

FastAPI only documents an endpoint's success response and request validation
errors on its own. The other status codes an endpoint can return are passed
to its route decorator through `responses=`.
"""

from typing import Any

from app.models.responses import ErrorResponse, UnprocessableEntityResponse


def error(description: str) -> dict[str, Any]:
    """Document an error response whose body is `{"detail": str}`."""
    return {"model": ErrorResponse, "description": description}


def unprocessable(description: str) -> dict[str, Any]:
    """Document a 422 response.

    Declaring 422 replaces FastAPI's automatic validation error response, so
    its model accepts both the validation error list and a string detail.
    """
    return {"model": UnprocessableEntityResponse, "description": description}


def unauthorized() -> dict[str, Any]:
    """Document the 401 of an endpoint that requires an access token."""
    return error("The access token is missing, invalid or expired.")

