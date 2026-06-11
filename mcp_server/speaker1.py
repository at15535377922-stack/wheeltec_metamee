import queue
import logging
import sounddevice as sd
import numpy as np

logger = logging.getLogger(__file__)


class Speaker:
    def __init__(self):
        self.audio_buffer = queue.Queue()
        self.session_id = ""

    def append_audio(self, audio_chunk):
        self.audio_buffer.put(audio_chunk)

    def set_session_id(self, session_id):
        self.session_id = session_id

    def play(self):
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
                session_id, audio = self.audio_buffer.get()
                # if not self.clear_event.is_set() and
                stream.write(np.frombuffer(audio, dtype=np.int16))
        except Exception as e:
            logger.error(f"Play audio error: {str(e)}")
