import asyncio
from collections import deque
import copy
from datetime import datetime
import json
import logging
import queue
import re
import threading
import time
import traceback
from typing import Optional
import uuid
from pkg.tts.bytedance.protocols import *
from websockets.protocol import State
import sounddevice as sd
import numpy as np

TTS_ENDPOINT = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
# TTS_ENDPOINT = "ws://116.62.111.185:9443/api/v3/tts/bidirection"
TTS_APPID = "6813388294"  # 替换为你的APPID
TTS_ACCESS_TOKEN = "eImThtW9vFVGmzR4vLnVduT68vWfj8MV"  # 替换为你的Access Token
TTS_VOICE_TYPE = "zh_male_yangguangqingnian_emo_v2_mars_bigtts"  # 替换为你想要的音色
TTS_ENCODING = "pcm"  # 输出音频格式
# 重连配置
CONNECTION_TIMEOUT = 10  # 连接超时(秒)


chars_to_find = "，。？！!,.?"
logger = logging.getLogger(__file__)


def get_resource_id(voice: str) -> str:
    """获取资源ID"""
    if voice.startswith("S_"):
        return "volc.megatts.default"
    return "volc.service_type.10029"


class TTSConnectionManager:
    """全局TTS连接管理器，复用WebSocket连接"""

    def __init__(
        self,
    ):
        self.websocket = None
        self.connection_ready = False
        self.base_request = None
        self._loop = None
        self.session_id = None
        self.session_condition = None  # 用于会话状态同步
        self.pending_sessions = {}  # 跟踪待处理的会话状态 {session_id: event_type}

    def set_event_loop(self, loop):
        """设置事件循环"""
        self._loop = loop

    async def ensure_connection(self):
        """确保连接已建立"""
        if (
            self.connection_ready
            and self.websocket
            and self.websocket.state == State.OPEN
        ):
            return True

        try:
            logger.info("建立TTS连接...")

            # 初始化 Condition
            if self.session_condition is None:
                self.session_condition = asyncio.Condition()

            headers = {
                "X-Api-App-Key": TTS_APPID,
                "X-Api-Access-Key": TTS_ACCESS_TOKEN,
                "X-Api-Resource-Id": get_resource_id(TTS_VOICE_TYPE),
                "X-Api-Connect-Id": str(uuid.uuid4()),
            }
            self.websocket = await asyncio.wait_for(
                websockets.connect(
                    TTS_ENDPOINT,
                    additional_headers=headers,
                    max_size=10 * 1024 * 1024,
                ),
                timeout=CONNECTION_TIMEOUT,
            )
            await start_connection(self.websocket)
            await wait_for_event(
                self.websocket, MsgType.FullServerResponse, EventType.ConnectionStarted
            )
            self.base_request = {
                "user": {"uid": str(uuid.uuid4())},
                "namespace": "BidirectionalTTS",
                "req_params": {
                    "speaker": TTS_VOICE_TYPE,
                    "audio_params": {
                        "format": TTS_ENCODING,
                        "sample_rate": 16000,
                        "loudness_rate": 100,
                    },
                    "additions": json.dumps({"disable_markdown_filter": False}),
                },
            }

            # 启动会话
            start_session_request = copy.deepcopy(self.base_request)
            start_session_request["event"] = EventType.StartSession
            self.session_request = start_session_request
            return True
        except Exception as e:
            logger.error(f"TTS连接建立失败: {e}")
            self.connection_ready = False
            return False
            # self.session_id = str(uuid.uuid4())

    async def start_session(self, session_id):
        try:
            async with self.session_condition:
                # 标记等待 SessionStarted 事件
                self.pending_sessions[session_id] = EventType.SessionStarted

                # 发送启动会话请求
                await start_session(
                    self.websocket,
                    json.dumps(self.session_request).encode(),
                    session_id,
                )
                logger.info(f"TTS会话启动请求已发送: {session_id}")

                # 等待 _receive_audio 收到 SessionStarted 事件并通知
                await self.session_condition.wait_for(
                    lambda: self.pending_sessions.get(session_id) == "completed"
                )

                # 清理状态
                self.pending_sessions.pop(session_id, None)

            self.connection_ready = True
            logger.info(f"TTS会话启动成功: {session_id}")
            return True

        except Exception as e:
            logger.error(f"TTS会话启动失败: {e}")
            self.pending_sessions.pop(session_id, None)
            self.connection_ready = False
            return False

    async def close_session(self, session_id):
        logger.info(f"关闭TTS会话: {session_id}")

        try:
            async with self.session_condition:
                # 标记等待 SessionFinished 事件
                self.pending_sessions[session_id] = EventType.SessionFinished

                # 发送结束会话请求
                await finish_session(self.websocket, session_id)
                logger.info(f"TTS会话结束请求已发送: {session_id}")

                # 等待 _receive_audio 收到 SessionFinished 事件并通知
                await self.session_condition.wait_for(
                    lambda: self.pending_sessions.get(session_id) == "completed"
                )

                # 清理状态
                self.pending_sessions.pop(session_id, None)

            logger.info(f"TTS会话已关闭: {session_id}")
        except Exception as e:
            logger.warning(f"关闭会话出错: {e}")
            self.pending_sessions.pop(session_id, None)

    async def disconnect(self):
        """断开连接"""
        if self.websocket:
            try:
                await finish_connection(self.websocket)
                await self.websocket.close()
            except:
                pass
            finally:
                self.websocket = None
                self.connection_ready = False


