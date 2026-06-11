import asyncio
from pathlib import Path
from google import genai
import pyaudio
import os
from google.genai import types
from pkg.service.tool import get_default_tool_service
from taskgroup import TaskGroup
from pydub import AudioSegment
from config.log import setup_logger
from config.config import load_config
from pkg.mic.sherpa import SherpaListener
import traceback

setup_logger()

os.environ.setdefault("GEMINI_API_KEY", load_config().google.api_key)
client = genai.Client()
# --- pyaudio config ---
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024

pya = pyaudio.PyAudio()

# --- Live API config ---
MODEL = load_config().google.model

TOOLS = []
for tool in get_default_tool_service().list():
    TOOLS.append(
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description,
                    parameters=types.Schema(**tool.inputSchema),
                    behavior="NON_BLOCKING",
                )
            ]
        )
    )


CONFIG = {
    "response_modalities": ["AUDIO"],
    "system_instruction": "You are a helpful and friendly AI assistant.",
    "tools": TOOLS,
}

audio_queue_output = asyncio.Queue()
audio_queue_mic = asyncio.Queue(maxsize=5)
audio_stream = None


def _run_listener_loop(loop, queue):
    """
    这是一个同步函数，将在单独的线程中运行。
    它负责运行阻塞的 SherpaListener 迭代器。
    """
    listener = SherpaListener()

    # 这个循环是阻塞的，但因为它在单独线程里，所以不会卡死主程序的 async 循环
    for item in listener.get_chat_audio_data_after_keyword_detected():
        if item is None:
            continue

        payload = {"data": item, "mime_type": "audio/wav"}

        # 关键点：asyncio.Queue 不是线程安全的，不能直接在线程里调用 await queue.put()
        # 必须使用 run_coroutine_threadsafe 将其调度回主事件循环
        future = asyncio.run_coroutine_threadsafe(queue.put(payload), loop)

        # 可选：如果你希望这个线程等待队列写入完成（比如队列满了需要阻塞），取消下面这行的注释
        # future.result()


async def listen_audio():
    """Listens for audio using SherpaListener in a separate thread."""
    # 获取当前的事件循环，以便传给线程使用
    loop = asyncio.get_running_loop()

    print("Starting SherpaListener in a separate thread...")

    # asyncio.to_thread 会在一个线程池中运行 _run_listener_loop
    # 并等待它结束（如果迭代器是死循环，这里就会一直挂起，符合预期）
    await asyncio.to_thread(_run_listener_loop, loop, audio_queue_mic)


async def send_realtime(session):
    """Sends audio from the mic audio queue to the GenAI session."""
    while True:
        msg = await audio_queue_mic.get()
        await session.send_realtime_input(audio=msg)


async def play_audio():
    """Plays audio from the speaker audio queue."""
    stream = await asyncio.to_thread(
        pya.open,
        format=FORMAT,
        channels=CHANNELS,
        rate=RECEIVE_SAMPLE_RATE,
        output=True,
    )
    while True:
        bytestream = await audio_queue_output.get()
        await asyncio.to_thread(stream.write, bytestream)


async def receive(live_session):
    while True:

        async for response in live_session.receive():
            # 1. 处理打断信号 (用户说话时，AI 应该停止当前播放)
            """
            if response.server_content and response.server_content.interrupted:
                print("--- Interrupted by user ---")
                while not audio_queue_output.empty():
                    try:
                        audio_queue_output.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                continue
            """
            if response.server_content and response.server_content.model_turn:
                for part in response.server_content.model_turn.parts:
                    if part.inline_data and isinstance(part.inline_data.data, bytes):
                        audio_queue_output.put_nowait(part.inline_data.data)
            elif response.data is not None:
                audio_queue_output.put_nowait(response.data)
            elif response.tool_call:
                print("The tool was called")
                function_responses = []
                for fc in response.tool_call.function_calls:
                    func = get_default_tool_service().get(fc.name)
                    data = func(**fc.args)
                    function_response = types.FunctionResponse(
                        id=fc.id,
                        name=fc.name,
                        response={
                            "result": "ok",
                            "data": data,
                        },  # simple, hard-coded function response
                    )
                    function_responses.append(function_response)

                await live_session.send_tool_response(
                    function_responses=function_responses
                )
        """
        # Empty the queue on interruption to stop playback
        while not audio_queue_output.empty():
            audio_queue_output.get_nowait()
        """


async def run():
    """Main function to run the audio loop."""
    try:
        async with client.aio.live.connect(model=MODEL, config=CONFIG) as live_session:
            print("Connected to Gemini. Start speaking!")
            """
            await live_session.send_client_content(
                turns={
                    "role": "user",
                    "parts": [{"text": "看下当前的ipv4地址,这是windows系统"}],
                },
                turn_complete=True,
            )
            """
            async with TaskGroup() as tg:
                tg.create_task(send_realtime(live_session))
                tg.create_task(listen_audio())
                tg.create_task(receive(live_session))
                tg.create_task(play_audio())

    except Exception as e:
        traceback.print_exc()
        print(e)
        pass
    finally:
        if audio_stream:
            audio_stream.close()
        pya.terminate()
        print("\nConnection closed.")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("Interrupted by user.")
