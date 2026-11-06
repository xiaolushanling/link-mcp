"""异步 API 客户端；固定网关、无自动重试、无跨域重定向。"""

import json
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

import httpx

from .catalog import Operation
from .config import Settings


class ApiError(Exception):
    def __init__(self, kind: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status


class LinkClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self.settings = settings
        self.http = http

    async def request(self, operation: Operation, arguments: dict[str, Any]) -> tuple[int, Any]:
        token = self.settings.token.get_secret_value()
        if not token.strip():
            raise ApiError(
                "missing_token", "请在 .env 或进程环境变量中配置 LINK_TOKEN 后重启服务。"
            )
        path = operation.path
        for name, value in arguments.get("path_params", {}).items():
            path = path.replace("{" + name + "}", quote(str(value), safe=""))
        headers = {"Accept": "application/json", "linkToken": token}
        headers.update(arguments.get("headers", {}))
        # A caller cannot override authentication through a differently cased header.
        if sum(name.lower() == "linktoken" for name in headers) != 1:
            raise ApiError("invalid_headers", "linkToken 只能通过 LINK_TOKEN 配置。")
        kwargs: dict[str, Any] = {"headers": headers, "params": arguments.get("query")}
        if operation.content_type:
            headers["Content-Type"] = operation.content_type
        if "body" in arguments:
            if operation.raw_body:
                kwargs["content"] = arguments["body"].encode("utf-8")
            else:
                kwargs["json"] = arguments["body"]
        try:
            async with self.http.stream(
                operation.method,
                self.settings.api_base_url + operation.context_path + path,
                timeout=self.settings.timeout_seconds,
                follow_redirects=False,
                **kwargs,
            ) as response:
                status = response.status_code
                if status in {401, 403}:
                    raise ApiError(
                        "authentication_error",
                        "接口拒绝访问，请检查 LINK_TOKEN 对应环境、有效期及接口权限。",
                        status,
                    )
                if status == 429:
                    raise ApiError("rate_limited", "接口限流，请稍后按服务端限制重试。", status)
                if not 200 <= status < 300:
                    raise ApiError(
                        "http_error", "接口返回非成功 HTTP 状态，请检查环境和接口路径。", status
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self.settings.max_response_bytes:
                        raise ApiError(
                            "response_too_large",
                            "响应超过 LINK_MAX_RESPONSE_BYTES，请缩小查询范围或调整配置。",
                            status,
                        )
        except httpx.TimeoutException as error:
            message = "接口请求超时，请检查连接或调整 LINK_TIMEOUT_SECONDS。"
            if not operation.read_only:
                message += "写操作可能已生效，请先查询业务状态，避免重复下单或扣费。"
            raise ApiError("timeout", message) from error
        except (httpx.RequestError, httpx.InvalidURL, UnicodeError, ValueError) as error:
            raise ApiError(
                "network_error", "无法完成接口请求，请检查网络、网关地址及请求头格式。"
            ) from error
        if not body:
            return status, None
        try:

            def reject_constant(value: str) -> None:
                raise ValueError("JSON 不允许非有限数值")

            def finite_float(value: str) -> float:
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError("JSON 数字超出有限浮点范围")
                return number

            return status, json.loads(
                body, parse_constant=reject_constant, parse_float=finite_float
            )
        except (ValueError, UnicodeError) as error:
            raise ApiError(
                "invalid_response",
                "接口未返回文档声明的 JSON，请检查网关是否返回登录页或代理错误。",
                status,
            ) from error


@asynccontextmanager
async def open_client(settings: Settings) -> AsyncIterator[LinkClient]:
    async with httpx.AsyncClient(
        follow_redirects=False,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    ) as http:
        yield LinkClient(settings, http)
