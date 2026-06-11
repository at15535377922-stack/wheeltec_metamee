from mcp.server.fastmcp import FastMCP
import json
from config.config import load_config
from pkg.service.tool import get_default_tool_service

# 配置与初始化
conf = load_config()
mcp = FastMCP("Smart-Service", host="0.0.0.0", port=conf.app.port)
service = get_default_tool_service()

# 动态注册：遍历你 service 里的每一个工具
for tool_info in service.list():
    # tool_info 应该是包含 name, description 的对象

    # 获取原始函数
    func = service.get(tool_info.name)

    # 关键点：使用 add_tool 直接注册函数
    # FastMCP 会读取 func 的类型提示（例如 a: int, b: str）生成正确的 properties
    mcp.add_tool(fn=func, name=tool_info.name, description=tool_info.description)
if __name__ == "__main__":
    mcp.run(transport="sse")
