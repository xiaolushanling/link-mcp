"""工具分发、参数验证、业务错误及输出格式。"""

import copy
import json
from typing import Any

from jsonschema import Draft202012Validator, ValidationError
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

from .catalog import Catalog, object_schema
from .client import ApiError, LinkClient
from .config import Settings
from .profiles import CUSTOMER_TOOLS, customer_tool
from .schema_view import field_summaries, select_field


def validation_message(error: ValidationError) -> str:
    """Report schema paths, never the invalid instance (it may contain a password)."""
    path = ".".join(str(part) for part in error.absolute_path) or "arguments"
    if error.validator == "required" and isinstance(error.instance, dict):
        missing = [name for name in error.validator_value if name not in error.instance]
        reason = "缺少必填字段：" + ", ".join(missing)
    elif error.validator == "additionalProperties":
        reason = "包含接口未定义的参数，请核对 input_schema"
    else:
        reason = f"不满足 {error.validator} 约束，请核对 input_schema"
    return f"{path}：{reason}。可调用 link_describe_api 查看完整定义。"


def page_result(result: Any, offset: int, limit: int) -> tuple[Any, dict[str, Any] | None]:
    """Slice only an actual top-level result array; no invented upstream pagination."""
    items = result if isinstance(result, list) else None
    if isinstance(result, dict) and isinstance(result.get("data"), list):
        items = result["data"]
    if items is None:
        return result, None
    page = items[offset : offset + limit]
    next_offset = offset + len(page) if offset + len(page) < len(items) else None
    pagination = {
        "mode": "local_response",
        "total": len(items),
        "offset": offset,
        "count": len(page),
        "has_more": next_offset is not None,
        "next_offset": next_offset,
    }
    return ({**result, "data": page} if isinstance(result, dict) else page), pagination


