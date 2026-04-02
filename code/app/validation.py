import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft7Validator

SCHEMA_PATH = Path(__file__).parent / "schemas" / "bom-1.7.schema.json"


@lru_cache
def get_validator():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)

    # TODO: Use register to load the additional schemas with a URI to allow for proper $ref resolution,
    # currently this is not working (e.g., signature) because the schema contains $ref to external files which are not being resolved correctly.

    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def validate_aimbom(aimbom_dict: dict):
    validator = get_validator()
    errors = sorted(validator.iter_errors(aimbom_dict), key=lambda e: e.path)

    if errors:
        messages = [f"{list(error.path)}: {error.message}" for error in errors]
        raise ValueError("CycloneDX validation failed:\n" + "\n".join(messages))
