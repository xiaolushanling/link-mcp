import pytest
from jsonschema import Draft202012Validator

from link_mcp.catalog import schema_bundle
from link_mcp.config import Settings
from link_mcp.runtime import Runtime


def test_all_documented_operations_have_unique_tools(catalog):
    assert len(catalog.operations) == 27
    assert len(catalog.manifest["services"]) == 6
    assert len(Runtime(Settings(), catalog).tools) == 30
    assert all(len(name) <= 64 for name in catalog.operations)
    for operation in catalog.operations.values():
        Draft202012Validator.check_schema(operation.input_schema)
        for schema in operation.response_schemas.values():
            Draft202012Validator.check_schema(schema)


def test_annotations_follow_business_semantics(catalog):
    assert sum(operation.read_only for operation in catalog.operations.values()) == 11
    assert catalog.operations["link_lms_query_tracks"].to_tool().annotations.read_only_hint
    assert not catalog.operations["link_pds_cal_price"].to_tool().annotations.read_only_hint
    assert catalog.operations["link_lms_delete_order"].to_tool().annotations.destructive_hint


def test_customer_key_is_optional_only_in_public_schema(catalog):
    operation = catalog.operations["link_finance_query_price"]
    body_ref = operation.input_schema["properties"]["body"]["$ref"].split("/")[-1]
    assert "customerKey" not in operation.input_schema["$defs"][body_ref]["required"]
    assert "customerKey" in operation.request_schema["$defs"][body_ref]["required"]


def test_read_only_and_service_filters(catalog):
    runtime = Runtime(Settings(services=("lms", "finance"), read_only=True), catalog)
    assert len(runtime.operations) == 5
    assert "link_lms_express_order" not in runtime.tools
    assert "link_pds_order" not in runtime.tools
    with pytest.raises(ValueError, match="LINK_SERVICES"):
        Runtime(Settings(services=("typo",)), catalog)


def test_schema_conversion_handles_nullable_recursive_and_literal_examples():
    document = {
        "components": {
            "schemas": {
                "Node": {
                    "type": "object",
                    "properties": {
                        "next": {"$ref": "#/components/schemas/Node", "nullable": True},
                        "price": {"type": "number", "minimum": 0, "exclusiveMinimum": True},
                        "raw": {"type": "object", "example": {"$ref": "literal-not-a-schema"}},
                    },
                }
            }
        }
    }
    bundled = schema_bundle({"$ref": "#/components/schemas/Node"}, document)
    Draft202012Validator.check_schema(bundled)
    Draft202012Validator(bundled).validate({"next": {"next": None, "price": 1}})
    assert bundled["$defs"]["Node"]["properties"]["price"]["exclusiveMinimum"] == 0
    assert (
        bundled["$defs"]["Node"]["properties"]["raw"]["example"]["$ref"] == "literal-not-a-schema"
    )
