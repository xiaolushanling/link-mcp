"""同步公开文档时保留凭证字段结构，但不发布其中的凭证样例和默认值。"""

import json
from typing import Any

SENSITIVE_FIELDS = {
    "customerkey",
    "linktoken",
    "token",
    "password",
    "authorization",
    "appsecret",
    "clientsecret",
    "apikey",
    "accesstoken",
    "refreshtoken",
    "privatekey",
    "secret",
}
EXAMPLE_FIELDS = {"example", "examples", "default"}


def sensitive(name: str) -> bool:
    return name.casefold().replace("_", "").replace("-", "") in SENSITIVE_FIELDS


def scrub_credential_examples(value: Any, *, example: bool = False) -> Any:
    """Return a copy; handle schemas, header parameters and structured JSON examples."""
    if isinstance(value, list):
        return [scrub_credential_examples(child, example=example) for child in value]
    if isinstance(value, str) and example and value.lstrip().startswith(("{", "[")):
        try:
            payload = json.loads(value)
        except ValueError:
            return value
        return json.dumps(scrub_credential_examples(payload, example=True), ensure_ascii=False)
    if not isinstance(value, dict):
        return value
    result = {
        key: scrub_credential_examples(child, example=example or key in EXAMPLE_FIELDS)
        for key, child in value.items()
        if not (example and sensitive(key))
    }
    properties = result.get("properties", {})
    for name, field in properties.items() if isinstance(properties, dict) else ():
        if sensitive(name) and isinstance(field, dict):
            for marker in EXAMPLE_FIELDS:
                field.pop(marker, None)
    if isinstance(result.get("name"), str) and sensitive(result["name"]):
        for container in (result, result.get("schema", {})):
            if isinstance(container, dict):
                for marker in EXAMPLE_FIELDS:
                    container.pop(marker, None)
    return result
