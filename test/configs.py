TTS_APPID = "6813388294"  # 替换为你的APPID
TTS_ACCESS_TOKEN = "eImThtW9vFVGmzR4vLnVduT68vWfj8MV"  # 替换为你的Access Token
TTS_VOICE_TYPE = "zh_male_yangguangqingnian_emo_v2_mars_bigtts"  # 替换为你想要的音色
TTS_ENCODING = "pcm"  # 输出音频格式


# --- Configuration ---
SAMPLE_RATE = 48000  # Hz
CHANNELS = 1  # mono
SAMPLE_WIDTH = 2  # 2 bytes for 16-bit audio
RECORD_DURATION = 300  # 5 minutes in seconds
PRE_TRIGGER_BUFFER = 2.0  # seconds of audio to keep before keyword detection

# Sherpa-ONNX Keyword Spotting Configuration
# You need to download a KWS model from sherpa-onnx
# Example: https://github.com/k2-fsa/sherpa-onnx/releases/tag/kws-models
KWS_MODEL_DIR = "/home/wheeltec/steering/keyword_wakeup_model/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"  # Update this path
KEYWORDS_FILE = f"/home/wheeltec/metamee/test/keywords.txt"  # Keywords file
TOKENS_FILE = f"{KWS_MODEL_DIR}/tokens.txt"  # Tokens file
ENCODER_MODEL = f"{KWS_MODEL_DIR}/encoder-epoch-13-avg-2-chunk-16-left-64.onnx"
DECODER_MODEL = f"{KWS_MODEL_DIR}/decoder-epoch-13-avg-2-chunk-16-left-64.onnx"
JOINER_MODEL = f"{KWS_MODEL_DIR}/joiner-epoch-13-avg-2-chunk-16-left-64.onnx"

# Keyword settings
KEYWORD_THRESHOLD = 0.3  # Detection threshold (0.0-1.0) - 提高到0.6减少误检
KEYWORD_SCORE = 0.3  # Keyword score threshold
KEYWORDS = ["小金小金"]  # Your wake words
