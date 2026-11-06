import asyncio
import json

import httpx
import pytest
from conftest import minimal_instance

from link_mcp.catalog import Catalog
from link_mcp.client import LinkClient
from link_mcp.config import Settings
from link_mcp.runtime import Runtime

CATALOG = Catalog()


def call_mock(name, arguments, handler=None, settings=None):
    settings = settings or Settings(token="fixture-token", customer_key="fixture-customer-key")
    requests = []

    async def run():
        def respond(request):
            requests.append(request)
            return (
                handler(request) if handler else httpx.Response(200, json={"code": 0, "data": {}})
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            return await Runtime(settings, CATALOG).call(
                name, arguments, LinkClient(settings, http)
            )

    return asyncio.run(run()), requests


@pytest.mark.parametrize("name", list(CATALOG.operations))
def test_every_endpoint_uses_documented_request(name):
    operation = CATALOG.operations[name]
    arguments = minimal_instance(operation.request_schema)
    if operation.raw_body and "body" in arguments:
        arguments["body"] = '{"fixture":true}'
    result, requests = call_mock(name, arguments)
    assert not result.is_error, result.content
    assert len(requests) == 1
    request = requests[0]
    assert (
        str(request.url)
        == "https://demo.linkl.com.cn/api" + operation.context_path + operation.path
    )
    assert request.method == operation.method
    assert request.headers["linkToken"] == "fixture-token"
    if "body" in arguments:
        if operation.raw_body:
            assert request.content == arguments["body"].encode("utf-8")
        else:
            expected = dict(arguments["body"])
            if operation.accepts_customer_key:
                expected.setdefault("customerKey", "fixture-customer-key")
            assert json.loads(request.content) == expected
    for key, value in arguments.get("headers", {}).items():
        assert request.headers[key] == value


def test_customer_key_injection_and_explicit_override():
    arguments = {"body": {"weight": 1.5}}
    result, requests = call_mock("link_finance_query_price", arguments)
    assert not result.is_error
    assert json.loads(requests[0].content)["customerKey"] == "fixture-customer-key"
    assert "customerKey" not in arguments["body"]
    result, requests = call_mock(
        "link_finance_query_price",
        {
            "body": {"weight": 1.5, "customerKey": "explicit-fixture"},
        },
    )
    assert json.loads(requests[0].content)["customerKey"] == "explicit-fixture"


def test_custom_base_url_is_loaded_from_client_environment():
    settings = Settings.from_env(
        {
            "LINK_API_BASE_URL": "https://custom.example.invalid/api/",
            "LINK_TOKEN": "fixture-token",
        }
    )
    result, requests = call_mock(
        "link_lms_query_tracks",
        {"body": {"nos": ["TEST"]}},
        settings=settings,
    )
    assert not result.is_error
    assert str(requests[0].url) == (
        "https://custom.example.invalid/api/lmsservice/openapi/queryTracks"
    )


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("link_lms_query_tracks", {"body": {"nos": ["TEST"] * 31}}),
        ("link_lms_print", {"body": {"no": "TEST", "noType": 1, "type": 100, "copyCount": 11}}),
        ("link_finance_query_price", {"body": {"weight": "secret-invalid-input"}}),
        ("link_lms_query_tracks", {"body": {"nos": ["TEST"]}, "result_limit": 101}),
        ("link_edge_push_post", {"body": "{}", "headers": {"serviceCode": "TEST"}}),
        ("link_lms_query_tracks", {"body": {"nos": ["TEST"]}, "arbitrary": "secret-invalid-input"}),
        (
            "link_lms_query_tracks",
            {
                "body": {"nos": ["TEST"]},
                "headers": {"linkToken": "secret-invalid-input"},
            },
        ),
    ],
)
def test_invalid_arguments_never_send_requests(name, arguments):
    result, requests = call_mock(name, arguments)
    assert result.is_error
    assert not requests
    assert result.structured_content["error"]["kind"] == "validation_error"
    assert "secret-invalid-input" not in result.content[0].text


def test_nested_required_field_is_validated():
    operation = CATALOG.operations["link_pds_order"]
    arguments = minimal_instance(operation.request_schema)
    del arguments["body"]["pieces"][0]["weight"]
    result, requests = call_mock(operation.tool_name, arguments)
    assert result.is_error
    assert not requests
    assert "body.pieces.0" in result.content[0].text
    assert "weight" in result.content[0].text


def test_missing_credentials_and_missing_customer_key():
    result, requests = call_mock(
        "link_lms_query_tracks", {"body": {"nos": ["TEST"]}}, settings=Settings()
    )
    assert result.structured_content["error"]["kind"] == "missing_token"
    assert not requests
    result, requests = call_mock(
        "link_finance_balance",
        {"body": {}},
        settings=Settings(token="fixture-token"),
    )
    assert result.structured_content["error"]["kind"] == "validation_error"
    assert not requests


