import json
from pathlib import Path

from link_mcp.document_safety import scrub_credential_examples


def test_schema_credentials_are_removed_without_changing_required_fields():
    document = {
        "type": "object",
        "required": ["customerKey"],
        "properties": {
            "customerKey": {
                "type": "string",
                "example": "fixture-sensitive",
                "default": "fixture-default",
            },
            "weight": {"type": "number", "example": 1.5, "default": 1},
        },
    }
    safe = scrub_credential_examples(document)
    assert safe["required"] == ["customerKey"]
    assert safe["properties"]["customerKey"] == {"type": "string"}
    assert safe["properties"]["weight"] == document["properties"]["weight"]
    assert document["properties"]["customerKey"]["example"] == "fixture-sensitive"


def test_headers_and_nested_payload_examples_do_not_keep_credentials():
    document = {
        "parameters": [
            {
                "name": "linkToken",
                "in": "header",
                "example": "fixture-sensitive",
                "schema": {"type": "string", "default": "fixture-sensitive"},
            }
        ],
        "example": {"body": {"customerKey": "fixture-sensitive", "weight": 1}},
        "examples": {"named": {"value": '{"password":"fixture-sensitive","name":"Example"}'}},
    }
    safe = scrub_credential_examples(document)
    assert "fixture-sensitive" not in json.dumps(safe)
    assert safe["example"] == {"body": {"weight": 1}}
    assert json.loads(safe["examples"]["named"]["value"]) == {"name": "Example"}


def test_published_snapshots_are_already_sanitized():
    root = Path(__file__).resolve().parents[1] / "src/link_mcp/data"
    for path in root.glob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document == scrub_credential_examples(document), path.name


def test_examples_can_contain_a_business_field_named_properties():
    document = {
        "example": {"properties": "ordinary parcel notes", "customerKey": "fixture-sensitive"}
    }
    assert scrub_credential_examples(document) == {
        "example": {"properties": "ordinary parcel notes"}
    }
