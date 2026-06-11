import threading
import time
from pkg.player.speaker1 import Speaker


import wave


def run():
    speaker = Speaker()
    with wave.open("sorry.wav", "rb") as f:
        n = f.getnframes()
        data = f.readframes(n)
    threading.Thread(target=speaker.play).start()
    speaker.set_session_id("a")
    speaker.append_audio(("a", data))
    time.sleep(30)


run()
