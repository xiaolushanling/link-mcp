"""将官网 OpenAPI 快照转换为独立 MCP 工具的 JSON Schema。"""

import copy
import json
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from mcp.types import Tool, ToolAnnotations

METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}
SCHEMA_PREFIX = "#/components/schemas/"
# 按业务语义列举；POST 不能用于推断是否只读。
READ_ONLY_OPERATIONS = {
    ("user", "getReceiveWarehouse"),
    ("user", "getOwmsWarehouse"),
    ("lms", "queryTracks"),
    ("lms", "orderDetail"),
    ("pds", "orderDetail"),
    ("finance", "queryPrice"),
    ("finance", "fetchAvailableProducts"),
    ("finance", "balance"),
    ("basicdata", "validateRemote"),
    ("basicdata", "validateAddress"),
    ("basicdata", "cityPostCodeSearch"),
}


def snake_case(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")


def resolve_reference(document: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    """Resolve local OpenAPI object references (parameters/requestBody/responses)."""
    seen: set[str] = set()
    while "$ref" in value:
        ref = value["$ref"]
        if not ref.startswith("#/") or ref in seen:
            raise ValueError("OpenAPI 对象引用必须是无循环的文档内部引用")
        seen.add(ref)
        target = document
        for part in ref[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        value = target
    return value


def schema_bundle(schema: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    """Convert OAS 3.0 schemas and retain only the transitive local $defs needed.

    Keeping references rather than expanding them also supports recursive models.
    Example/default payloads are copied verbatim, never interpreted as schemas.
    """
    definitions: dict[str, Any] = {}

    def convert(value: Any) -> Any:
        if not isinstance(value, dict):
            return copy.deepcopy(value)
        result = copy.deepcopy(value)
        ref = result.get("$ref")
        if ref:
            if not ref.startswith(SCHEMA_PREFIX):
                raise ValueError("仅支持文档内部 components/schemas 引用")
            key = ref[len(SCHEMA_PREFIX) :].replace("~1", "/").replace("~0", "~")
            result["$ref"] = "#/$defs/" + ref[len(SCHEMA_PREFIX) :]
            if key not in definitions:
                definitions[key] = {}  # Mark before descending into a recursive definition.
                definitions[key] = convert(document["components"]["schemas"][key])
        for key in ("properties", "patternProperties", "$defs"):
            if isinstance(result.get(key), dict):
                result[key] = {name: convert(child) for name, child in result[key].items()}
        for key in ("items", "additionalProperties", "not", "contains", "if", "then", "else"):
            if isinstance(result.get(key), dict):
                result[key] = convert(result[key])
        for key in ("allOf", "oneOf", "anyOf", "prefixItems"):
            if isinstance(result.get(key), list):
                result[key] = [convert(child) for child in result[key]]
        for keyword, bound in (("exclusiveMinimum", "minimum"), ("exclusiveMaximum", "maximum")):
            if isinstance(result.get(keyword), bool):
                exclusive = result.pop(keyword)
                if exclusive and bound in result:
                    result[keyword] = result.pop(bound)
        if result.pop("nullable", False):
            result = {"anyOf": [result, {"type": "null"}]}
        return result

    bundled = convert(schema)
    if definitions:
        bundled["$defs"] = definitions
    return bundled


def object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


@dataclass(frozen=True)
class Operation:
    service: str
    service_name: str
    context_path: str
    method: str
    path: str
    operation_id: str
    summary: str
    description: str
    input_schema: dict[str, Any]
    request_schema: dict[str, Any]
    response_schemas: dict[str, Any]
    content_type: str | None
    raw_body: bool
    read_only: bool
    accepts_customer_key: bool

    @property
    def tool_name(self) -> str:
        return f"link_{self.service}_{snake_case(self.operation_id)}"

    def summary_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "service": self.service,
            "service_name": self.service_name,
            "summary": self.summary,
            "method": self.method,
            "path": self.context_path + self.path,
            "read_only": self.read_only,
        }

    def describe(self) -> dict[str, Any]:
        return {
            **self.summary_dict(),
            "operation_id": self.operation_id,
            "description": self.description,
            "content_type": self.content_type,
            "raw_body": self.raw_body,
            "input_schema": self.input_schema,
            "response_schemas": self.response_schemas,
            "notes": [
                "linkToken 从 LINK_TOKEN 环境变量读取，不作为工具参数。",
                "customerKey 仅在接口定义该字段且调用方省略时从 LINK_CUSTOMER_KEY 补入。",
                "文档只在描述中声明的条件必填、枚举等业务规则仍由接口服务验证。",
            ],
        }

    def to_tool(self) -> Tool:
        description = (
            f"{self.service_name}：{self.summary}。{self.method} {self.context_path}{self.path}。"
        )
        if self.description:
            description += self.description + "。"
        if self.raw_body:
            description += "body 是原始请求文本，按约定格式原样发送，不会再次 JSON 编码。"
        description += (
            "先用 link_describe_api 查看完整请求和响应说明。"
            "result_offset/result_limit 仅对本次响应的顶层数组做本地分页，不是服务端分页。"
            "返回 success/http_status/result；业务 code 非 0 时 isError=true。"
        )
        if not self.read_only:
            description += (
                "此操作可能改变业务数据或触发外部流程，网络超时后先查询状态再决定是否重试。"
            )
        return Tool(
            name=self.tool_name,
            title=f"{self.service_name} · {self.summary}",
            description=description,
            input_schema=self.input_schema,
            annotations=ToolAnnotations(
                read_only_hint=self.read_only,
                destructive_hint=not self.read_only,
                idempotent_hint=self.read_only,
                open_world_hint=True,
            ),
        )


class Catalog:
    def __init__(self, data_dir: Path | None = None) -> None:
        root = data_dir if data_dir is not None else files("link_mcp").joinpath("data")
        self.manifest = json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))
        self.operations: dict[str, Operation] = {}
        for service in self.manifest["services"]:
            document = json.loads(root.joinpath(service["file"]).read_text(encoding="utf-8"))
            for path, item in document.get("paths", {}).items():
                item = resolve_reference(document, item)
                for method, spec in item.items():
                    if method not in METHODS:
                        continue
                    operation = self._build_operation(service, document, path, method, item, spec)
                    if operation.tool_name in self.operations:
                        raise ValueError(f"重复的工具名称：{operation.tool_name}")
                    Draft202012Validator.check_schema(operation.input_schema)
                    Draft202012Validator.check_schema(operation.request_schema)
                    self.operations[operation.tool_name] = operation

    @staticmethod
    def _build_operation(
        service: dict[str, Any],
        document: dict[str, Any],
        path: str,
        method: str,
        item: dict[str, Any],
        spec: dict[str, Any],
    ) -> Operation:
        properties: dict[str, Any] = {}
        required: list[str] = []
        groups: dict[str, dict[str, Any]] = {}
        group_required: dict[str, list[str]] = {}
        locations = {"header": "headers", "query": "query", "path": "path_params"}
        parameters = {}
        for raw in item.get("parameters", []) + spec.get("parameters", []):
            parameter = resolve_reference(document, raw)
            parameters[(parameter["in"], parameter["name"])] = parameter
        for (location, name), parameter in parameters.items():
            if location == "header" and name.lower() == "linktoken":
                continue
            if location not in locations:
                raise ValueError(f"暂不支持参数位置：{location}")
            group = locations[location]
            groups.setdefault(group, {})[name] = {
                **parameter.get("schema", {"type": "string"}),
                "description": parameter.get("description", name),
            }
            if parameter.get("required"):
                group_required.setdefault(group, []).append(name)
        for group, fields in groups.items():
            properties[group] = object_schema(fields, group_required.get(group))
            if group_required.get(group):
                required.append(group)

        request_body = resolve_reference(document, spec.get("requestBody", {}))
        content = request_body.get("content", {})
        content_type = (
            "application/json" if "application/json" in content else next(iter(content), None)
        )
        body_schema = content.get(content_type, {}).get("schema", {})
        resolved_body = resolve_reference(document, body_schema)
        raw_body = resolved_body.get("type") == "string"
        accepts_customer_key = "customerKey" in resolved_body.get("properties", {})
        if content_type:
            properties["body"] = {
                **body_schema,
                "description": request_body.get("description", "按接口定义提供请求体"),
            }
            if raw_body:
                properties["body"]["description"] += "。原样发送文本，不添加 JSON 字符串引号。"
            if request_body.get("required"):
                required.append("body")

        request_schema = schema_bundle(object_schema(properties, required), document)
        public_schema = copy.deepcopy(request_schema)
        if accepts_customer_key:
            public_body = public_schema["properties"]["body"]
            if "$ref" in public_body:
                key = public_body["$ref"].split("/")[-1].replace("~1", "/").replace("~0", "~")
                public_body = public_schema["$defs"][key]
            if "customerKey" in public_body.get("required", []):
                public_body["required"].remove("customerKey")
            public_body["properties"]["customerKey"]["description"] += (
                "；省略时读取 LINK_CUSTOMER_KEY，未配置时仍需传入"
            )
        public_schema["properties"].update(
            {
                "response_format": {
                    "type": "string",
                    "enum": ["json", "markdown"],
                    "default": "json",
                    "description": "返回文本格式；structuredContent 始终为 JSON 对象",
                },
                "result_offset": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "description": "仅对本次响应顶层结果数组做本地切片的起始位置",
                },
                "result_limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                    "description": "本次响应顶层结果数组最多返回条数（本地分页）",
                },
            }
        )
        response_schemas = {}
        for status, raw_response in spec.get("responses", {}).items():
            response = resolve_reference(document, raw_response)
            for media_type, media in response.get("content", {}).items():
                response_schemas[f"{status} {media_type}"] = schema_bundle(
                    media.get("schema", {}), document
                )
        operation_id = spec.get("operationId") or f"{method}_{path}"
        return Operation(
            service=service["id"],
            service_name=service["name"],
            context_path=service["context_path"],
            method=method.upper(),
            path=path,
            operation_id=operation_id,
            summary=spec.get("summary", operation_id),
            description=spec.get("description", ""),
            input_schema=public_schema,
            request_schema=request_schema,
            response_schemas=response_schemas,
            content_type=content_type,
            raw_body=raw_body,
            read_only=(service["id"], operation_id) in READ_ONLY_OPERATIONS,
            accepts_customer_key=accepts_customer_key,
        )
