from datetime import datetime
import queue
import numpy as np
from configs import *
import sherpa_onnx
import sounddevice as sd
import threading
import wave

CHUNK = 1024
RATE = 48000
SAMPLE_RATE = RATE
MINDB = 300
DELAYTIME = 1.2


try:

    kws = sherpa_onnx.KeywordSpotter(
        tokens=TOKENS_FILE,
        encoder=ENCODER_MODEL,
        decoder=DECODER_MODEL,
        joiner=JOINER_MODEL,
        keywords_file=KEYWORDS_FILE,
        keywords_score=KEYWORD_SCORE,  # 关键词得分阈值
        keywords_threshold=KEYWORD_THRESHOLD,  # 检测阈值
        max_active_paths=4,  # 降低到4提高准确性
        num_trailing_blanks=1,  # 添加trailing blanks参数
        provider="cpu",
    )
    stream = kws.create_stream()
except BaseException as e:
    print(e)
audio_buffer = queue.Queue()


def push_bytes_to_buffer(wav_bytes):
    audio_buffer.put(wav_bytes)


def get_chat_audio_data_after_keyword_detected():
    current_mode = "detect"
    global audio_buffer, kws, stream
    silent_start = None
    while True:
        try:
            wav_bytes = audio_buffer.get(timeout=10)
        except Exception as e:
            return
        if wav_bytes is None:

            if silent_start is not None:
                silent_duration = (datetime.now() - silent_start).total_seconds()

                if silent_duration > 60:
                    # set flag，开始重新检测关键字
                    current_mode = "detect"
            else:
                silent_start = datetime.now()

            continue
        if current_mode == "chat":
            yield wav_bytes
            continue
        # 处理录音数据
        stream.accept_waveform(
            SAMPLE_RATE, np.frombuffer(wav_bytes, np.int16) / 32768.0
        )

        while kws.is_ready(stream):
            kws.decode_stream(stream)

            result = kws.get_result(stream)
            if result:
                print(f"检测到关键词: {result}")
                kws.reset_stream(stream)


time_idx = 0
flag = False  # 开始有效录音标志
is_silent = True  # 结束有效录音 状态 | 满足这个状态为true且持续一定时间
valid_idx = 0


def call_back(indata, frames=None, time=None, status=None):
    try:
        global time_idx, flag, is_silent, valid_idx
        if isinstance(indata, bytes):
            samples = np.frombuffer(indata, dtype=np.int16)
        else:
            samples = indata[0]
        current_max_db = np.max(samples)

        # If recording, collect data
        if current_max_db > MINDB and not flag:
            flag = True
            valid_idx = time_idx
            push_bytes_to_buffer(indata)
            time_idx += 1
            return

        if flag:
            if current_max_db < MINDB and not is_silent:
                is_silent = True
                valid_idx = time_idx

            if current_max_db > MINDB:
                is_silent = False
                valid_idx = time_idx

            if time_idx > valid_idx + DELAYTIME * 15 and is_silent:
                flag = False
                push_bytes_to_buffer(None)
                time_idx += 1
                return

            push_bytes_to_buffer(indata)
        else:
            if time_idx > 1 << 5:
                time_idx = 0
                valid_idx = 0
            push_bytes_to_buffer(None)

        time_idx += 1

    except Exception as e:
        print("Error: " + str(e))


def main():
    print("开始监听麦克风...")
    """
    # 打开输入流，回调处理音频
    with sd.InputStream(
        # callback=call_back,
        channels=1,
        samplerate=RATE,
        blocksize=1600,
        dtype="int16",
    ) as f:
    """
    wav_file = wave.open("test.wav", "rb")

    actual_rate = wav_file.getframerate()
    print(f"WAV文件采样率: {actual_rate}Hz")

    if actual_rate != SAMPLE_RATE:
        print(f"警告: WAV采样率({actual_rate})与设置采样率({SAMPLE_RATE})不匹配!")

    # 读取音频数据
    # audio_data = wav_file.readframes(wav_file.getnframes())
    while True:
        audio_data = wav_file.readframes(CHUNK)
        if audio_data:

            call_back(audio_data)
    samples = np.frombuffer(audio_data, np.int16)

    # 分块处理
    chunk_size = 1600
    for i in range(0, len(samples), chunk_size):
        chunk = samples[i : i + chunk_size]
        if len(chunk) == 0:
            break

        stream.accept_waveform(SAMPLE_RATE, chunk / 32768.0)

        while kws.is_ready(stream):
            kws.decode_stream(stream)

            result = kws.get_result(stream)
            if result:
                print(f"检测到关键词: {result}")
                kws.reset_stream(stream)


if __name__ == "__main__":
    threading.Thread(target=main).start()
    for item in get_chat_audio_data_after_keyword_detected():
        pass
