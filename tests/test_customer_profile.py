import asyncio
import copy
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator
from mcp import Client, StdioServerParameters
from pydantic import ValidationError

from link_mcp.catalog import Catalog
from link_mcp.client import ApiError, LinkClient
from link_mcp.config import Settings
from link_mcp.profiles import CUSTOMER_TOOLS
from link_mcp.runtime import Runtime
from link_mcp.server import create_server

CATALOG = Catalog()


def minimal_instance(schema, root=None):
    root = schema if root is None else root
    if "$ref" in schema:
        resolved = root
        for part in schema["$ref"][2:].split("/"):
            resolved = resolved[part.replace("~1", "/").replace("~0", "~")]
        return minimal_instance(resolved, root)
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
    return "FIXTURE"


def customer_settings(**values):
    return Settings(
        profile="customer", token="fixture-token", customer_key="bound-fixture-key", **values
    )


def call_mock(name, arguments, settings=None, handler=None):
    settings = settings or customer_settings()
    calls = []

    async def run():
        def respond(request):
            calls.append(request)
            return (
                handler(request) if handler else httpx.Response(200, json={"code": 0, "data": {}})
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            result = await Runtime(settings, CATALOG).call(
                name, arguments, LinkClient(settings, http)
            )
            return result

    return asyncio.run(run()), calls


def test_full_profile_is_backward_compatible():
    runtime = Runtime(Settings())
    assert len(runtime.operations) == 27
    assert len(runtime.tools) == 30
    assert runtime.list_services()["profile"] == "full"
    result, requests = call_mock(
        "link_finance_balance",
        {"body": {"customerKey": "explicit-fixture"}},
        Settings(token="fixture-token", customer_key="default-fixture"),
    )
    assert not result.is_error
    assert json.loads(requests[0].content)["customerKey"] == "explicit-fixture"


def test_customer_profile_filters_discovery_and_descriptions():
    runtime = Runtime(customer_settings())
    assert set(runtime.operations) == CUSTOMER_TOOLS
    assert len(runtime.tools) == 25
    assert len(Runtime(customer_settings(read_only=True)).tools) == 14
    assert len(Runtime(customer_settings(services=("finance",))).operations) == 3
    result = asyncio.run(runtime.call("link_search_apis", {"query": "", "limit": 100}))
    assert {
        item["tool_name"] for item in result.structured_content["result"]["items"]
    } == CUSTOMER_TOOLS
    for name in (
        "link_user_oauth_login",
        "link_lms_push_post",
        "link_edge_push_post",
        "link_lms_dws_upload_file",
        "link_lms_dws_upload_data_post",
    ):
        with pytest.raises(ApiError, match="接口不存在或未启用"):
            runtime.describe(name)
        result, calls = call_mock(name, {})
        assert result.is_error
        assert not calls


def test_new_endpoints_do_not_implicitly_enter_customer_profile():
    catalog = Catalog()
    operation = next(iter(catalog.operations.values()))
    future = replace(operation, operation_id="futureOperation")
    catalog.operations[future.tool_name] = future
    assert future.tool_name in Runtime(Settings(), catalog).operations
    assert future.tool_name not in Runtime(customer_settings(), catalog).operations


def test_customer_schema_does_not_mutate_shared_catalog():
    catalog = Catalog()
    runtime = Runtime(customer_settings(), catalog)
    full = Runtime(Settings(), catalog)
    for name, operation in runtime.operations.items():
        schema = runtime.describe(name)["input_schema"]
        Draft202012Validator.check_schema(schema)
        if operation.accepts_customer_key:
            body = schema["properties"]["body"]
            if "$ref" in body:
                body = schema["$defs"][body["$ref"].split("/")[-1]]
            assert "customerKey" not in body["properties"]
            assert "customerKey" not in body.get("required", [])
            assert "customerKey" in json.dumps(full.describe(name)["input_schema"])


@pytest.mark.parametrize("name", sorted(CUSTOMER_TOOLS))
def test_all_customer_operations_inject_only_the_documented_identity(name):
    operation = CATALOG.operations[name]
    arguments = minimal_instance(operation.request_schema)
    arguments.get("body", {}).pop("customerKey", None)
    result, requests = call_mock(name, arguments)
    assert not result.is_error, result.content
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert requests[0].headers["linkToken"] == "fixture-token"
    if operation.accepts_customer_key:
        assert body["customerKey"] == "bound-fixture-key"
    else:
        assert "customerKey" not in body
    assert "customerKey" not in arguments["body"]


@pytest.mark.parametrize("field", ["customerKey", "CustomerKey", "CUSTOMERKEY"])
def test_customer_identity_override_is_blocked_before_network(field):
    result, requests = call_mock("link_finance_balance", {"body": {field: "other-private-key"}})
    assert result.is_error
    assert not requests
    assert result.structured_content["error"]["kind"] == "customer_identity_locked"
    assert "other-private-key" not in result.content[0].text


def test_customer_credentials_missing_but_documentation_works():
    runtime = Runtime(Settings(profile="customer"))
    result = asyncio.run(runtime.call("link_list_services", {}))
    assert not result.is_error
    assert result.structured_content["result"]["customer_identity_locked"]
    assert not result.structured_content["result"]["token_configured"]
    result, calls = call_mock(
        "link_lms_query_tracks",
        {"body": {"nos": ["TEST"]}},
        Settings(profile="customer", token="fixture-token"),
    )
    assert result.structured_content["error"]["kind"] == "missing_customer_key"
    assert not calls


def test_client_environment_selects_customer_and_custom_gateway():
    settings = Settings.from_env(
        {
            "LINK_PROFILE": "customer",
            "LINK_TOKEN": "fixture-token",
            "LINK_CUSTOMER_KEY": "bound-fixture-key",
            "LINK_API_BASE_URL": "https://customer.example.invalid/api",
        }
    )
    result, calls = call_mock("link_finance_balance", {"body": {}}, settings)
    assert not result.is_error
    assert (
        str(calls[0].url) == "https://customer.example.invalid/api/financeservice/openapi/balance"
    )
    with pytest.raises(ValidationError):
        Settings.from_env({"LINK_PROFILE": "unknown"})


def test_nested_validation_and_write_timeout_do_not_send_duplicates():
    operation = CATALOG.operations["link_pds_order"]
    arguments = minimal_instance(operation.request_schema)
    arguments["body"].pop("customerKey")
    del arguments["body"]["pieces"][0]["weight"]
    result, requests = call_mock(operation.tool_name, arguments)
    assert result.structured_content["error"]["kind"] == "validation_error"
    assert not requests

    arguments = minimal_instance(operation.request_schema)
    arguments["body"].pop("customerKey")

    def timeout(request):
        raise httpx.ReadTimeout("fixture", request=request)

    result, requests = call_mock(operation.tool_name, arguments, handler=timeout)
    assert result.structured_content["error"]["kind"] == "timeout"
    assert len(requests) == 1
    assert "可能已生效" in result.content[0].text


async def check_customer_connection(client):
    tools = await client.list_tools()
    assert len(tools.tools) == 25
    result = await client.call_tool("link_list_services", {})
    assert result.structured_content["result"]["profile"] == "customer"
    result = await client.call_tool("link_finance_balance", {"body": {"customerKey": "other-key"}})
    assert result.is_error
    resources = await client.list_resources()
    assert len(resources.resources) == 23
    description = await client.read_resource("link://api/link_finance_balance")
    data = json.loads(description.contents[0].text)
    assert data["input_schema"] == next(
        tool.input_schema for tool in tools.tools if tool.name == "link_finance_balance"
    )


def test_customer_in_process_mcp_handshake():
    async def run():
        async with Client(create_server(customer_settings()), raise_exceptions=True) as client:
            await check_customer_connection(client)

    asyncio.run(asyncio.wait_for(run(), timeout=20))


def test_customer_stdio_entrypoint(tmp_path):
    root = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(root / "server.py"), "--env-file", str(tmp_path / "absent.env")],
        cwd=tmp_path,
        env={
            **os.environ,
            "LINK_PROFILE": "customer",
            "LINK_TOKEN": "fixture-token",
            "LINK_CUSTOMER_KEY": "bound-fixture-key",
            "LINK_SERVICES": "",
            "LINK_READ_ONLY": "false",
            "PYTHONIOENCODING": "utf-8",
        },
    )

    async def run():
        async with Client(params) as client:
            await check_customer_connection(client)

    asyncio.run(asyncio.wait_for(run(), timeout=25))
