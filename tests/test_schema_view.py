import asyncio

import pytest
from jsonschema import Draft202012Validator

from link_mcp.config import Settings
from link_mcp.runtime import Runtime
from link_mcp.schema_view import select_field


@pytest.fixture(scope="module")
def runtime():
    return Runtime(Settings(profile="customer"))


@pytest.mark.parametrize("name", ["link_lms_express_order", "link_lms_special_line_order"])
def test_large_models_are_accessible_in_complete_sections(runtime, name):
    result = asyncio.run(
        runtime.call("link_describe_api", {"tool_name": name, "section": "summary"})
    )
    assert not result.is_error
    assert not result.structured_content.get("truncated", False)
    fields = result.structured_content["result"]["input_fields"]
    assert any(row["field_path"] == "body.recipient" for row in fields)
    assert not any(row["field_path"] == "body.customerKey" for row in fields)
    for path in (
        "body.recipient",
        "body.info",
        "body.pieces[]" if "express" in name else "body.boxes[]",
    ):
        result = asyncio.run(
            runtime.call(
                "link_describe_api",
                {
                    "tool_name": name,
                    "section": "input",
                    "field_path": path,
                },
            )
        )
        assert not result.is_error
        assert not result.structured_content.get("truncated", False)
        schema = result.structured_content["result"]["input_schema"]
        Draft202012Validator.check_schema(schema)
        assert schema["type"] == "object"
        assert schema["properties"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"section": "input", "field_path": "body.customerKey"},
        {"section": "input", "field_path": "body.missing"},
        {"section": "input", "field_path": "body.no[]"},
        {"section": "summary", "field_path": "body"},
    ],
)
def test_field_selection_cannot_expose_hidden_credentials(runtime, arguments):
    result = asyncio.run(
        runtime.call(
            "link_describe_api",
            {
                "tool_name": "link_lms_order_detail",
                **arguments,
            },
        )
    )
    assert result.is_error


def test_selected_array_item_retains_reachable_constraints():
    root = {
        "type": "object",
        "properties": {
            "body": {
                "type": "object",
                "properties": {
                    "boxes": {"type": "array", "items": {"$ref": "#/$defs/Box"}},
                },
            }
        },
        "$defs": {
            "Box": {
                "type": "object",
                "required": ["contact"],
                "properties": {
                    "contact": {"$ref": "#/$defs/Contact"},
                },
            },
            "Contact": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "minLength": 2},
                },
            },
            "Unrelated": {"type": "string"},
        },
    }
    selected = select_field(root, "body.boxes[]")
    assert set(selected["$defs"]) == {"Contact"}
    validator = Draft202012Validator(selected)
    validator.validate({"contact": {"name": "Recipient"}})
    assert list(validator.iter_errors({"contact": {"name": "A"}}))
    assert list(validator.iter_errors({"contact": {}}))
