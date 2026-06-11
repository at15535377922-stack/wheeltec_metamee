import threading
import time
from pkg.tts.bytedance.tts import TTSSession
import asyncio


async def run():
    tts_client = TTSSession()
    session_id = "test_session_1"
    tts_client.set_session(session_id)

    def tts_job():
        asyncio.run(tts_client.run())

    threading.Thread(target=tts_job).start()
    await tts_client.append_text((session_id, "抱歉，我没有听清楚，您重新跟我说说"))
    await tts_client.append_text((session_id, None))  # 结束会话
    # await tts_client.run()
    await asyncio.sleep(50)
    await tts_client.append_text(("aa", ""))


if __name__ == "__main__":
    asyncio.run(run())
