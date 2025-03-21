# app/config.py
import os
from pathlib import Path

# 项目基础路径
BASE_DIR = Path(__file__).resolve().parent.parent

# 数据目录
DATA_DIR = BASE_DIR / "data"
INPUT_DIR = DATA_DIR / "inputs"
TEMP_DIR = DATA_DIR / "temp"
OUTPUT_DIR = DATA_DIR / "outputs"
CACHE_DIR = DATA_DIR / "cache"

# 确保目录存在
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# 缓存配置
CACHE_ENABLED = True  # 默认启用缓存
CACHE_MAX_AGE = 30  # 缓存最大保留天数
CACHE_INDEX_FILE = TEMP_DIR / "book_cache_index.json"

# DeepSeek API 配置
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"

# Azure TTS 配置
AZURE_SPEECH_KEY = os.environ.get("AZURE_SPEECH_KEY", "")
AZURE_SPEECH_REGION = os.environ.get("AZURE_SPEECH_REGION", "eastasia")
AZURE_VOICE_NAME = "zh-CN-XiaochenNeural"  # 默认女声
AZURE_SPEECH_RATE = "+0%"  # 语速调整
AZURE_SPEECH_PITCH = "+0Hz"  # 音调调整

# 渲染配置
FONT_FAMILY = "'Noto Serif SC', serif"  # 默认字体
FONT_SIZE = "18px"  # 默认字体大小
LINE_HEIGHT = "1.7"  # 默认行高
BACKGROUND_COLOR = "#F5F5DC"  # 默认背景色（米色）
TEXT_COLOR = "#333333"  # 默认文字颜色
HIGHLIGHT_COLOR = "#FFFF00"  # 高亮颜色（黄色）

# 视频配置
VIDEO_WIDTH = 1920 # 视频宽度
VIDEO_HEIGHT = 1080  # 视频高度
VIDEO_FPS = 30  # 视频帧率
VIDEO_FORMAT = "mp4"  # 视频格式
SPEED_FACTOR = 2.0  # 录制加速倍率

# 插图处理
IMAGE_DISPLAY_TIME = 5  # 插图显示时间（秒）

# 并发设置
MAX_WORKERS = os.cpu_count() or 4  # 最大工作进程数