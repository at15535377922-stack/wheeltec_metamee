import sys
import asyncio
import logging
import traceback
from typing import Optional, Union
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client

from pkg.llm.llm import LLMOpenAICompti


logger = logging.getLogger(__name__)


CHAT_MAX_ROUND = 5


@dataclass
class MCPClient:

    llm: Union[LLMOpenAICompti] = None

    # init=False 不在 __init__ 中初始化
    session: Optional[ClientSession] = field(init=False, default=None)
    exit_stack: AsyncExitStack = field(init=False, default=AsyncExitStack())
    tools: list = field(init=False, default=None)
    prompts: list = field(init=False, default=None)
    resources: list = field(init=False, default=None)
    resource_templates: list = field(init=False, default=None)
    server_url: list = field(init=False, default="http://localhost:3000")
    messages: list = field(default_factory=list)
    system_prompt: str = field(init=True, default="简短回答 不要带emoji表情符号等")

    async def get_messages(self):
        if len(self.messages) > 30:
            self.messages.pop(0)  # 一个user
            self.messages.pop(0)  # 一个assistant 应该大部分都不支持 assistant在最前面
        if self.system_prompt:
            messages = [{"role": "system", "content": self.system_prompt}]
            messages.extend(self.messages)
            return messages
        else:
            return self.messages

    async def connect_to_server_by_stdio(self, server_script_path: str):
        """通过stdio的方式通信

        Args:
            server_script_path: mcp server python脚本
        """
        is_python = server_script_path.endswith(".py")
        is_js = server_script_path.endswith(".js")
        if not (is_python or is_js):
            raise ValueError("Server script must be a .py or .js file")

        command = "python" if is_python else "node"
        server_params = StdioServerParameters(
            command=command, args=[server_script_path], env=None
        )

        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(self.stdio, self.write)
        )

        await self.session.initialize()

    async def connect_to_server_by_sse(self, server_url: str):
        """通过sse的方式通信"""
        # async with sse_client(server_url) as streams:
        #     async with ClientSession(streams[0], streams[1]) as self.session:
        #         await self.session.initialize()
        # self.session = session

        # 创建 SSE 客户端连接上下文管理器
        self._streams_context = sse_client(url=server_url)
        # 异步初始化 SSE 连接，获取数据流对象
        streams = await self._streams_context.__aenter__()

        # 使用数据流创建 MCP 客户端会话上下文
        self._session_context = ClientSession(*streams)
        # 初始化客户端会话对象
        self.session: ClientSession = await self._session_context.__aenter__()

        # 执行 MCP 协议初始化握手
        await self.session.initialize()

    async def get_server_resources(self):
        """获取mcp服务器上的资源"""
        list_tools = await self.session.list_tools()
        if list_tools and list_tools.tools:
            await self.handle_mcp_server_tools(list_tools.tools)
        print(f"mcp server tools: {self.tools}")

        list_resources = await self.session.list_resources()
        if list_resources and list_resources.resources:
            await self.handle_mcp_server_resources(list_resources.resources)
        print(f"mcp server resources: {self.resources}")

    async def process_query_by_sse(self, query, resource_uris=None):
        messages = [{"role": "user", "content": query}]

        chat_messages = {"messages": messages, "stream": False}

        if self.tools:
            chat_messages["tools"] = self.tools

        if resource_uris:
            resource_list = []
            if isinstance(resource_uris, str):
                resource_uris = [resource_uris]
            if isinstance(resource_uris, list):
                for uri in resource_uris:
                    resource = await self.session.read_resource(uri)
                    if resource:
                        contents = resource.contents
                        for content in contents:
                            resource_list.append(content.text)

            if resource_list:
                # 将resource添加到messages中
                pass

        curr_round, response = 1, None
        while curr_round <= CHAT_MAX_ROUND:
            response = self.llm.chat_completions(chat_messages)
            if not response:
                continue

            result = await self.llm.handle_completions(
                self.session, response, chat_messages
            )
            if not isinstance(result, dict):
                return result
            else:
                chat_messages = result

            curr_round += 1

        return response

    async def process_query_by_sse_stream(self, query, resource_uris=None):
        previos_messages = await self.get_messages()
        previos_messages.append({"role": "user", "content": query})

        chat_messages = {"messages": previos_messages, "stream": True}

        if self.tools:
            chat_messages["tools"] = self.tools
        """
        if resource_uris:
            resource_list = []
            if isinstance(resource_uris, str):
                resource_uris = [resource_uris]
            if isinstance(resource_uris, list):
                for uri in resource_uris:
                    resource = await self.session.read_resource(uri)
                    if resource:
                        contents = resource.contents
                        for content in contents:
                            resource_list.append(content.text)

            if resource_list:
                # 将resource添加到messages中
                pass
        """
        curr_round, continue_loop = 1, True
        while curr_round <= CHAT_MAX_ROUND and continue_loop:
            response = self.llm.chat_completions(chat_messages)
            if not response:
                continue

            async for result in self.llm.handle_completions_stream(
                self.session, response, chat_messages
            ):
                if not isinstance(result, dict):
                    continue_loop = False
                    yield result
                else:
                    chat_messages = result

            curr_round += 1

    async def handle_mcp_server_tools(self, resource_tools):
        if self.tools:
            return

        server_tools = []
        if resource_tools:
            for tool in resource_tools:
                server_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.inputSchema,
                        },
                    }
                )

        self.tools = server_tools

    async def handle_mcp_server_resources(self, resources):
        if self.resources:
            return

        server_resources = []
        if resources:
            for resource in resources:
                server_resources.append(
                    {
                        "uri": resource.uri,
                        "name": resource.name,
                        "description": resource.description,
                        "mimeType": resource.mimeType,
                        "size": resource.size,
                        "annotations": resource.annotations,
                    }
                )
        self.resources = server_resources

    async def handle_mcp_server_resource_templates(self, resource_templates):
        resources = []
        if resource_templates:
            for temp in resource_templates:
                uri = temp.uriTemplate
                name = temp.name

                resources.append({"uri": uri, "name": name})

        self.resource_templates = resources

    async def chat_loop(self, stream=True):
        print("\nMCP Client Started!")
        print("Type your queries or 'quit' to exit.")

        # 获取mcp server的资源

        try:
            await self.get_server_resources()
        except Exception as e:
            logger.error(e)

        resource_uris = []
        if self.resources:
            for resource in self.resources:
                resource_uris.append(resource.get("uri"))

        while True:
            query = input("\nQuery: ").strip()
            if not query:
                continue
            if query.lower() == "quit":
                break

            try:
                if stream is True:
                    async for response in self.process_query_by_sse_stream(
                        query, resource_uris
                    ):
                        if not isinstance(response, str):
                            if not response.choices:
                                continue

                            choice = response.choices[0]
                            print(f"{choice.delta.content}", end="")
                else:
                    response = await self.process_query_by_sse(query, resource_uris)
                    print(response.choices[0].message.content)

            except Exception as e:
                logger.error(traceback.format_exc())

    async def chat(self, user_input, stream=True):
        """

        try:
            await self.get_server_resources()
        except Exception as e:
            logger.error(e)

        resource_uris = []
        if self.resources:
            for resource in self.resources:
                resource_uris.append(resource.get("uri"))
        """
        try:
            if stream is True:
                async for response in self.process_query_by_sse_stream(user_input, []):
                    if not isinstance(response, str):
                        if not response.choices:
                            continue

                        choice = response.choices[0]
                        yield choice.delta.content
        except Exception as e:
            logger.error(traceback.format_exc())

    async def cleanup(self):
        await self.exit_stack.aclose()


async def main():
    args = sys.argv
    """
    args[1] = "http://miuros.moe:8099/sse"
    if len(args) < 2:
        print("Usage: python client_sse.py <sse server url>")
        sys.exit(1)
    """
    try:
        llm_instance = LLMOpenAICompti()
        client = MCPClient(llm=llm_instance)
    except Exception as e:
        logger.info("初始化mcp client失败")
        logger.error(traceback.format_exc())
        sys.exit(1)

    try:
        await client.connect_to_server_by_sse("http://192.168.0.97:8090/sse")
        await client.chat_loop()
    except Exception as e:
        logger.info("连接mcp server失败，或者会话异常")
        logger.error(traceback.format_exc())
    finally:
        await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
