import asyncio
from pkg.mcp.llm import LLMClient
from config.config import load_config


async def main():
    llm = LLMClient(
        load_config().model.base_url,
        load_config().model.api_key,
        load_config().model.model_name,
    )
    response = await llm.chat_completions(
        {"stream": True, "messages": [{"role": "user", "content": "你好"}]}
    )
    async for line in response:
        print(line.model_dump())


if __name__ == "__main__":
    asyncio.run(main())
