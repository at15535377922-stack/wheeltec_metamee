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


setup_logger()
logger = logging.getLogger(__file__)


def get_sorry_wav_bytes():
    with wave.open("sorry.wav", "rb") as f:
        n = f.getnframes()
        return f.readframes(n)


async def run():
    llm = LLMClient()
    mcp_client = MCPClient(llm=llm)
    await mcp_client.connect_to_server_by_sse("http://miuros.moe:8090/sse")
    tts_client = ByteDanceTtsClient()

    def tts_job():
        asyncio.run(tts_client.run())

    t = threading.Thread(target=tts_job, daemon=True)
    t.start()

    # asr_client = TencentAsrClient()
    # asr_client.run()

    listen = SherpaListener()
    listen.start()
    asr_result_queue = queue.Queue()

    def mic_listen_job():
        session_id = ""
        is_running = False
        asr_result = ""
        for data in listen.listen():
            try:
                if data is not None:
                    if not is_running:
                        asr_client = TencentAsrClient()
                        asr_client.run()
                        is_running = True
                        session_id = str(uuid.uuid4())
                        tts_client.set_session(session_id)
                    tts_client.set_audio_play(False)  # 收到新的录音 停止之前播放
                    asr_client.write_audio(data)
                else:
                    if is_running:
                        # 腾讯的 长时间ws 不传输数据 服务端会断链
                        record_end = datetime.now()
                        try:
                            asr_result = asr_client.get_asr_result()
                            # asr_client.stop()
                            is_running = False
                        except:

                            listen.reset()
                            is_running = False
                            continue
                        if len(asr_result.strip()) == 0:
                            continue
                        asr_end = datetime.now()
                        logger.info(
                            f"ASR start at: {record_end.strftime('%H:%M:%S.%f')[:-3]} cost {(asr_end-record_end).microseconds/1000}"
                        )

                        asr_result_queue.put((session_id, asr_result))
            except Exception as e:
                logger.error(f"Worker error: {str(e)}")
                continue

    threading.Thread(target=mic_listen_job).start()

    loop = asyncio.get_event_loop()
    while True:
        session_id, asr_result = asr_result_queue.get()
        logger.info(f"Got asr result: {asr_result}")
        tts_client.set_audio_play(True)
        chat_start = datetime.now()
        async for chunk_text in mcp_client.chat(asr_result):
            await tts_client.append_text((session_id, chunk_text))

        chat_end = datetime.now()
        logger.info(
            f"Chat start at {chat_start.strftime('%H:%M:%S.%f')[:-3]} cost {(chat_end-chat_start).microseconds/1000}"
        )


if __name__ == "__main__":
    asyncio.run(run())
