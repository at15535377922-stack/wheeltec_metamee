import binascii
from datetime import datetime
import os
import queue
import time
import numpy as np
import sherpa_onnx
import sounddevice as sd
import threading
import wave
from config.config import load_config
import logging
import serial
import requests

CHUNK = 1024
SAMPLE_RATE = 16000
MINDB = 1200
DELAYTIME = 2


# 创建全 0 数组
silence_data = np.zeros(SAMPLE_RATE * 1, dtype=np.int16).tobytes()


class AngleReader:
    def __init__(self):
        self.latest_angle_index = 0
        self.is_running = False
        self.logger = logging.getLogger(__name__)
        self.angle_data = []
        self.angle_read_thread = threading.Thread(target=self.serial_reader_thread)
        self.angle_read_thread.start()
        pass

    def get_angle(self, time_unix: int):
        if len(self.angle_data)==0:
            return 0
        index=0
        for idx, item in enumerate(self.angle_data):
            if item.get("time") > time_unix:
                index=idx
                break

        if index == 0:
            return self.angle_data[0]
        else:
            data = self.angle_data[index - 1]
            self.angle_data = self.angle_data[index- 1 :]
        return data

    def serial_reader_thread(self):
        """
        纯净版串口线程 (V6.0 Realtime)：
        1. 严格 8N1 配置。
        2. 【回归】实时更新模式：收到包立即更新，消除滞后。
        3. 角度公式：0x00 对应 180 度。
        """

        # 打印提示
        self.logger.info(
            f"[串口线程] 启动监听 {load_config().serial.serial_port} @ {load_config().serial.serial_port}"
        )

        try:
            # 打开串口
            ser = serial.Serial(
                port=load_config().serial.serial_port,
                baudrate=load_config().serial.baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
            ser.dtr = False
            ser.rts = False
        except Exception as e:
            self.logger.error(f"【严重错误】串口打开失败: {e}")
            return

        buffer = b""
        MAX_BUFFER = 2048

        while True:
            try:
                waiting = ser.in_waiting
                if waiting > 0:
                    data = ser.read(waiting)
                    buffer += data

                    # 限制缓冲区
                    if len(buffer) > MAX_BUFFER:
                        buffer = buffer[-MAX_BUFFER:]

                    # 循环解析
                    while len(buffer) >= 4:
                        # 1. 寻找包头 55 AA
                        if buffer[0] == 0x55 and buffer[1] == 0xAA:
                            # 找到头了
                            angle_idx = buffer[2]
                            checksum = buffer[3]

                            expected_sum = (0xFF - angle_idx) & 0xFF

                            if expected_sum == checksum:
                                # 校验通过！直接计算使用的公式:
                                # 协议定义: Index 00 = 180°
                                # 公式: (180 + Index * 30) % 360
                                correct_angle = (180 + angle_idx * 30) % 360

                                # 格式化原始数据
                                raw_packet = buffer[:4]
                                hex_str = (
                                    binascii.hexlify(raw_packet).decode("utf-8").upper()
                                )
                                formatted_hex = " ".join(
                                    [
                                        hex_str[i : i + 2]
                                        for i in range(0, len(hex_str), 2)
                                    ]
                                )

                                # 【直接更新，不等待】
                                latest_angle_data = {
                                    "angle": correct_angle,
                                    "index": angle_idx,
                                    "hex": formatted_hex,
                                    "time": int(time.time()),
                                }
                                self.angle_data.append(latest_angle_data)

                                # 移除这个包
                                buffer = buffer[4:]
                            else:
                                # 校验失败，可能是假头，丢弃 55
                                buffer = buffer[1:]
                        else:
                            # 不是头，丢弃首字节，向后滑动
                            buffer = buffer[1:]
                else:
                    time.sleep(0.01)
            except Exception:
                time.sleep(0.1)

        if ser and ser.isOpen():
            ser.close()


class SherpaListener:
    def __init__(self):

        self.keywords_file = os.path.join(load_config().sherpa.base_dir, "keywords.txt")
        self.tokens_file = os.path.join(load_config().sherpa.base_dir, "tokens.txt")
        self.encoder_file = os.path.join(load_config().sherpa.base_dir, "encoder.onnx")
        self.decoder_file = os.path.join(load_config().sherpa.base_dir, "decoder.onnx")
        self.joiner_file = os.path.join(load_config().sherpa.base_dir, "joiner.onnx")
        self.keywords = load_config().sherpa.keywords
        self.keyword_score = load_config().sherpa.keyword_score
        self.keyword_threshold = load_config().sherpa.keyword_threshold

        self.kws = sherpa_onnx.KeywordSpotter(
            tokens=self.tokens_file,
            encoder=self.encoder_file,
            decoder=self.decoder_file,
            joiner=self.joiner_file,
            keywords_file=self.keywords_file,
            keywords_score=self.keyword_score,  # 关键词得分阈值
            keywords_threshold=self.keyword_threshold,  # 检测阈值
            max_active_paths=25,  # 降低到4提高准确性
            num_trailing_blanks=1,  # 添加trailing blanks参数
            provider="cpu",
        )
        self.stream = self.kws.create_stream()
        self.audio_buffer = queue.Queue()
        self.logger = logging.getLogger(__file__)

        self.time_idx = 0
        self.flag = False  # 开始有效录音标志
        self.is_silent = True  # 结束有效录音 状态 | 满足这个状态为true且持续一定时间
        self.valid_idx = 0

        self.reset_event = threading.Event()

        self.angle_reader = AngleReader()

    def push_bytes_to_buffer(self, wav_bytes):
        self.audio_buffer.put(wav_bytes)

    def reset(self):
        self.reset_event.set()
        while not self.audio_buffer.empty():
            self.audio_buffer.get(timeout=1)
        self.reset_event.clear()

    def keyword_detected_callback(self):

        def job():
            angle_data = self.angle_reader.get_angle(int(time.time()))
            if angle_data is None:
                return
            angle = angle_data.get("angle")
            if angle_data is None or angle == 0:
                return
            try:
                response = requests.post(
                    f"{load_config().navi.base_url}/api/rotate",
                    json={"angle": angle},
                    timeout=2,
                )
                if response.status_code != 200:
                    self.logger.error(f"Error request ros cmd_vel: {response.text}")
                    return

            except Exception as e:
                self.logger.error(f"Error request ros cmd_vel: {str(e)}")
            pass

        threading.Thread(target=job).start()

    def get_chat_audio_data_after_keyword_detected(self):
        try:
            current_mode = "detect"
            silent_start = None
            is_turn_end = False
            while True:
                try:
                    if self.reset_event.is_set():
                        time.sleep(0.2)
                        continue
                    wav_bytes = self.audio_buffer.get(timeout=10)
                except Exception as e:
                    time.sleep(0.2)
                    continue
                if wav_bytes is None:

                    if silent_start is not None:
                        silent_duration = (
                            datetime.now() - silent_start
                        ).total_seconds()

                        if silent_duration > 10 and current_mode == "chat":
                            # set flag，开始重新检测关键字
                            current_mode = "detect"
                            # yield "我先退下了"
                    else:
                        silent_start = datetime.now()
                    if not is_turn_end:
                        is_turn_end = True
                        yield None
                    continue
                if is_turn_end:
                    is_turn_end = False
                if silent_start is not None:
                    silent_start = None
                if current_mode == "chat":
                    yield wav_bytes
                    continue
                # 处理录音数据
                self.stream.accept_waveform(
                    SAMPLE_RATE, np.frombuffer(wav_bytes, np.int16) / 32768.0
                )

                while self.kws.is_ready(self.stream):
                    self.kws.decode_stream(self.stream)

                    result = self.kws.get_result(self.stream)
                    if result:
                        self.logger.info(f"---Detected keywords: {result}---")
                        self.kws.reset_stream(self.stream)
                        self.keyword_detected_callback()
                        current_mode = "chat"
                        break
        except Exception as e:
            self.logger.error(f"Detect worker error: {e}")

    def callback(self, indata):

        try:
            if isinstance(indata, bytes):
                samples = np.frombuffer(indata, dtype=np.int16)
            else:
                samples = indata[0]
            current_max_db = np.max(samples)

            # If recording, collect data
            if current_max_db > MINDB and not self.flag:
                self.flag = True
                self.valid_idx = self.time_idx
                self.push_bytes_to_buffer(indata[0].tobytes())
                self.time_idx += 1
                return

            if self.flag:
                if current_max_db < MINDB and not self.is_silent:
                    self.is_silent = True
                    self.valid_idx = self.time_idx

                if current_max_db > MINDB:
                    self.is_silent = False
                    self.valid_idx = self.time_idx

                if self.time_idx > self.valid_idx + DELAYTIME * 15 and self.is_silent:
                    self.flag = False
                    self.push_bytes_to_buffer(silence_data)
                    self.push_bytes_to_buffer(None)
                    self.time_idx += 1
                    return

                self.push_bytes_to_buffer(indata[0].tobytes())
            else:
                if self.time_idx > (1 << 4):
                    self.time_idx = 0
                    self.valid_idx = 0
                self.push_bytes_to_buffer(None)

            self.time_idx += 1

        except Exception as e:
            self.logger.error("Error: " + str(e))

    def start(self):
        def read_stream():

            with sd.InputStream(
                # callback=call_back,
                channels=1,
                samplerate=SAMPLE_RATE,
                blocksize=1600,
                dtype="int16",
            ) as f:

                while True:
                    audio_data = f.read(CHUNK)
                    if audio_data:
                        self.callback(audio_data)

        threading.Thread(target=read_stream).start()

    def listen(self):
        for item in self.get_chat_audio_data_after_keyword_detected():
            yield item
