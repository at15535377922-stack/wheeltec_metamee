import asyncio
import websockets
import json
import base64
import time
from typing import Optional, Callable, List, Dict, Any
from enum import Enum


class TurnDetectionMode(Enum):
    SERVER_VAD = "server_vad"
    MANUAL = "manual"


from pydub import AudioSegment


def mp3_to_pcm_bytes(file_path, target_sample_rate=24000):
    # 1. 加载 MP3 文件
    audio = AudioSegment.from_file(file_path, format="mp3")

    # 2. 转换为标准 PCM 格式 (重要：AI 模型通常要求单声道和特定采样率)
    audio = audio.set_frame_rate(target_sample_rate)  # 设置采样率 (如 24000)
    audio = audio.set_channels(1)  # 设置为单声道
    audio = audio.set_sample_width(2)  # 设置为 16-bit (2字节)

    # 3. 获取原始 PCM 字节流
    pcm_bytes = audio.raw_data

    return pcm_bytes


TOOLS = [
    {
        "type": "function",
        "name": "get_weather",
        "description": "获取指定城市的实时天气",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "城市名，如北京"}
            },
            "required": ["location"],
        },
    }
]


class OmniRealtimeClient:

    def __init__(
        self,
        base_url="wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
        api_key: str = "sk-032a3f4b61c945a8bb92c7baea5f458c",
        model: str = "qwen3-omni-flash-realtime",
        voice: str = "Ethan",
        instructions: str = "You are a helpful assistant.",
        turn_detection_mode: TurnDetectionMode = TurnDetectionMode.SERVER_VAD,
        on_text_delta: Optional[Callable[[str], None]] = None,
        on_audio_delta: Optional[Callable[[bytes], None]] = None,
        on_input_transcript: Optional[Callable[[str], None]] = None,
        on_output_transcript: Optional[Callable[[str], None]] = None,
        extra_event_handlers: Optional[
            Dict[str, Callable[[Dict[str, Any]], None]]
        ] = None,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.instructions = instructions
        self.ws = None
        self.on_text_delta = on_text_delta
        self.on_audio_delta = on_audio_delta
        self.on_input_transcript = on_input_transcript
        self.on_output_transcript = on_output_transcript
        self.turn_detection_mode = turn_detection_mode
        self.extra_event_handlers = extra_event_handlers or {}

        # 当前回复状态
        self._current_response_id = None
        self._current_item_id = None
        self._is_responding = False
        # 输入/输出转录打印状态
        self._print_input_transcript = True
        self._output_transcript_buffer = ""

    async def connect(self) -> None:
        """与 Realtime API 建立 WebSocket 连接。"""
        url = f"{self.base_url}?model={self.model}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        self.ws = await websockets.connect(url, additional_headers=headers)

        # 会话配置
        session_config = {
            "modalities": ["text", "audio"],
            "voice": self.voice,
            "instructions": self.instructions,
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm24",
            "input_audio_transcription": {"model": "gummy-realtime-v1"},
            "tools": TOOLS,
        }

        if self.turn_detection_mode == TurnDetectionMode.MANUAL:
            session_config["turn_detection"] = None
            await self.update_session(session_config)
        elif self.turn_detection_mode == TurnDetectionMode.SERVER_VAD:
            session_config["turn_detection"] = {
                "type": "server_vad",
                "threshold": 0.1,
                "prefix_padding_ms": 500,
                "silence_duration_ms": 900,
            }
            await self.update_session(session_config)
        else:
            raise ValueError(f"Invalid turn detection mode: {self.turn_detection_mode}")

    async def send_event(self, event) -> None:
        event["event_id"] = "event_" + str(int(time.time() * 1000))
        await self.ws.send(json.dumps(event))

    async def update_session(self, config: Dict[str, Any]) -> None:
        """更新会话配置。"""
        event = {"type": "session.update", "session": config}
        await self.send_event(event)

    async def stream_audio(self, audio_chunk: bytes) -> None:
        """向 API 流式发送原始音频数据。"""
        # 仅支持 16bit 16kHz 单声道 PCM
        audio_b64 = base64.b64encode(audio_chunk).decode()
        append_event = {"type": "input_audio_buffer.append", "audio": audio_b64}
        await self.send_event(append_event)

    async def commit_audio_buffer(self) -> None:
        """提交音频缓冲区以触发处理。"""
        event = {"type": "input_audio_buffer.commit"}
        await self.send_event(event)

    async def append_image(self, image_chunk: bytes) -> None:
        """向图像缓冲区追加图像数据。
        图像数据可以来自本地文件，也可以来自实时视频流。
        注意:
            - 图像格式必须为 JPG 或 JPEG。推荐分辨率为 480P 或 720P，最高支持 1080P。
            - 单张图片大小不应超过 500KB。
            - 将图像数据编码为 Base64 后再发送。
            - 建议以 1张/秒 的频率向服务端发送图像。
            - 在发送图像数据之前，需要至少发送过一次音频数据。
        """
        image_b64 = base64.b64encode(image_chunk).decode()
        event = {"type": "input_image_buffer.append", "image": image_b64}
        await self.send_event(event)

    async def create_response(self) -> None:
        """向 API 请求生成回复（仅在手动模式下需要调用）。"""
        event = {"type": "response.create"}
        await self.send_event(event)

    async def cancel_response(self) -> None:
        """取消当前回复。"""
        event = {"type": "response.cancel"}
        await self.send_event(event)

    async def handle_interruption(self):
        """处理用户对当前回复的打断。"""
        if not self._is_responding:
            return
        # 1. 取消当前回复
        if self._current_response_id:
            await self.cancel_response()

        self._is_responding = False
        self._current_response_id = None
        self._current_item_id = None

    async def handle_messages(self) -> None:
        try:
            async for message in self.ws:
                event = json.loads(message)
                event_type = event.get("type")
                if event_type == "error":
                    print(" Error: ", event["error"])
                    continue
                elif event_type == "response.created":
                    self._current_response_id = event.get("response", {}).get("id")
                    self._is_responding = True
                elif event_type == "response.output_item.added":
                    self._current_item_id = event.get("item", {}).get("id")
                elif event_type == "response.done":
                    self._is_responding = False
                    self._current_response_id = None
                    self._current_item_id = None
                elif event_type == "input_audio_buffer.speech_started":
                    print("检测到语音开始")
                    if self._is_responding:
                        print("处理打断")
                        await self.handle_interruption()
                elif event_type == "input_audio_buffer.speech_stopped":
                    print("检测到语音结束")
                elif event_type == "response.text.delta":
                    if self.on_text_delta:
                        self.on_text_delta(event["delta"])
                elif event_type == "response.audio.delta":
                    if self.on_audio_delta:
                        audio_bytes = base64.b64decode(event["delta"])
                        self.on_audio_delta(audio_bytes)
                elif (
                    event_type
                    == "conversation.item.input_audio_transcription.completed"
                ):
                    transcript = event.get("transcript", "")
                    print(f"用户: {transcript}")
                    if self.on_input_transcript:
                        await asyncio.to_thread(self.on_input_transcript, transcript)
                        self._print_input_transcript = True
                elif event_type == "response.audio_transcript.delta":
                    if self.on_output_transcript:
                        delta = event.get("delta", "")
                        if not self._print_input_transcript:
                            self._output_transcript_buffer += delta
                        else:
                            if self._output_transcript_buffer:
                                await asyncio.to_thread(
                                    self.on_output_transcript,
                                    self._output_transcript_buffer,
                                )
                                self._output_transcript_buffer = ""
                            await asyncio.to_thread(self.on_output_transcript, delta)
                elif event_type == "response.audio_transcript.done":
                    print(f"大模型: {event.get('transcript', '')}")
                    self._print_input_transcript = False
                elif event_type in self.extra_event_handlers:
                    self.extra_event_handlers[event_type](event)
        except websockets.exceptions.ConnectionClosed:
            print(" Connection closed")
        except Exception as e:
            print(" Error in message handling: ", str(e))

    async def close(self) -> None:
        """关闭 WebSocket 连接。"""
        if self.ws:
            await self.ws.close()


# -- coding: utf-8 --
import os, asyncio, pyaudio, queue, threading


# 音频播放器类（处理中断）
class AudioPlayer:
    def __init__(self, pyaudio_instance, rate=24000):
        self.stream = pyaudio_instance.open(
            format=pyaudio.paInt16, channels=1, rate=rate, output=True
        )
        self.queue = queue.Queue()
        self.stop_evt = threading.Event()
        self.interrupt_evt = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self.stop_evt.is_set():
            try:
                data = self.queue.get(timeout=0.5)
                if data is None:
                    break
                if not self.interrupt_evt.is_set():
                    self.stream.write(data)
                self.queue.task_done()
            except queue.Empty:
                continue

    def add_audio(self, data):
        self.queue.put(data)

    def handle_interrupt(self):
        self.interrupt_evt.set()
        self.queue.queue.clear()

    def stop(self):
        self.stop_evt.set()
        self.queue.put(None)
        self.stream.stop_stream()
        self.stream.close()


# 麦克风录音并发送
async def record_and_send(client):

    data = mp3_to_pcm_bytes("aaa.mp3", 16000)
    p = pyaudio.PyAudio()
    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=16000,
        input=True,
        frames_per_buffer=3200,
    )
    print("开始录音，请讲话...")
    try:
        idx = 0
        while True:

            audio_data = stream.read(3200)
            await client.stream_audio(audio_data)
            await asyncio.sleep(0.02)
            idx = 0
            while len(audio_data) > 0:
                audio_data = data[idx * 3200 : (idx + 1) * 3200]
                await client.stream_audio(audio_data)
                await asyncio.sleep(0.1)
                idx += 1
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()


async def main():
    p = pyaudio.PyAudio()
    player = AudioPlayer(pyaudio_instance=p)

    client = OmniRealtimeClient(
        # 以下是中国大陆（北京）地域 base_url，国际（新加坡）地域base_url为wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime
        base_url="wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
        model="qwen3-omni-flash-realtime",
        voice="Cherry",
        instructions="你是小云，风趣幽默的好助手",
        turn_detection_mode=TurnDetectionMode.SERVER_VAD,
        on_text_delta=lambda t: print(f"\nAssistant: {t}", end="", flush=True),
        on_audio_delta=player.add_audio,
    )

    await client.connect()
    print("连接成功，开始实时对话...")

    # 并发运行
    await asyncio.gather(client.handle_messages(), record_and_send(client))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序已退出。")