class Runtime:
    def __init__(self, settings: Settings, catalog: Catalog | None = None) -> None:
        self.settings = settings
        self.catalog = catalog or Catalog()
        known = {service["id"] for service in self.catalog.manifest["services"]}
        if set(settings.services) - known:
            raise ValueError("LINK_SERVICES 包含未知服务；可用值：" + ",".join(sorted(known)))
        self.operations = {
            name: operation
            for name, operation in self.catalog.operations.items()
            if (not settings.services or operation.service in settings.services)
            and (not settings.read_only or operation.read_only)
            and (settings.profile != "customer" or name in CUSTOMER_TOOLS)
        }
        self.tools = {name: operation.to_tool() for name, operation in self.operations.items()}
        if settings.profile == "customer":
            self.tools = {name: customer_tool(tool) for name, tool in self.tools.items()}
        for tool in self._helper_tools():
            self.tools[tool.name] = tool
        self.validators = {
            name: Draft202012Validator(tool.input_schema) for name, tool in self.tools.items()
        }
        self.request_validators = {
            name: Draft202012Validator(operation.request_schema)
            for name, operation in self.operations.items()
        }

    @staticmethod
    def _helper_tools() -> list[Tool]:
        definitions = [
            (
                "link_list_services",
                "查看服务和配置状态",
                "列出可用服务、接口数量及凭证是否配置；不返回凭证。",
                {},
            ),
            (
                "link_search_apis",
                "查找接口",
                "按中文用途、工具名或路径查找接口。仅读本地文档，无需凭证。",
                {
                    "query": {
                        "type": "string",
                        "default": "",
                        "description": "如：查价、轨迹、取消",
                    },
                    "service": {"type": "string", "description": "服务代码，如 lms、pds、finance"},
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                },
            ),
            (
                "link_describe_api",
                "查看完整接口定义",
                "查看工具的请求字段、必填约束及响应结构。仅读本地文档，无需凭证。",
                {
                    "tool_name": {
                        "type": "string",
                        "description": "link_search_apis 返回的完整 tool_name",
                    },
                    "section": {
                        "type": "string",
                        "enum": ["all", "summary", "input", "responses"],
                        "default": "all",
                        "description": "大型模型先用 summary 查看字段，"
                        "再用 input 和 field_path 获取约束",
                    },
                    "field_path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 500,
                        "description": "仅 section=input 时使用，如 body.recipient、body.pieces[]",
                    },
                },
            ),
        ]
        return [
            Tool(
                name=name,
                title=title,
                description=description,
                input_schema=object_schema(
                    properties, ["tool_name"] if name == "link_describe_api" else []
                ),
                annotations=ToolAnnotations(
                    read_only_hint=True,
                    destructive_hint=False,
                    idempotent_hint=True,
                    open_world_hint=False,
                ),
            )
            for name, title, description, properties in definitions
        ]

    def list_services(self) -> dict[str, Any]:
        return {
            "source_url": self.catalog.manifest["source_url"],
            "snapshot_date": self.catalog.manifest.get("snapshot_date"),
            "api_base_url": self.settings.api_base_url,
            "profile": self.settings.profile,
            "customer_identity_locked": self.settings.profile == "customer",
            "read_only": self.settings.read_only,
            "token_configured": bool(self.settings.token.get_secret_value().strip()),
            "customer_key_configured": bool(self.settings.customer_key.get_secret_value()),
            "api_count": len(self.operations),
            "tool_count": len(self.tools),
            "services": [
                {
                    "id": service["id"],
                    "name": service["name"],
                    "context_path": service["context_path"],
                    "api_count": sum(
                        op.service == service["id"] for op in self.operations.values()
                    ),
                }
                for service in self.catalog.manifest["services"]
                if not self.settings.services or service["id"] in self.settings.services
            ],
        }

    def describe(self, name: str) -> dict[str, Any]:
        if name not in self.operations:
            raise ApiError(
                "unknown_api", "接口不存在或未启用，请使用 link_search_apis 查找可用工具。"
            )
        description = self.operations[name].describe()
        if self.settings.profile == "customer":
            description["input_schema"] = self.tools[name].input_schema
            description["notes"] = [
                "客户模式：连接器固定使用配置中的客户身份，不接受工具参数指定 customerKey。",
                "网关和凭证在客户端的安全配置中设置，不要在会话中提供凭证。",
                "上游仍须验证凭证权限及运单归属；本模式不替代业务服务的权限校验。",
            ]
        return description

    def _local_call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "link_list_services":
            return self.list_services()
        if name == "link_describe_api":
            description = self.describe(arguments["tool_name"])
            section = arguments.get("section", "all")
            path = arguments.get("field_path")
            if path and section != "input":
                raise ApiError("invalid_section", "field_path 需要同时指定 section=input。")
            if section == "all":
                return description
            result = {
                key: value
                for key, value in description.items()
                if key not in {"input_schema", "response_schemas"}
            }
            if section == "summary":
                result["input_fields"] = field_summaries(description["input_schema"])
                result["response_types"] = list(description["response_schemas"])
            elif section == "input":
                result["input_schema"] = (
                    select_field(description["input_schema"], path)
                    if path
                    else description["input_schema"]
                )
                if path:
                    result["field_path"] = path
            else:
                result["response_schemas"] = description["response_schemas"]
            return result
        query = arguments.get("query", "").casefold()
        service = arguments.get("service")
        items = [
            operation.summary_dict()
            for operation in self.operations.values()
            if (
                (not service or service == operation.service)
                and query
                in " ".join(
                    (
                        operation.tool_name,
                        operation.summary,
                        operation.path,
                        operation.description,
                        operation.service_name,
                    )
                ).casefold()
            )
        ]
        offset, limit = arguments.get("offset", 0), arguments.get("limit", 20)
        return {
            "items": items[offset : offset + limit],
            "total": len(items),
            "offset": offset,
            "has_more": offset + limit < len(items),
            "next_offset": offset + limit if offset + limit < len(items) else None,
        }

    def _result(
        self,
        data: dict[str, Any],
        *,
        is_error: bool = False,
        response_format: str = "json",
    ) -> CallToolResult:
        # Redact configured secrets even if an upstream error echoes them in text.
        secrets = [
            secret.get_secret_value()
            for secret in (
                self.settings.token,
                self.settings.customer_key,
            )
            if secret.get_secret_value()
        ]

        def redact(value: Any) -> Any:
            if isinstance(value, str):
                for secret in secrets:
                    value = value.replace(secret, "[REDACTED]")
                return value
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items()}
            return value

        data = redact(data)
        serialized = json.dumps(data, ensure_ascii=False, allow_nan=False)
        character_budget = self.settings.max_response_characters - (
            12 if response_format == "markdown" else 0
        )
        if len(serialized) > character_budget:
            data = {
                "success": data.get("success", not is_error),
                "truncated": True,
                "message": "响应超过长度限制，以下为文本预览；请缩小查询、降低 result_limit，"
                "或调整 LINK_MAX_RESPONSE_CHARACTERS。写操作不要为获取完整响应而重复执行。",
                "preview": "",
            }
            # Escaped control characters can make the preview larger than the source.
            # A binary search keeps both structuredContent and text within the budget.
            low, high = 0, character_budget
            while low < high:
                middle = (low + high + 1) // 2
                data["preview"] = serialized[:middle]
                if len(json.dumps(data, ensure_ascii=False)) <= character_budget:
                    low = middle
                else:
                    high = middle - 1
            data["preview"] = serialized[:low]
        text = json.dumps(data, ensure_ascii=False)
        if response_format == "markdown":
            text = "```json\n" + text + "\n```"
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=data,
            is_error=is_error,
        )

    async def call(
        self,
        name: str,
        arguments: dict[str, Any],
        client: LinkClient | None = None,
    ) -> CallToolResult:
        try:
            if name not in self.tools:
                raise ApiError("unknown_tool", "工具不存在或未启用，请使用 link_search_apis 查找。")
            if self.settings.profile == "customer" and isinstance(arguments.get("body"), dict):
                if any(str(key).casefold() == "customerkey" for key in arguments["body"]):
                    raise ApiError(
                        "customer_identity_locked",
                        "客户身份由连接器固定配置，请移除 body 中的客户凭证字段。",
                    )
            self.validators[name].validate(arguments)
            if name not in self.operations:
                return self._result({"success": True, "result": self._local_call(name, arguments)})
            operation = self.operations[name]
            if self.settings.profile == "customer" and not (
                self.settings.customer_key.get_secret_value().strip()
            ):
                raise ApiError(
                    "missing_customer_key",
                    "请在客户端安全配置中绑定 LINK_CUSTOMER_KEY 后重新连接；不要在会话中发送凭证。",
                )
            request = copy.deepcopy(
                {
                    key: value
                    for key, value in arguments.items()
                    if key not in {"response_format", "result_offset", "result_limit"}
                }
            )
            if operation.accepts_customer_key and isinstance(request.get("body"), dict):
                configured_key = self.settings.customer_key.get_secret_value()
                if "customerKey" not in request["body"] and configured_key:
                    request["body"]["customerKey"] = configured_key
            self.request_validators[name].validate(request)
            if client is None:
                raise ApiError("client_unavailable", "API 客户端尚未启动，请重新连接 MCP 服务。")
            status, raw_result = await client.request(operation, request)
            business_failure = (
                isinstance(raw_result, dict)
                and "code" in raw_result
                and (type(raw_result["code"]) is not int or raw_result["code"] != 0)
            )
            # Failed results retain all error context; pagination is for successful lists.
            result, pagination = (
                (raw_result, None)
                if business_failure
                else page_result(
                    raw_result,
                    arguments.get("result_offset", 0),
                    arguments.get("result_limit", 20),
                )
            )
            output = {
                "success": not business_failure,
                "service": operation.service,
                "operation": operation.operation_id,
                "http_status": status,
                "result": result,
            }
            if business_failure:
                output["error"] = {
                    "kind": "business_error",
                    "message": "接口业务 code 非 0，请按 result.msg 修正请求。",
                }
            if pagination is not None:
                output["pagination"] = pagination
            return self._result(
                output,
                is_error=business_failure,
                response_format=arguments.get("response_format", "json"),
            )
        except ValidationError as error:
            data = {
                "success": False,
                "error": {"kind": "validation_error", "message": validation_message(error)},
            }
        except ApiError as error:
            data = {
                "success": False,
                "error": {
                    "kind": error.kind,
                    "message": str(error),
                    "http_status": error.status,
                },
            }
        return self._result(data, is_error=True)
