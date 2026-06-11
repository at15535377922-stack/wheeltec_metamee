import asyncio
import json
import re
import copy
import threading
from datetime import datetime
import numpy as np
import sounddevice as sd
import edge_tts
import io
from pydub import AudioSegment
import logging

logger = logging.getLogger(__file__)


class EdgeTtsClient:
    def __init__(self, voice="zh-CN-XiaoxiaoNeural"):
        self.session_id = None
        self.connection_ready = False
        self.session_finished = False
        self.audio_buffer = asyncio.Queue()

        # 文本缓冲区：LLM生成的文本先存这里
        self.text_buffer = asyncio.Queue()

        # 事件用于同步
        self.connection_ready_event = asyncio.Event()
        self.stop_event = asyncio.Event()

        self.interrupted = False
        self.lock = threading.Lock()
        self.clear_event = threading.Event()
        self.session_id = ""

        # edge-tts 相关配置
        self.voice = voice
        # 标点符号用于文本分割
        self.chars_to_find = "。！？；.,!?; "

    async def run(self):
        """运行完整的TTS会话"""
        # edge-tts 不需要预连接，直接设为就绪
        self.connection_ready = True
        self.connection_ready_event.set()
        logger.info("EdgeTTS session started")

        tasks = [
            asyncio.create_task(
                self._send_buffered_text()
            ),  # 核心：处理文本并调用edge-tts
            asyncio.create_task(self.play()),  # 播放音频
        ]

        # 等待任务完成或被外部取消
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)

        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def append_text(self, text):
        # 假设传入的是 (session_id, text) 元组以匹配原逻辑
        await self.text_buffer.put(text)

    async def _send_buffered_text(self):
        """发送缓冲的文本到TTS"""
        logger.info("Starting buffered text sender...")
        chars_to_find_pattern = re.compile(f"[{re.escape(self.chars_to_find)}]")
        cache_text = ""
        chars_to_find_tuple = tuple([char for char in self.chars_to_find])

        try:
            await self.connection_ready_event.wait()
            prevois_session = ""

            while not self.stop_event.is_set():
                # 从缓冲区获取文本
                session_id, chunk_text = await self.text_buffer.get()
                if self.session_id != session_id:
                    continue
                if not chunk_text:
                    continue

                # 如果 session 变化，立即处理旧文本
                if session_id != prevois_session and cache_text:
                    await self._send_text_to_tts(prevois_session, cache_text)
                    cache_text = ""

                prevois_session = session_id
                cache_text += chunk_text

                # 逻辑：遇到标点符号、长度超过10位且有标点、或强制超过30位时发送
                if cache_text.endswith(chars_to_find_tuple):
                    await self._send_text_to_tts(session_id, cache_text)
                    cache_text = ""
                elif len(cache_text) > 10:
                    match = re.search(chars_to_find_pattern, cache_text)
                    if match:
                        index = match.end()
                        await self._send_text_to_tts(session_id, cache_text[:index])
                        cache_text = cache_text[index:]
                elif len(cache_text) > 30:
                    await self._send_text_to_tts(session_id, cache_text)
                    cache_text = ""

        except Exception as e:
            logger.error(f"Error sending buffered text: {e}")
            self.stop_event.set()

    async def _send_text_to_tts(self, session, text: str):
        """调用 edge-tts 生成音频并转换为原始 PCM 字节放入 buffer"""
        if not text.strip():
            return

        try:
            logger.info(f"EdgeTTS synthesizing: [{text}] session: {session}")
            communicate = edge_tts.Communicate(text)

            # 1. 收集 edge-tts 返回的 MP3 字节数据
            mp3_buffer = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    mp3_buffer.write(chunk["data"])

            # 如果没有抓取到音频，直接返回
            if mp3_buffer.tell() == 0:
                return

            # 2. 将 MP3 字节数据 转换为 PCM 字节数据
            # 重置指针到开始位置
            mp3_buffer.seek(0)

            # 使用 pydub 读取 MP3 字节流
            audio_seg = AudioSegment.from_file(mp3_buffer, format="mp3")

            # 强制转换为：采样率16000Hz, 单声道(1), 采样宽度2字节(16bit PCM)
            audio_seg = (
                audio_seg.set_frame_rate(16000).set_channels(1).set_sample_width(2)
            )

            # 3. 提取原始字节 (raw_data 就是 bytes 类型)
            pcm_bytes = audio_seg.raw_data

            # 4. 存入缓冲区
            if not self.clear_event.is_set():
                # 这里放入的是 (session, bytes)，play 方法中 np.frombuffer 会处理它
                await self.audio_buffer.put((session, pcm_bytes))
                logger.debug(f"Put {len(pcm_bytes)} bytes of PCM to buffer")

        except Exception as e:
            logger.error(f"Error in edge-tts synthesis or conversion: {e}")

    async def _receive_audio(self):
        """
        在 edge-tts 模式下，此方法不再需要独立循环。
        音频接收已集成在 _send_text_to_tts 的 stream() 中。
        保留空方法以兼容结构，或直接移除。
        """
        pass

    async def _disconnect(self):
        """清理 edge-tts 相关资源"""
        logger.info("Cleaning up edge-tts session")
        self.connection_ready = False
        self.stop_event.set()

    def set_audio_play(self, state: bool):
        if state and self.clear_event.is_set():
            self.clear_event.clear()
        elif state == False and not self.clear_event.is_set():
            self.clear_event.set()

    def set_session(self, session_id):
        self.session_id = session_id

    async def play(self):
        """播放音频流 (保持原样，仅确保采样率匹配)"""
        try:
            # 确保采样率与转换后的 PCM 一致 (16000)
            stream = sd.OutputStream(samplerate=16000, channels=1, dtype="int16")
            stream.start()
            while not self.stop_event.is_set():
                try:
                    session_id, audio = await asyncio.wait_for(
                        self.audio_buffer.get(), timeout=1.0
                    )
                    # if not self.clear_event.is_set() and self.session_id == session_id:
                    # if self.session_id == session_id:
                    stream.write(np.frombuffer(audio, dtype=np.int16))
                except asyncio.TimeoutError:
                    continue
        except Exception as e:
            logger.error(f"Play audio error: {str(e)}")

    def cancel(self):
        """取消当前TTS会话"""
        logger.info("Cancelling EdgeTTS session")
        self.interrupted = True
        self.stop_event.set()
