import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, FormatChecker
from referencing import Registry, Resource

CDX_SCHEMA_PATH = Path(__file__).parent / "schemas" / "bom-1.7.schema.json"
SPDX_SCHEMA_PATH = Path(__file__).parent / "schemas" / "spdx.schema.json"
JSF_SCHEMA_PATH = Path(__file__).parent / "schemas" / "jsf-0.82.schema.json"
CDEFS_SCHEMA_PATH = Path(__file__).parent / "schemas" / "cryptography-defs.schema.json"


# The JSF schema defines the `algorithm` field as a `oneOf` between a known algorithm
# enum (e.g. "ES256") and a `format: uri` string for custom/proprietary algorithms.
# By default, jsonschema's URI format validation is loose enough that plain strings
# like "ES256" pass as valid URIs (interpreted as relative URIs), causing "ES256" to
# match both branches and failing `oneOf` (which requires exactly one match).
# This custom checker enforces that a URI must have a scheme (e.g. "https://"),
# so known algorithm names only match the enum branch.
def make_format_checker() -> FormatChecker:
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


def make_validator_registry() -> Registry[Any]:
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
    with open(CDX_SCHEMA_PATH) as sf:
        validator = Draft7Validator(
            json.load(sf),
            registry=make_validator_registry(),
            format_checker=make_format_checker(),
        )

    return validator


def validate_aimbom(aimbom_dict: dict) -> None:
    validator = get_validator()
    errors = sorted(validator.iter_errors(aimbom_dict), key=lambda e: e.path)

    if errors:
        messages = [f"{list(error.path)}: {error.message}" for error in errors]
        raise ValueError("CycloneDX validation failed:\n" + "\n".join(messages))