# 全局TTS连接管理器
tts_connection_manager = TTSConnectionManager()


class TTSSession:
    def __init__(self):
        # self.websocket = None
        self.session_id = None
        self.connection_ready = False
        self.session_finished = False
        self.audio_buffer = asyncio.Queue()

        # 文本缓冲区：LLM生成的文本先存这里，连接好后发送
        self.text_buffer = asyncio.Queue()

        # 事件用于同步
        self.connection_ready_event = asyncio.Event()
        self.stop_event = asyncio.Event()

        # self.base_request = None
        self.interrupted = False
        self.lock = threading.Lock()
        self.clear_event = threading.Event()
        self.session_id = ""

    async def run(self):
        """运行完整的TTS会话：并行建连接和LLM处理"""

        if not await tts_connection_manager.ensure_connection():
            logger.error("无法建立TTS连接")
            return

        self.websocket = tts_connection_manager.websocket
        self.base_request = tts_connection_manager.base_request
        # self.session_id = tts_connection_manager.session_id
        self.connection_ready = True
        self.connection_ready_event.set()

        tasks = [
            # asyncio.create_task(self._connect_tts()),
            asyncio.create_task(self._receive_audio()),
            asyncio.create_task(self._send_buffered_text()),  # 发送缓冲的文本
            asyncio.create_task(self.play()),
        ]

        # 等待所有任务完成或出错
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)

        # 取消未完成的任务
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def append_text(self, text):
        await self.text_buffer.put(text)

    async def new_tts_session(self, session_id):
        await tts_connection_manager.start_session(session_id)
        self.connection_ready = True
        self.connection_ready_event.set()

    async def close_tts_session(self, session_id):
        await tts_connection_manager.close_session(session_id)

    async def _send_buffered_text(self):
        """发送缓冲的文本到TTS"""
        logger.info("Starting buffered text sender...")
        chars_to_find_pattern = re.compile(f"[{re.escape(chars_to_find)}]")
        cache_text = ""
        chars_to_find_tuple = tuple([char for char in chars_to_find])
        try:
            # 等待TTS连接就绪
            # await self.connection_ready_event.wait()
            logger.info("TTS connection ready, start sending buffered text")
            prevois_session = ""

            while True:
                session_id, chunk_text = await self.text_buffer.get()
                #logger.info(f"got session: {session_id},chunk text: {chunk_text}")
                if chunk_text is None:
                    # 可以作为一个句子的结束
                    if cache_text:
                        await self._send_text_to_tts(session_id, cache_text)
                        cache_text=""
                    #
                    continue
                if session_id != prevois_session:
                    if cache_text:
                        logger.info(f"Got tts send message: [{cache_text}]")
                        await self._send_text_to_tts(prevois_session, cache_text)
                        cache_text = ""
                    if prevois_session:
                        await self.close_tts_session(prevois_session)
                    await self.new_tts_session(session_id)

                prevois_session = session_id
                cache_text += chunk_text

                if cache_text.endswith(chars_to_find_tuple):
                    logger.info(f"Got tts send message: [{cache_text}]")
                    await self._send_text_to_tts(session_id, cache_text)
                    cache_text = ""
                elif len(cache_text) > 10:
                    match = re.search(chars_to_find_pattern, cache_text)
                    if match:
                        index = match.end() + 1
                        logger.info(f"Got tts send message: [{cache_text[:index]}]")
                        await self._send_text_to_tts(session_id, cache_text[:index])
                        cache_text = cache_text[index:]
                elif len(cache_text) > 30:
                    logger.info(f"Got tts send message: [{cache_text}]")
                    await self._send_text_to_tts(session_id, cache_text)
                    cache_text = ""

            # 发送完毕后，等待一会让音频播放完，然后结束会话
            # await asyncio.sleep(2)
            # await finish_session(self.websocket, self.session_id)
        except Exception as e:
            logger.error(f"Error sending buffered text: {e}")
            self.stop_event.set()

    async def _send_text_to_tts(self, session, text: str):
        """发送文本到TTS"""
        # if not self.connection_ready or not self.websocket:
        #    logger.warning("TTS not ready, cannot send text")
        #    return
        #

        try:
            synthesis_request = copy.deepcopy(self.base_request)
            synthesis_request["event"] = EventType.TaskRequest
            synthesis_request["req_params"]["text"] = text
            await task_request(
                tts_connection_manager.websocket,
                json.dumps(synthesis_request).encode(),
                session,
            )
            logger.info(f"Sent text to TTS: '{text}' session: {session}")
        except Exception as e:
            # traceback.print_exc()
            logger.error(f"Error sending text to TTS: {e}")

    async def _receive_audio(self):
        """接收TTS音频流"""
        logger.info("Starting audio reception...")

        # 等待TTS连接就绪
        await self.connection_ready_event.wait()

        # 创建音频文件
        # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # f = open("sorry.pcm", "wb")
        try:
            while not self.stop_event.is_set():
                try:

                    msg = await asyncio.wait_for(
                        receive_message(self.websocket), timeout=60.0
                    )

                    if msg.type == MsgType.FullServerResponse:
                        if msg.event == EventType.SessionStarted:
                            logger.info(f"Session started: {msg.session_id}")
                            # 通知等待的 start_session
                            async with tts_connection_manager.session_condition:
                                if (
                                    msg.session_id
                                    in tts_connection_manager.pending_sessions
                                ):
                                    if (
                                        tts_connection_manager.pending_sessions[
                                            msg.session_id
                                        ]
                                        == EventType.SessionStarted
                                    ):
                                        tts_connection_manager.pending_sessions[
                                            msg.session_id
                                        ] = "completed"
                                        tts_connection_manager.session_condition.notify_all()
                        elif msg.event == EventType.SessionFinished:
                            logger.info(f"Session finished: {msg.session_id}")
                            # 通知等待的 close_session
                            async with tts_connection_manager.session_condition:
                                if (
                                    msg.session_id
                                    in tts_connection_manager.pending_sessions
                                ):
                                    if (
                                        tts_connection_manager.pending_sessions[
                                            msg.session_id
                                        ]
                                        == EventType.SessionFinished
                                    ):
                                        tts_connection_manager.pending_sessions[
                                            msg.session_id
                                        ] = "completed"
                                        tts_connection_manager.session_condition.notify_all()
                            self.session_finished = True
                            # f.close()

                    elif msg.type == MsgType.AudioOnlyServer:
                        # logger.info(f"Received audio chunk: {len(msg.payload)} bytes")
                        # f.write(msg.payload)
                        # self.audio_buffer.extend(msg.payload)
                        # ===== 第一次接收到音频包，调用绿色LED =====
                        # 解码并播放音频
                        try:
                            # pcm = decode_mp3_to_pcm(msg.payload)
                            """
                            if self.clear_event.is_set():
                                continue
                            """
                            # f.write(msg.payload)
                            await self.audio_buffer.put((msg.session_id, msg.payload))

                        except Exception as e:
                            logger.warning(f"Error playing audio chunk: {e}")
                    else:
                        logger.debug(f"Received message type: {msg.type}")

                except asyncio.TimeoutError:
                    logger.warning("Audio reception timeout")
                    continue
                except websockets.exceptions.ConnectionClosed:
                    logger.info("WebSocket connection closed by server")
                    self.stop_event.set()
                    break
                except Exception as e:
                    logger.error(f"Error receiving audio: {e}")
                    self.stop_event.set()
                    break
        except Exception as e:
            logger.error(f"Error in audio reception: {e}")
            self.stop_event.set()

    async def _disconnect(self):
        """关闭TTS连接"""
        return
        if not self.connection_ready:
            return

        try:
            logger.info("Closing TTS connection...")

            # 结束会话
            if not self.session_finished and self.session_id:
                try:
                    await finish_session(self.websocket, self.session_id)
                    await wait_for_event(
                        self.websocket,
                        MsgType.FullServerResponse,
                        EventType.SessionFinished,
                    )
                except Exception as e:
                    logger.warning(f"Error finishing session: {e}")

            # 结束连接
            try:
                await finish_connection(self.websocket)
                await wait_for_event(
                    self.websocket,
                    MsgType.FullServerResponse,
                    EventType.ConnectionFinished,
                )
            except Exception as e:
                logger.warning(f"Error finishing connection: {e}")

            # 关闭WebSocket
            await self.websocket.close()

        except Exception as e:
            logger.error(f"Error during disconnect: {e}")
        finally:
            self.connection_ready = False
            self.websocket = None
            self.session_id = None
            logger.info("TTS connection closed")

    def set_audio_play(self, state: bool):
        # clear event set
        # with self.lock
        """
        self.clear_event.set()
        with self.lock:
            self.audio_buffer.clear()
        self.clear_event.clear()
        """
        if state and self.clear_event.is_set():
            self.clear_event.clear()
        elif state == False and self.clear_event.is_set() == False:
            self.clear_event.set()

        # clear event reset

    def set_session(self, session_id):
        self.session_id = session_id

    async def get_audio_buffer(self):
        audio_data = await self.audio_buffer.get()
        yield audio_data

    async def play(self):
        try:
            stream = sd.OutputStream(samplerate=16000, channels=1, dtype="int16")
            stream.start()
            while True:

                # if clear event set,skip
                """
                if self.clear_event.is_set():
                    time.sleep(0.1)
                    continue
                """
                session_id, audio = await self.audio_buffer.get()
                # if not self.clear_event.is_set() and
                if self.session_id == session_id:
                    stream.write(np.frombuffer(audio, dtype=np.int16))
        except Exception as e:
            logger.error(f"Play audio error: {str(e)}")

    def cancel(self):
        """取消当前TTS会话"""
        logger.info("Cancelling TTS session")
        self.interrupted = True
        self.stop_event.set()
