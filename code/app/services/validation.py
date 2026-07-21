import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, FormatChecker
from referencing import Registry, Resource

logger = logging.getLogger(__name__)

SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"

CDX_SCHEMA_PATH = SCHEMAS_DIR / "bom-1.7.schema.json"
SPDX_SCHEMA_PATH = SCHEMAS_DIR / "spdx.schema.json"
JSF_SCHEMA_PATH = SCHEMAS_DIR / "jsf-0.82.schema.json"
CDEFS_SCHEMA_PATH = SCHEMAS_DIR / "cryptography-defs.schema.json"


# The JSF schema defines the `algorithm` field in the `signature` as a `oneOf` between a
# known algorithm enum (e.g. "ES256") and a `format: uri` string for custom/proprietary algorithms.
# By default, jsonschema's URI format validation is loose enough that plain strings
# like "ES256" pass as valid URIs (interpreted as relative URIs), causing "ES256" to
# match both branches and failing `oneOf` (which requires exactly one match).
# This custom checker enforces that a URI must have a scheme (e.g. "https://"),
# so known algorithm names only match the enum branch.
def get_format_checker() -> FormatChecker:
    """
    Get a custom JSON Schema format checker with strict URI validation.

    Returns:
        FormatChecker: A JSON Schema format checker with strict URI validation.
    """

    checker = FormatChecker()

    # Override the uri format to be strict — ES256 etc. must not match
    @checker.checks("uri", raises=ValueError)
    def check_uri(value):
        from urllib.parse import urlparse

        result = urlparse(value)
        if not result.scheme:
            raise ValueError(f"{value!r} is not a valid URI (no scheme)")
        return True

    return checker


def get_validator_registry() -> Registry[Any]:
    """
    Get a JSON Schema registry with the required schemas for CycloneDX validation.

    Returns:
        Registry: A JSON Schema registry containing the CycloneDX, SPDX, JSF, and cryptography-defs schemas.
    """

    with (
        open(SPDX_SCHEMA_PATH) as spdx,
        open(JSF_SCHEMA_PATH) as jsf,
        open(CDEFS_SCHEMA_PATH) as cdefs,
    ):
        return Registry().with_resources(
            [
                (
                    "spdx.schema.json",
                    Resource.from_contents(json.load(spdx)),
                ),
                (
                    "cryptography-defs.schema.json",
                    Resource.from_contents(json.load(cdefs)),
                ),
                (
                    "jsf-0.82.schema.json",
                    Resource.from_contents(json.load(jsf)),
                ),
            ]
        )


@lru_cache
def get_validator() -> Draft7Validator:
    """
    Get a JSON Schema validator for CycloneDX reports.

    Returns:
        Draft7Validator: A JSON Schema validator for CycloneDX reports.
    """

    with open(CDX_SCHEMA_PATH) as sf:
        validator = Draft7Validator(
            json.load(sf),
            registry=get_validator_registry(),
            format_checker=get_format_checker(),
        )

    return validator


def cdx_validate_dict(report_dict: dict) -> None:
    """
    Validate a CycloneDX report dictionary against the CycloneDX JSON Schema.

    Args:
        report_dict (dict): The CycloneDX report as a dictionary.
    """

    logger.debug("Starting CycloneDX validation")
    validator = get_validator()
    errors = sorted(validator.iter_errors(report_dict), key=lambda e: e.path)

    if errors:
        messages = [f"{list(error.path)}: {error.message}" for error in errors]
        logger.warning("CycloneDX validation failed with %d errors", len(errors))
        raise ValueError("CycloneDX validation failed:\n" + "\n".join(messages))
    else:
        logger.debug("CycloneDX validation successful")
