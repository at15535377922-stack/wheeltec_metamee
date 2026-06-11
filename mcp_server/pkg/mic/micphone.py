import queue
import threading
import pyaudio
import numpy as np

CHUNK = 1024
FMT = pyaudio.paInt16
CHANNEL = 1
RATE = 16000
MINDB = 300
SCALE = 8
DELAYTIME = 1.2


sample_rate = 16000  # 采样率
duration = 1  # 秒
dtype = np.int16  # 必须与你的 OutputStream dtype 一致

# 计算采样点数：16000 * 0.5 = 8000 个点
num_samples = int(sample_rate * duration)

# 创建全 0 数组
silence_data = np.zeros(num_samples, dtype=dtype).tobytes()


class Listener:
    def __init__(self):
        self.p = pyaudio.PyAudio()
        self.stream = self.p.open(
            format=FMT, channels=CHANNEL, rate=RATE, input=True, frames_per_buffer=CHUNK
        )
        self.state = True

        self.cache = queue.Queue()

    def __del__(self):
        self.stream.stop_stream()
        self.stream.close()
        self.p.terminate()

    def close(self):
        self.__del__()

    def stop(self):
        self.state = False

    def listen(self):
        while True:
            data = self.cache.get()
            yield data

    def start(self):
        threading.Thread(target=self.job).start()

    def job(self):
        self.stream.start_stream()
        flag = False  # 开始有效录音标志
        is_silent = False  # 结束有效录音 状态 | 满足这个状态为true且持续一定时间
        time_idx = 0
        valid_idx = 0

        cache = bytes()
        f = open(r"C:\Users\miuros\Desktop\iwhale\mcp_server\test.wav", "rb")

        while self.state:
            data = f.read(CHUNK)
            if len(data) == 0:
                self.cache.put(None)
                continue
            # data = self.stream.read(CHUNK, exception_on_overflow=False)
            audio_data = np.frombuffer(data, dtype=np.int16)
            current_max_db = np.max(audio_data)
            audio_data = np.int16(audio_data * SCALE)
            data = audio_data.tobytes()

            if current_max_db > MINDB and not flag:
                flag = True
                valid_idx = time_idx
                # 最大值大于阈值 且 flag前为false静音  则开始录音返回有效数据
                self.cache.put(data)

                continue

            if flag:
                if current_max_db < MINDB and not is_silent:
                    is_silent = True  # 标记存在静音可能
                    valid_idx = time_idx

                if current_max_db > MINDB:
                    is_silent = False  # 去除标记
                    valid_idx = time_idx
                if (
                    time_idx > valid_idx + DELAYTIME * 15 and is_silent
                ):  # 说明之前已经静音一段时间
                    flag = False
                    self.cache.put(silence_data)
                    self.cache.put(None)
                    # yield None  # 标记一个结束
                    continue
                    """
                    if (is_silent and current_max_db < MINDB): #静音且没有声音
                        state=False #
                    else:
                        is_silent=False
                    """
                self.cache.put(data)

            time_idx = time_idx + 1
