import asyncio
import queue
import threading
import uuid
from datetime import datetime
import asyncio
from datetime import datetime
import queue
import threading
import time
import uuid
from pkg.asr.tencent_client import TencentAsrClient
from pkg.tts.byte_client import ByteDanceTtsClient
from pkg.tts.edge_client import EdgeTtsClient
from pkg.mic.micphone import Listener
from pkg.mic.sherpa import SherpaListener
from pkg.mcp.mcp_client import MCPClient
from pkg.mcp.llm import LLMClient
from pkg.player.speaker import Speaker
from config.log import setup_logger
import logging
import wave

# ... 你的其他 import 保持不变 ...

setup_logger()
logger = logging.getLogger(__file__)


def get_sorry_wav_bytes():
    with wave.open("sorry.wav", "rb") as f:
        n = f.getnframes()
        return f.readframes(n)


async def run():
    # 1. 初始化所有客户端
    sorry_wav_bytes = get_sorry_wav_bytes()
    llm = LLMClient()
    mcp_client = MCPClient(llm=llm)
    await mcp_client.connect_to_server_by_sse("http://miuros.moe:8090/sse")

    tts_client = ByteDanceTtsClient()
    speaker = Speaker()
    listen = SherpaListener()
    listen.start()

    # 2. 定义异步队列 (我们的“足球”)
    # asr_queue: 存放识别出来的文字
    asr_queue = asyncio.Queue()
    # 所有的异步任务共用这个 loop
    loop = asyncio.get_running_loop()

    # 3. 核心任务 A: TTS 处理器
    # 负责启动 tts_client.run() 并不断将音频喂给 speaker
    async def tts_processor():
        # 启动 TTS 内部循环（假设 tts_client.run 是异步的）
        asyncio.create_task(tts_client.run())

        logger.info("TTS 处理器已启动，等待音频流...")
        async for session_id, audio_bytes in tts_client.get_audio_buffer():
            logger.debug(
                f"收到音频片段，Session: {session_id}, 长度: {len(audio_bytes)}"
            )
            speaker.append_audio((session_id, audio_bytes))

    # 4. 核心任务 B: 播放器驱动
    # 如果 speaker.play 是阻塞的，我们把它扔到线程池执行
    def speaker_driver():
        logger.info("播放器线程已启动")
        speaker.play()  # 这是一个死循环阻塞调用

    loop.run_in_executor(None, speaker_driver)

    # 5. 核心任务 C: 录音监听（线程桥接）
    # 录音通常是阻塞 IO，放在独立线程跑，通过 asr_queue 传回文字
    def mic_listen_worker():
        session_id = ""
        is_running = False
        asr_client = None

        logger.info("麦克风监听线程启动")
        valid_audio_count = 0
        for data in listen.listen():
            try:
                if data is not None:
                    if not is_running:
                        asr_client = TencentAsrClient()
                        asr_client.run()
                        is_running = True
                        # 准备播放
                        tts_client.set_audio_play(True)
                        session_id = str(uuid.uuid4())
                        tts_client.set_session(session_id)
                        speaker.set_session_id(session_id)
                        # 这里需要通知主循环：用户开始说话了，停止之前的播放
                        loop.call_soon_threadsafe(tts_client.set_audio_play, False)
                    asr_client.write_audio(data)
                    valid_audio_count += 1
                else:
                    if is_running:
                        if valid_audio_count < 20:
                            valid_audio_count = 0
                            is_running = False
                            asr_client.stop()
                        try:
                            result = asr_client.get_asr_result()
                            asr_client.stop()
                            is_running = False
                            if result.strip():
                                # 【关键射门】：将识别结果放入异步队列
                                loop.call_soon_threadsafe(
                                    asr_queue.put_nowait, (session_id, result)
                                )
                        except Exception as e:
                            speaker.append_audio((session_id, sorry_wav_bytes))
                            logger.error(f"ASR error: {e}")
                            is_running = False
            except Exception as e:
                logger.error(f"Mic Worker error: {e}")

    threading.Thread(target=mic_listen_worker, daemon=True).start()

    # 6. 启动 TTS 处理任务
    asyncio.create_task(tts_processor())

    # 7. 主循环：处理 ASR 结果 -> 调用 LLM -> 喂给 TTS
    logger.info("系统就绪，开始主循环...")
    while True:
        # 等待录音文字进来
        session_id, asr_result = await asr_queue.get()

        chat_start = datetime.now()

        # 迭代 LLM 的流式输出
        async for chunk_text in mcp_client.chat(asr_result):
            # 直接 await 喂给 tts，不再跨线程
            await tts_client.append_text((session_id, chunk_text))

        logger.info(
            f"LLM 推理完成，耗时: {(datetime.now()-chat_start).total_seconds()}s"
        )


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
