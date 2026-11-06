import copy
from typing import Any

import pytest

from link_mcp.catalog import Catalog


@pytest.fixture(scope="session")
def catalog() -> Catalog:
    return Catalog()


def minimal_instance(schema: dict[str, Any], root: dict[str, Any] | None = None) -> Any:
    """Build only the fields the upstream schema actually requires."""
    root = schema if root is None else root
    if "$ref" in schema:
        definition = root
        for part in schema["$ref"][2:].split("/"):
            definition = definition[part.replace("~1", "/").replace("~0", "~")]
        return minimal_instance(definition, root)
    if "example" in schema:
        return copy.deepcopy(schema["example"])
    if "enum" in schema:
        return schema["enum"][0]
    if schema.get("type") == "object":
        return {
            key: minimal_instance(schema["properties"][key], root)
            for key in schema.get("required", [])
        }
    if schema.get("type") == "array":
        return [minimal_instance(schema["items"], root)] * max(1, schema.get("minItems", 0))
    if schema.get("type") in {"integer", "number"}:
        return max(1, schema.get("minimum", 0))
    if schema.get("type") == "boolean":
        return False
    return "FIXTURE"
