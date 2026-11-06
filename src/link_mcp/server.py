"""使用官方 Python SDK 2.x，直接注册 OpenAPI 生成的 JSON Schema。"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server import Server, ServerRequestContext
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListResourcesResult,
    ListToolsResult,
    PaginatedRequestParams,
    ReadResourceRequestParams,
    ReadResourceResult,
    Resource,
    TextResourceContents,
)

from . import __version__
from .client import ApiError, LinkClient, open_client
from .config import Settings
from .runtime import Runtime


def create_server(settings: Settings | None = None) -> Server:
    runtime = Runtime(settings or Settings.from_env())

    @asynccontextmanager
    async def lifespan(server: Server) -> AsyncIterator[LinkClient]:
        async with open_client(runtime.settings) as client:
            yield client

    async def list_tools(
        ctx: ServerRequestContext,
        params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        return ListToolsResult(tools=list(runtime.tools.values()))

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        return await runtime.call(params.name, params.arguments or {}, ctx.lifespan_context)

    async def list_resources(
        ctx: ServerRequestContext,
        params: PaginatedRequestParams | None,
    ) -> ListResourcesResult:
        return ListResourcesResult(
            resources=[
                Resource(uri="link://services", name="链路服务目录", mime_type="application/json"),
                *[
                    Resource(
                        uri="link://api/" + operation.tool_name,
                        name=operation.summary,
                        description=operation.tool_name,
                        mime_type="application/json",
                    )
                    for operation in runtime.operations.values()
                ],
            ]
        )

    async def read_resource(
        ctx: ServerRequestContext,
        params: ReadResourceRequestParams,
    ) -> ReadResourceResult:
        uri = str(params.uri)
        if uri == "link://services":
            data = runtime.list_services()
        elif uri.startswith("link://api/"):
            data = runtime.describe(uri.removeprefix("link://api/"))
        else:
            raise ApiError("unknown_resource", "资源不存在，请先调用 resources/list。")
        return ReadResourceResult(
            contents=[
                TextResourceContents(
                    uri=uri,
                    mime_type="application/json",
                    text=json.dumps(data, ensure_ascii=False),
                )
            ]
        )

    return Server(
        name="link_mcp",
        version=__version__,
        title="链路 ERP 开放平台",
        instructions=(
            "先用 link_search_apis 发现接口，再用 link_describe_api 查看字段。"
            "linkToken 由进程配置，oauthLogin 仅做第三方登录。"
            "下单、取消、删除、上传和推送可能影响业务，须符合用户的明确意图。"
            "result_offset/result_limit 是本次响应的本地分页。不要自动重试超时的写操作。"
        ),
        lifespan=lifespan,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_list_resources=list_resources,
        on_read_resource=read_resource,
        get_tool_input_schema=lambda name: (
            runtime.tools[name].input_schema if name in runtime.tools else None
        ),
    )
