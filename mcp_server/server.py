import inspect
import json
import sys
import anyio
import logging
import traceback
import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import os
import uvicorn
import mcp.types as types
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route
from pkg.service.tool import get_default_tool_service
import logging
from config.config import load_config
from config.log import setup_logger


logging.basicConfig(
    # level=logging.CRITICAL,
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)


logger = logging.getLogger(__file__)


@asynccontextmanager
async def lifespan(server: Server) -> AsyncIterator[dict]:
    """初始化配置和释放资源"""
    try:
        setup_logger()
        yield {}
    finally:
        pass


server = Server("", lifespan=lifespan)
sse = SseServerTransport("/messages/")


async def handle_sse(request):
    """处理sse请求"""
    try:
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0], streams[1], server.create_initialization_options()
            )
    except asyncio.exceptions.CancelledError:
        pass
    except anyio.WouldBlock:
        pass
    except Exception as e:
        logger.error(traceback.format_exc())


async def handle_messages(request):
    try:
        await sse.handle_post_message(request.scope, request.receive, request._send)
    except Exception as e:
        logger.error(traceback.format_exc())


@server.list_tools()
async def list_tools():
    ctx = server.request_context
    # client_mysql = ctx.lifespan_context.get("","")
    return get_default_tool_service().list()


@server.call_tool()
async def call_tool(name, args):
    try:
        tool_func = get_default_tool_service().get(name)
        if tool_func:
            result_text = tool_func(**args)

        else:
            result_text = f"Tool function {name} not found"
    except Exception as e:
        logger.error(traceback.format_exc())
        result_text = f"Error: {str(e)}"
    text = json.dumps({"data": result_text})

    return [types.TextContent(type="text", text=text)]


@server.list_resources()
async def list_resources():
    """定义一些资源"""
    return [
        # types.Resource(
        #     uri='file:///doc01/file03.png',
        #     name="文档03",
        #     description="文档03",
        #     mimeType="image/png",
        #     size=10 * 1024 * 1024
        # ),
    ]


@server.read_resource()
async def read_resource(uri):
    raise ValueError("Resource not found")


if __name__ == "__main__":
    starlette_app = Starlette(
        debug=True,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/messages/", endpoint=handle_messages, methods=["POST"]),
        ],
    )
    uvicorn.run(starlette_app, host="0.0.0.0", port=load_config().app.port)
