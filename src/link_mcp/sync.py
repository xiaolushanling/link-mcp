"""手动同步官网 OpenAPI；仅 GET 文档，不发送业务请求。"""

import argparse
import asyncio
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from jsonschema.exceptions import SchemaError

from .catalog import Catalog
from .config import Settings


def document_url(api_base_url: str, value: str) -> str:
    base = urlsplit(api_base_url)
    if value.startswith("/api/"):
        target = f"{base.scheme}://{base.netloc}{value}"
    elif value.startswith(("http://", "https://")):
        target = value
    else:
        target = api_base_url + "/" + value.lstrip("/")
    parsed = urlsplit(target)
    if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
        raise ValueError("Swagger 文档必须与配置的网关同源")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("文档 URL 不得携带查询参数、凭证或片段")
    return target


def render_tool_index(catalog: Catalog) -> str:
    lines = [
        "# 接口工具目录",
        "",
        "从官网 OpenAPI 快照生成。实际字段以 `link_describe_api` 返回的定义为准。",
        "",
        "| 服务 | MCP 工具 | 用途 | 只读 | HTTP 路径 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for operation in catalog.operations.values():
        lines.append(
            f"| {operation.service_name} | `{operation.tool_name}` | {operation.summary} | "
            f"{'是' if operation.read_only else '否'} | "
            f"`{operation.method} {operation.context_path}{operation.path}` |"
        )
    lines.extend(
        [
            "",
            "另有 `link_list_services`、`link_search_apis`、`link_describe_api` 三个本地文档工具。",
            "",
            "只读按业务语义列举。打印、运费试算及第三方登录可能触发服务端流程，按非只读保守标注。",
            "",
        ]
    )
    return "\n".join(lines)


async def sync_documents(api_base_url: str, data_dir: Path) -> Catalog:
    api_base_url = Settings(api_base_url=api_base_url).api_base_url
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
        config_response = await client.get(api_base_url + "/v3/api-docs/swagger-config")
        config_response.raise_for_status()
        services = config_response.json().get("urls", [])
        if not services:
            raise ValueError("Swagger 配置中没有服务")
        with tempfile.TemporaryDirectory(prefix="link-mcp-sync-", dir=data_dir.parent) as temporary:
            staging = Path(temporary)

            async def fetch(service: dict) -> dict:
                context_path = service["contextPath"]
                if not re.fullmatch(r"/[a-zA-Z0-9_-]+", context_path):
                    raise ValueError("服务 contextPath 格式无效")
                identifier = context_path.strip("/").removesuffix("service")
                url = document_url(api_base_url, service["url"])
                response = await client.get(url)
                response.raise_for_status()
                document = response.json()
                if not str(document.get("openapi", "")).startswith("3."):
                    raise ValueError("需要 OpenAPI 3.x 文档")
                if not document.get("paths"):
                    raise ValueError("接口文档 paths 为空")
                filename = identifier + ".json"
                staging.joinpath(filename).write_text(
                    json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                return {
                    "id": identifier,
                    "name": service.get("name", identifier),
                    "context_path": context_path,
                    "document_url": url,
                    "file": filename,
                }

            metadata = await asyncio.gather(*(fetch(service) for service in services))
            if len({item["id"] for item in metadata}) != len(metadata):
                raise ValueError("Swagger 中存在重复服务")
            manifest = {
                "source_url": api_base_url.removesuffix("/api") + "/doc/index.html",
                "api_base_url": api_base_url,
                "snapshot_date": datetime.now(UTC).date().isoformat(),
                "services": metadata,
            }
            staging.joinpath("manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            # Do not overwrite a working snapshot unless every document parses and validates.
            catalog = Catalog(staging)
            data_dir.mkdir(parents=True, exist_ok=True)
            for item in metadata:
                os.replace(staging / item["file"], data_dir / item["file"])
            os.replace(staging / "manifest.json", data_dir / "manifest.json")
            return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="同步链路官网 Swagger 文档（只读请求）")
    parser.add_argument("--api-base-url", default="https://demo.linkl.com.cn/api")
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).with_name("data"))
    parser.add_argument("--tools-file", type=Path, help="可选：同时生成 Markdown 工具目录")
    args = parser.parse_args()
    try:
        catalog = asyncio.run(sync_documents(args.api_base_url, args.data_dir))
    except (httpx.HTTPError, ValueError, KeyError, SchemaError) as error:
        # Do not print request objects or arbitrary remote error responses.
        parser.exit(
            1, f"同步失败（{type(error).__name__}），请检查文档地址与网络，原快照未替换。\n"
        )
    if args.tools_file:
        args.tools_file.parent.mkdir(parents=True, exist_ok=True)
        args.tools_file.write_text(render_tool_index(catalog), encoding="utf-8")
    print(
        f"已同步 {len(catalog.manifest['services'])} 个服务、"
        f"{len(catalog.operations)} 个接口；请重启 MCP。"
    )


if __name__ == "__main__":
    main()
