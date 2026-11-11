"""客户可用能力的显式名单；新接口不会自动进入客户配置。"""

import copy
from typing import Any

from mcp.types import Tool

CUSTOMER_TOOLS = frozenset(
    {
        "link_user_get_receive_warehouse",
        "link_user_get_owms_warehouse",
        "link_lms_upload_no",
        "link_lms_upload_file",
        "link_lms_special_line_order",
        "link_lms_query_tracks",
        "link_lms_print",
        "link_lms_order_detail",
        "link_lms_express_order",
        "link_lms_delete_order",
        "link_pds_print",
        "link_pds_order",
        "link_pds_order_detail",
        "link_pds_order_by_cal_price",
        "link_pds_cancel",
        "link_pds_cal_price",
        "link_finance_query_price",
        "link_finance_fetch_available_products",
        "link_finance_balance",
        "link_basicdata_validate_remote",
        "link_basicdata_validate_address",
        "link_basicdata_city_post_code_search",
    }
)


def customer_tool(tool: Tool) -> Tool:
    """Hide the bound identity from the public schema without changing the upstream schema."""
    schema = copy.deepcopy(tool.input_schema)
    body = schema.get("properties", {}).get("body", {})
    while "$ref" in body:
        target: Any = schema
        for part in body["$ref"][2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        body = target
    if "customerKey" in body.get("properties", {}):
        del body["properties"]["customerKey"]
        body["required"] = [key for key in body.get("required", []) if key != "customerKey"]
        body.setdefault("allOf", []).append({"not": {"required": ["customerKey"]}})
    return tool.model_copy(
        update={
            "input_schema": schema,
            "description": (tool.description or "")
            + "客户身份由连接器固定注入，不接受通过对话传入或切换 customerKey。",
        }
    )
