"""命令行入口；stdio 协议输出不得混入日志。"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from pydantic import ValidationError

from .config import Settings
from .server import create_server


async def run_stdio(server: Server) -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main(default_env_file: Path | None = None) -> None:
    parser = argparse.ArgumentParser(description="链路 ERP MCP 服务")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP 监听地址，默认仅本机")
    parser.add_argument("--port", type=int, default=8000, help="HTTP 端口，默认 8000")
    parser.add_argument("--env-file", type=Path, default=default_env_file or Path.cwd() / ".env")
    args = parser.parse_args()
    load_dotenv(args.env_file, override=False)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    # Neither request URLs nor HTTP header values should be emitted by debug loggers.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        server = create_server(Settings.from_env())
    except ValidationError as error:
        # Pydantic's default str(error) includes input values; do not print credentials.
        fields = ", ".join(".".join(str(part) for part in item["loc"]) for item in error.errors())
        parser.exit(2, f"配置无效，请检查：{fields}\n")
    except ValueError as error:
        parser.exit(2, str(error) + "\n")
    try:
        if args.transport == "stdio":
            asyncio.run(run_stdio(server))
        else:
            import uvicorn

            app = server.streamable_http_app(
                host=args.host, json_response=True, stateless_http=True
            )
            uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
