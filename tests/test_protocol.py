import asyncio
import os
import socket
import sys
from pathlib import Path

import uvicorn
from mcp import Client, StdioServerParameters

from link_mcp.config import Settings
from link_mcp.server import create_server


async def check_protocol(client):
    tools = await client.list_tools()
    assert len(tools.tools) == 30
    assert "link_lms_query_tracks" in {tool.name for tool in tools.tools}
    result = await client.call_tool("link_search_apis", {"query": "轨迹"})
    assert not result.is_error
    assert result.structured_content["result"]["items"][0]["tool_name"] == "link_lms_query_tracks"
    invalid = await client.call_tool("link_lms_query_tracks", {"body": {"nos": "wrong-type"}})
    assert invalid.is_error
    missing_token = await client.call_tool("link_lms_query_tracks", {"body": {"nos": ["TEST"]}})
    assert missing_token.is_error
    assert missing_token.structured_content["error"]["kind"] == "missing_token"
    resources = await client.list_resources()
    assert len(resources.resources) == 28
    document = await client.read_resource("link://api/link_lms_query_tracks")
    assert "nos" in document.contents[0].text


def test_in_process_mcp_lifecycle():
    async def run():
        async with Client(create_server(Settings()), raise_exceptions=True) as client:
            await check_protocol(client)

    asyncio.run(asyncio.wait_for(run(), timeout=20))


def test_stdio_subprocess_handshake_from_another_directory(tmp_path):
    root = Path(__file__).resolve().parents[1]
    environment = {
        **os.environ,
        "LINK_TOKEN": "",
        "LINK_CUSTOMER_KEY": "",
        "LINK_SERVICES": "",
        "LINK_READ_ONLY": "false",
        "PYTHONIOENCODING": "utf-8",
    }
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(root / "server.py"), "--env-file", str(tmp_path / "absent.env")],
        cwd=tmp_path,
        env=environment,
    )

    async def run():
        async with Client(parameters) as client:
            await check_protocol(client)

    asyncio.run(asyncio.wait_for(run(), timeout=25))


def test_streamable_http_lifecycle():
    async def run():
        application = create_server(Settings()).streamable_http_app(
            host="127.0.0.1",
            json_response=True,
            stateless_http=True,
        )
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            port = listener.getsockname()[1]
            http_server = uvicorn.Server(
                uvicorn.Config(
                    application,
                    log_level="critical",
                    access_log=False,
                )
            )
            task = asyncio.create_task(http_server.serve(sockets=[listener]))
            try:
                for _ in range(200):
                    if http_server.started or task.done():
                        break
                    await asyncio.sleep(0.025)
                assert http_server.started
                async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                    await check_protocol(client)
            finally:
                http_server.should_exit = True
                await asyncio.wait_for(task, timeout=10)

    asyncio.run(asyncio.wait_for(run(), timeout=25))
