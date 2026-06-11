import numpy as np
import sherpa_onnx
import wave

kws = sherpa_onnx.KeywordSpotter(
    tokens="sherpa-onnx/tokens.txt",
    encoder="sherpa-onnx/encoder.onnx",
    decoder="sherpa-onnx/decoder.onnx",
    joiner="sherpa-onnx/joiner.onnx",
    keywords_file="sherpa-onnx/keywords_baiying.txt",
    keywords_score=1,  # 关键词得分阈值
    keywords_threshold=0.1,  # 检测阈值
    max_active_paths=10,  # 降低到4提高准确性
    num_trailing_blanks=1,  # 添加trailing blanks参数
    provider="cpu",
)
stream = kws.create_stream()


def get_chat_audio_data_after_keyword_detected():
    f = wave.open("debug.wav", "rb")
    n = f.getnframes()
    CHUNK_SIZE = 1024
    readed = 0
    try:
        while n > readed:

            wav_bytes = f.readframes(CHUNK_SIZE)
            readed += CHUNK_SIZE
            if wav_bytes is None:
                return

            stream.accept_waveform(16000, np.frombuffer(wav_bytes, np.int16) / 32768.0)

            while kws.is_ready(stream):
                kws.decode_stream(stream)

                result = kws.get_result(stream)
                if result:
                    print(f"---Detected keywords: {result}---")
                    kws.reset_stream(stream)
    except Exception as e:
        print(f"Detect worker error: {e}")


get_chat_audio_data_after_keyword_detected()