@pytest.mark.parametrize(
    "status,kind",
    [
        (401, "authentication_error"),
        (403, "authentication_error"),
        (429, "rate_limited"),
        (500, "http_error"),
        (302, "http_error"),
    ],
)
def test_http_errors_never_follow_redirects(status, kind):
    result, requests = call_mock(
        "link_lms_query_tracks",
        {"body": {"nos": ["TEST"]}},
        handler=lambda request: httpx.Response(
            status, headers={"Location": "https://other.invalid"}
        ),
    )
    assert result.is_error
    assert len(requests) == 1
    assert result.structured_content["error"]["kind"] == kind


@pytest.mark.parametrize(
    "content",
    [b"<html>login</html>", b'{"data":NaN}', b'{"data":1e400}', b"not-json"],
)
def test_non_json_response_is_actionable(content):
    result, _ = call_mock(
        "link_lms_query_tracks",
        {"body": {"nos": ["TEST"]}},
        handler=lambda request: httpx.Response(200, content=content),
    )
    assert result.is_error
    assert result.structured_content["error"]["kind"] == "invalid_response"


def test_business_error_and_secrets_redacted():
    result, _ = call_mock(
        "link_finance_balance",
        {"body": {}},
        handler=lambda request: httpx.Response(
            200,
            json={
                "code": 1001,
                "msg": "denied fixture-token fixture-customer-key",
                "data": None,
            },
        ),
    )
    assert result.is_error
    assert result.structured_content["result"]["code"] == 1001
    assert "fixture-token" not in result.content[0].text
    assert "fixture-customer-key" not in result.content[0].text


def test_response_pagination_preserves_envelope_and_does_not_send_options():
    result, requests = call_mock(
        "link_lms_query_tracks",
        {"body": {"nos": ["TEST"]}, "result_offset": 2, "result_limit": 2},
        handler=lambda request: httpx.Response(
            200, json={"code": 0, "data": list(range(7)), "msg": "ok"}
        ),
    )
    assert result.structured_content["result"] == {"code": 0, "data": [2, 3], "msg": "ok"}
    assert result.structured_content["pagination"]["next_offset"] == 4
    assert result.structured_content["pagination"]["total"] == 7
    assert json.loads(requests[0].content) == {"nos": ["TEST"]}


def test_size_limit_and_truncation_are_explicit():
    result, _ = call_mock(
        "link_finance_balance",
        {"body": {}},
        settings=Settings(
            token="fixture-token", customer_key="fixture-key", max_response_bytes=1024
        ),
        handler=lambda request: httpx.Response(200, content=b"x" * 1025),
    )
    assert result.structured_content["error"]["kind"] == "response_too_large"
    result, _ = call_mock(
        "link_finance_balance",
        {"body": {}, "response_format": "markdown"},
        settings=Settings(
            token="fixture-token", customer_key="fixture-key", max_response_characters=2000
        ),
        handler=lambda request: httpx.Response(200, json={"code": 0, "data": "\n" * 10000}),
    )
    assert result.structured_content["truncated"]
    assert len(result.content[0].text) <= 2000
    assert result.content[0].text.startswith("```json")


def test_short_secret_redaction_cannot_corrupt_json_numbers():
    runtime = Runtime(Settings(token="0"), CATALOG)
    result = runtime._result({"code": 0, "value": "prefix0suffix"})
    assert result.structured_content == {"code": 0, "value": "prefix[REDACTED]suffix"}


def test_write_timeout_is_not_retried():
    def timeout(request):
        raise httpx.ReadTimeout("fixture", request=request)

    operation = CATALOG.operations["link_lms_express_order"]
    result, requests = call_mock(
        operation.tool_name, minimal_instance(operation.request_schema), timeout
    )
    assert result.is_error
    assert len(requests) == 1
    assert result.structured_content["error"]["kind"] == "timeout"
    assert "可能已生效" in result.content[0].text


def test_local_document_tools_work_without_credentials():
    runtime = Runtime(Settings(), CATALOG)

    async def run():
        services = await runtime.call("link_list_services", {})
        assert services.structured_content["result"]["api_count"] == 27
        assert not services.structured_content["result"]["token_configured"]
        search = await runtime.call("link_search_apis", {"query": "查价"})
        assert search.structured_content["result"]["total"] == 1
        describe = await runtime.call("link_describe_api", {"tool_name": "link_lms_print"})
        assert describe.structured_content["result"]["summary"] == "打印文件"
        unknown = await runtime.call("link_describe_api", {"tool_name": "unknown"})
        assert unknown.is_error

    asyncio.run(run())


@pytest.mark.parametrize("name", list(CATALOG.operations))
def test_every_document_description_fits_default_response_limit(name):
    result = asyncio.run(
        Runtime(Settings(), CATALOG).call(
            "link_describe_api",
            {"tool_name": name},
        )
    )
    assert not result.is_error
    assert not result.structured_content.get("truncated", False)
    assert result.structured_content["result"]["response_schemas"]
