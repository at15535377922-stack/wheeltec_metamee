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

logger = setup_logger()

os.environ.setdefault("GEMINI_API_KEY", "AIzaSyDNd3K9agvU6EePXvcNVhRG2QY7yRlueJo")
client = genai.Client()
# --- pyaudio config ---
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024

pya = pyaudio.PyAudio()

# --- Live API config ---
MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"

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


async def listen_audio():
    """Listens for audio and puts it into the mic audio queue."""
    global audio_stream
    mic_info = pya.get_default_input_device_info()
    audio_stream = await asyncio.to_thread(
        pya.open,
        format=FORMAT,
        channels=CHANNELS,
        rate=SEND_SAMPLE_RATE,
        input=True,
        input_device_index=mic_info["index"],
        frames_per_buffer=CHUNK_SIZE,
    )
    kwargs = {"exception_on_overflow": False} if __debug__ else {}
    while True:
        logger.info("Send audio to queue")
        data = await asyncio.to_thread(audio_stream.read, CHUNK_SIZE, **kwargs)
        await audio_queue_mic.put({"data": data, "mime_type": "audio/pcm"})


async def send_realtime(session):
    """Sends audio from the mic audio queue to the GenAI session."""
    while True:
        msg = await audio_queue_mic.get()
        logger.info("Send audio to session")
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
        logger.info("Got audioi from out queue")
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
                        logger.info("Receive audio from session")
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
