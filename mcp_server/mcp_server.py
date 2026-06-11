import asyncio
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP
import json
from config.config import load_config
from pkg.service.tool import get_default_tool_service
from config.log import setup_logger

logger = setup_logger()
load_config()


@asynccontextmanager
async def app_lifespan(mcp: FastMCP):
    # --- 启动部分 (Startup) ---

    try:
        yield  # 这里是服务运行期间
    except BaseException as e:
        logger.error(f"Server Exiting...", stack_info=True)
    finally:
        # --- 关闭部分 (Shutdown) ---
        pass


def run_server():
    # 配置与初始化
    conf = load_config()
    mcp = FastMCP(
        "Clock In mcp server",
        host="0.0.0.0",
        port=conf.app.port+10,
        lifespan=app_lifespan,
    )

    tool_service = get_default_tool_service()
    # 动态注册：遍历你 service 里的每一个工具
    for tool_info in tool_service.list():
        func = tool_service.get(tool_info.name)
        mcp.add_tool(fn=func, name=tool_info.name, description=tool_info.description)

    mcp.run(transport="sse")


if __name__ == "__main__":
    run_server()
