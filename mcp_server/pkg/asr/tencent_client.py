# -*- coding: utf-8 -*-
# 引用 SDK

import time
import sys
import threading
from datetime import datetime
import json

# sys.path.append("../../..")
from pkg.asr.tencent.common import credential
from pkg.asr.tencent.asr import speech_recognizer
import queue

from config.config import get_config
_cfg = get_config()
APPID = _cfg.tencent.appid
SECRET_ID = _cfg.tencent.secret_id
SECRET_KEY = _cfg.tencent.secret_key
ENGINE_MODEL_TYPE = "16k_zh"
SLICE_SIZE = 6400


class MySpeechRecognitionListener(speech_recognizer.SpeechRecognitionListener):
    def __init__(self, id):
        self.id = id
        self.asr_result_queue = queue.Queue()

    def on_recognition_start(self, response):
        return
        print(
            "%s|%s|OnRecognitionStart\n"
            % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), response["voice_id"])
        )

    def on_sentence_begin(self, response):
        rsp_str = json.dumps(response, ensure_ascii=False)
        """
        print(
            "%s|%s|OnRecognitionSentenceBegin, rsp %s\n"
            % (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                response["voice_id"],
                rsp_str,
            )
        )"""

    def on_recognition_result_change(self, response):
        asr_result = response.get("result").get("voice_text_str")
        # print(asr_result)
        """
        rsp_str = json.dumps(response, ensure_ascii=False)
        print(
            "%s|%s|OnResultChange, rsp %s\n"
            % (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                response["voice_id"],
                rsp_str,
            )
        )"""

    def on_sentence_end(self, response):
        asr_result = response.get("result").get("voice_text_str")
        self.asr_result_queue.put_nowait(asr_result)
        """
        rsp_str = json.dumps(response, ensure_ascii=False)
        print(
            "%s|%s|OnSentenceEnd, rsp %s\n"
            % (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                response["voice_id"],
                rsp_str,
            )
        )
        """

    def on_recognition_complete(self, response):
        """
        print(
            "%s|%s|OnRecognitionComplete\n"
            % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), response["voice_id"])
        )"""

    def on_fail(self, response):
        rsp_str = json.dumps(response, ensure_ascii=False)
        print(
            "%s|%s|OnFail,message %s\n"
            % (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                response["voice_id"],
                rsp_str,
            )
        )

    def result_generator(self):
        item = self.asr_result_queue.get()
        yield item

    def result(self):
        item = self.asr_result_queue.get(timeout=3)
        return item


class TencentAsrClient:
    def __init__(self):
        listener = MySpeechRecognitionListener(id)
        credential_var = credential.Credential(SECRET_ID, SECRET_KEY)
        recognizer = speech_recognizer.SpeechRecognizer(
            APPID, credential_var, ENGINE_MODEL_TYPE, listener
        )
        recognizer.set_filter_modal(1)
        recognizer.set_filter_punc(1)
        recognizer.set_filter_dirty(1)
        recognizer.set_need_vad(1)
        # recognizer.set_vad_silence_time(600)
        recognizer.set_voice_format(1)
        recognizer.set_word_info(1)
        # recognizer.set_nonce("12345678")
        recognizer.set_convert_num_mode(1)

        self.listener = listener
        self.recognizer = recognizer
        self.audio_buffer = queue.Queue()

    def run(self):
        self.asr_thread = threading.Thread(target=self.job)
        self.asr_thread.start()
        self.recognizer.wait_connection()

    def write_audio(self, data):
        self.audio_buffer.put(data)

    def stop(self):
        self.recognizer.stop()

    def job(self):
        try:
            self.recognizer.start()

            while True:
                data = self.audio_buffer.get()
                self.recognizer.write(data)
        except Exception as e:
            print(e)
        finally:
            self.recognizer.stop()

    def get_asr_result_generator(self):
        for item in self.listener.result_generator():
            yield item

    def get_asr_result(self):
        return self.listener.result()


def process(id):
    audio = r"C:\Users\miuros\Desktop\iwhale\mcp_server\test.wav"
    listener = MySpeechRecognitionListener(id)
    credential_var = credential.Credential(SECRET_ID, SECRET_KEY)
    recognizer = speech_recognizer.SpeechRecognizer(
        APPID, credential_var, ENGINE_MODEL_TYPE, listener
    )
    recognizer.set_filter_modal(1)
    recognizer.set_filter_punc(1)
    recognizer.set_filter_dirty(1)
    recognizer.set_need_vad(1)
    # recognizer.set_vad_silence_time(600)
    recognizer.set_voice_format(1)
    recognizer.set_word_info(1)
    # recognizer.set_nonce("12345678")
    recognizer.set_convert_num_mode(1)
    try:
        recognizer.start()
        with open(audio, "rb") as f:
            content = f.read(SLICE_SIZE)
            while content:
                recognizer.write(content)
                content = f.read(SLICE_SIZE)
                # sleep模拟实际实时语音发送间隔
                time.sleep(0.02)
    except Exception as e:
        print(e)
    finally:
        recognizer.stop()


def process_multithread(number):
    thread_list = []
    for i in range(0, number):
        thread = threading.Thread(target=process, args=(i,))
        thread_list.append(thread)
        thread.start()

    for thread in thread_list:
        thread.join()


if __name__ == "__main__":
    process(0)
    # process_multithread(20)
