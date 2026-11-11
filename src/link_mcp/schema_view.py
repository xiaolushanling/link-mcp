"""按业务字段路径读取大型输入模型，同时保留所需的本地引用。"""

import copy
from typing import Any

from .client import ApiError


def resolve(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    seen: set[str] = set()
    while "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/") or ref in seen:
            raise ApiError("invalid_schema_reference", "模型引用不能解析，请联系服务提供方。")
        seen.add(ref)
        value = root
        for part in ref[2:].split("/"):
            value = value[part.replace("~1", "/").replace("~0", "~")]
        schema = value
    return schema


def field_summaries(root: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for name, schema in root.get("properties", {}).items():
        resolved = resolve(schema, root)
        if name == "body" and resolved.get("properties"):
            for field, definition in resolved["properties"].items():
                rows.append(
                    {
                        "field_path": f"body.{field}",
                        "required": field in resolved.get("required", []),
                        "type": resolve(definition, root).get("type"),
                        "description": definition.get("description", ""),
                    }
                )
        else:
            rows.append(
                {
                    "field_path": name,
                    "required": name in root.get("required", []),
                    "type": resolved.get("type"),
                    "description": schema.get("description", ""),
                }
            )
    return rows


def select_field(root: dict[str, Any], field_path: str) -> dict[str, Any]:
    selected = root
    for part in field_path.split("."):
        array = part.endswith("[]")
        key = part[:-2] if array else part
        selected = resolve(selected, root).get("properties", {}).get(key)
        if not isinstance(selected, dict):
            raise ApiError(
                "unknown_schema_field", "字段不存在；请先用 section=summary 查看字段路径。"
            )
        if array:
            selected = resolve(selected, root).get("items")
            if not isinstance(selected, dict):
                raise ApiError("unknown_schema_field", "该字段不是数组，不能使用 [] 路径。")
    result = copy.deepcopy(resolve(selected, root))
    definitions: dict[str, Any] = {}

    def visit(schema: Any) -> None:
        if not isinstance(schema, dict):
            return
        ref = schema.get("$ref", "")
        if ref.startswith("#/$defs/"):
            key = ref[len("#/$defs/") :].replace("~1", "/").replace("~0", "~")
            if key not in definitions:
                definitions[key] = copy.deepcopy(root["$defs"][key])
                visit(definitions[key])
        for key in ("properties", "patternProperties"):
            for child in schema.get(key, {}).values():
                visit(child)
        for key in ("items", "additionalProperties", "not", "contains", "if", "then", "else"):
            visit(schema.get(key))
        for key in ("allOf", "oneOf", "anyOf", "prefixItems"):
            for child in schema.get(key, []):
                visit(child)

    visit(result)
    if definitions:
        result["$defs"] = definitions
    return result
