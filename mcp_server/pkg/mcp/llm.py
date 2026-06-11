from enum import Enum
import os
import json
from dataclasses import dataclass
from config.config import load_config
from openai import OpenAI, AsyncOpenAI


class FinishReason(str, Enum):
    STOP = "stop"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    LENGTH = "length"


@dataclass
class LLMBase:

    client = None
    default_model = None

    def chat_completions(self, chat_messages):
        if "model" not in chat_messages:
            chat_messages["model"] = self.default_model

        response = self.client.chat.completions.create(**chat_messages)
        return response

    async def handle_completions(self, client_session, response, chat_messages):
        """非流式会话响应处理"""
        choice = response.choices[0]
        finish_reason = choice.finish_reason
        if finish_reason == FinishReason.STOP:
            return response

        if finish_reason == FinishReason.TOOL_CALLS:

            tool_calls_message_info = choice.message
            # if isinstance(self, (LLMHuoShan, LLMZhipu)):
            #    tool_calls_message_info = choice.message.dict()

            chat_messages.get("messages").extend([tool_calls_message_info])

            tool_calls = choice.message.tool_calls
            for tool in tool_calls:
                tool_info = {"role": "tool", "tool_call_id": tool.id}

                tool_name = tool.function.name
                tool_args = (
                    json.loads(tool.function.arguments)
                    if tool.function.arguments
                    else {}
                )

                # 调用工具
                resp = await client_session.call_tool(tool_name, tool_args)
                func_call_content = resp.content[0] if resp and resp.content else None
                if func_call_content:
                    text_data = json.loads(func_call_content.text)
                    call_result = text_data.get("data", None)
                    call_result = json.dumps(call_result) if call_result else ""
                else:
                    call_result = None
                tool_info["content"] = call_result

                chat_messages.get("messages").extend([tool_info])

            return chat_messages

        return response

    async def handle_completions_stream(self, client_session, response, chat_messages):
        async for result in self.handle_completions_stream_t1(
            client_session, response, chat_messages
        ):
            yield result

    async def handle_completions_stream_t1(
        self, client_session, response, chat_messages
    ):
        """流式会话响应处理"""
        finish_reason = ""
        tool_infos = {}
        async for resp in response:
            if len(resp.choices) == 0:
                continue
            choice = resp.choices[0]
            finish_reason = choice.finish_reason
            tool_calls = choice.delta.tool_calls
            content = choice.delta.content

            if all([finish_reason is None, tool_calls is None, content in ["", None]]):
                continue

            if finish_reason == FinishReason.TOOL_CALLS:
                break

            if not tool_calls:
                # 非函数调用
                if finish_reason is None or finish_reason == FinishReason.STOP:
                    yield resp
            else:
                # 获取函数信息
                tool = tool_calls[0]
                tool_idx = tool.index
                tool_id = tool.id
                arguments = tool.function.arguments
                if tool_idx not in tool_infos:
                    tool_infos[tool_idx] = {
                        "tool_id": tool_id,
                        "tool_name": tool.function.name,
                        "arguments": arguments or "",
                    }
                else:
                    if arguments:
                        # 流式输出拼接函数调用的参数
                        tool_infos[tool_idx]["arguments"] += arguments
        if finish_reason == FinishReason.TOOL_CALLS and tool_infos:
            chat_messages = await self._handle_function_call_stream_t1(
                client_session, tool_infos, chat_messages
            )
            yield chat_messages

    @staticmethod
    async def _handle_function_call_stream_t1(
        client_session, tool_infos, chat_messages
    ):
        tool_call_list, tool_call_results = [], []
        for idx, val in tool_infos.items():
            tool_id = val.get("tool_id")
            tool_name = val.get("tool_name")
            arguments = val.get("arguments")
            func_args = json.loads(arguments) if arguments else {}

            tool_call_list.append(
                {
                    "id": tool_id,
                    "function": {
                        "arguments": arguments,
                        "name": tool_name,
                    },
                    "type": "function",
                    "index": idx,
                }
            )

            # 调用工具
            resp = await client_session.call_tool(tool_name, func_args)
            func_call_content = resp.content[0] if resp and resp.content else None
            if func_call_content:
                call_result = func_call_content.text
                # call_result = text_data.get("data", None)
                # call_result = json.dumps(call_result) if call_result else ""

                tool_call_results.extend(
                    [
                        {
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "content": call_result,
                        },
                    ]
                )

        chat_messages.get("messages").extend(
            [{"role": "assistant", "content": "", "tool_calls": tool_call_list}]
        )
        chat_messages.get("messages").extend(tool_call_results)

        return chat_messages

    async def handle_completions_stream_t2(
        self, client_session, response, chat_messages
    ):
        """流式会话响应处理"""
        for resp in response:
            choice = resp.choices[0]
            finish_reason = choice.finish_reason
            if finish_reason is None or finish_reason == FinishReason.STOP:
                yield resp

            if finish_reason == FinishReason.TOOL_CALLS and choice.delta.tool_calls:
                chat_messages = await self._handle_function_call_stream_t2(
                    client_session, resp, chat_messages
                )

        yield chat_messages

    @staticmethod
    async def _handle_function_call_stream_t2(client_session, response, chat_messages):
        if response and chat_messages:
            choice = response.choices[0]
            dump_content = choice.delta
            tool_calls = dump_content.tool_calls
            for tool in tool_calls:
                tool_id = tool.id
                func_name = tool.function.name
                func_args = json.loads(tool.function.arguments)

                resp = await client_session.call_tool(func_name, func_args)
                func_call_content = resp.content[0] if resp and resp.content else None
                if func_call_content:
                    text_data = json.loads(func_call_content.text)
                    call_result = text_data.get("data", None)
                    call_result = json.dumps(call_result) if call_result else ""

                    chat_messages.get("messages").extend(
                        [
                            dump_content.model_dump(),
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "content": call_result,
                                "name": func_name,
                            },
                        ]
                    )
            else:
                return chat_messages
        return chat_messages


@dataclass
class LLMOpenAICompti(LLMBase):

    client = OpenAI(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-032a3f4b61c945a8bb92c7baea5f458c",
    )

    default_model = "qwen3-max"


@dataclass
class LLMClient(LLMBase):
    def __init__(
        self,
        base_url=load_config().model.base_url,
        api_key=load_config().model.api_key,
        default_model=load_config().model.model_name,
    ):
        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key
        )

        self.default_model = default_model
