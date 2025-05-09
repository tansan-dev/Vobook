# app/voice_generator/azure_tts.py
import os
import time
import json
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Tuple
import logging
import azure.cognitiveservices.speech as speechsdk
from concurrent.futures import ThreadPoolExecutor
import shutil

from app.config import (
    AZURE_SPEECH_KEY, 
    AZURE_SPEECH_REGION, 
    AZURE_VOICE_NAME,
    AZURE_SPEECH_RATE,
    AZURE_SPEECH_PITCH,
    MAX_WORKERS,
    TEMP_DIR,
    CACHE_DIR,
    CACHE_ENABLED
)

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AzureTTS:
    def __init__(self, book_id: str):
        """
        初始化Azure TTS服务
        
        Args:
            book_id: 书籍ID，用于管理音频文件
        """
        self.speech_key = AZURE_SPEECH_KEY
        self.speech_region = AZURE_SPEECH_REGION
        self.voice_name = AZURE_VOICE_NAME
        self.speech_rate = AZURE_SPEECH_RATE
        self.speech_pitch = AZURE_SPEECH_PITCH
        
        self.book_id = book_id
        
        # 全局TTS缓存目录
        self.global_audio_cache = CACHE_DIR / "tts_cache"
        os.makedirs(self.global_audio_cache, exist_ok=True)
        
        # 书籍特定的音频目录
        self.book_audio_dir = TEMP_DIR / f"{book_id}_audio"
        os.makedirs(self.book_audio_dir, exist_ok=True)
        
        # 初始化Azure语音配置
        if self.speech_key:
            self.speech_config = speechsdk.SpeechConfig(
                subscription=self.speech_key, 
                region=self.speech_region
            )
            self.speech_config.speech_synthesis_voice_name = self.voice_name
        else:
            self.speech_config = None
            logger.warning("未提供Azure Speech密钥，TTS功能将不可用")
    
    def _get_audio_path(self, paragraph_id: str, content_hash: str = None) -> Path:
        """获取音频文件路径"""
        if content_hash:
            return self.book_audio_dir / f"{content_hash}.mp3"
        else:
            return self.book_audio_dir / f"{paragraph_id}.mp3"
    
    def _get_metadata_path(self, paragraph_id: str, content_hash: str = None) -> Path:
        """获取元数据文件路径"""
        if content_hash:
            return self.book_audio_dir / f"{content_hash}.json"
        else:
            return self.book_audio_dir / f"{paragraph_id}.json"
    
    def _get_global_audio_path(self, content_hash: str) -> Path:
        """获取全局缓存中的音频路径"""
        return self.global_audio_cache / f"{content_hash}.mp3"
    
    def _get_global_metadata_path(self, content_hash: str) -> Path:
        """获取全局缓存中的元数据路径"""
        return self.global_audio_cache / f"{content_hash}.json"
    
    def _is_in_global_cache(self, content_hash: str) -> bool:
        """检查是否在全局缓存中"""
        if not CACHE_ENABLED:
            return False
            
        audio_path = self._get_global_audio_path(content_hash)
        meta_path = self._get_global_metadata_path(content_hash)
        return audio_path.exists() and meta_path.exists()
    
    def _is_generated(self, paragraph_id: str, content: str = None) -> bool:
        """检查是否已生成音频文件"""
        if not CACHE_ENABLED:
            return False
            
        # 如果提供了内容，使用内容哈希查找
        if content:
            content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()
            
            # 先检查全局缓存
            if self._is_in_global_cache(content_hash):
                return True
                
            # 再检查书籍特定缓存
            audio_path = self._get_audio_path(paragraph_id, content_hash)
            metadata_path = self._get_metadata_path(paragraph_id, content_hash)
            return audio_path.exists() and metadata_path.exists()
        else:
            # 使用段落ID查找
            audio_path = self._get_audio_path(paragraph_id)
            metadata_path = self._get_metadata_path(paragraph_id)
            return audio_path.exists() and metadata_path.exists()
    
    def _copy_from_global_cache(self, content: str, paragraph_id: str) -> Dict[str, Any]:
        """从全局缓存复制到书籍特定目录"""
        content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()
        
        # 全局缓存路径
        global_audio = self._get_global_audio_path(content_hash)
        global_meta = self._get_global_metadata_path(content_hash)
        
        # 书籍特定路径
        book_audio = self._get_audio_path(paragraph_id, content_hash)
        book_meta = self._get_metadata_path(paragraph_id, content_hash)
        
        # 复制音频文件
        shutil.copy2(global_audio, book_audio)
        
        # 读取并保存元数据
        with open(global_meta, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        # 更新元数据中的一些信息
        metadata['copied_from_global'] = True
        metadata['copy_time'] = time.time()
        
        # 保存到书籍特定目录
        with open(book_meta, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False)
        
        logger.info(f"从全局缓存复制TTS结果: {paragraph_id} - {content_hash}")
        
        return {
            "audio_path": str(book_audio),
            "duration": metadata["duration"],
            "word_timings": metadata["word_timings"]
        }
    
    def _save_to_global_cache(self, content: str, audio_path: Path, metadata: Dict) -> None:
        """保存结果到全局缓存"""
        if not CACHE_ENABLED:
            return
            
        content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()
        
        # 全局缓存路径
        global_audio = self._get_global_audio_path(content_hash)
        global_meta = self._get_global_metadata_path(content_hash)
        
        # 复制音频文件
        shutil.copy2(audio_path, global_audio)
        
        # 更新元数据中的一些信息
        metadata['saved_to_global'] = True
        metadata['save_time'] = time.time()
        metadata['book_id'] = self.book_id
        
        # 保存元数据
        with open(global_meta, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False)
            
        logger.info(f"TTS结果已保存到全局缓存: {content_hash}")
    
    def _generate_empty_audio(self, paragraph_id: str, duration: float = 5.0) -> Dict[str, Any]:
        """为图片等创建空白音频和元数据"""
        audio_path = self._get_audio_path(paragraph_id)
        metadata_path = self._get_metadata_path(paragraph_id)
        
        # 创建一个静音音频文件
        if not audio_path.exists():
            # 使用ffmpeg创建静音音频
            os.system(f"ffmpeg -f lavfi -i anullsrc=r=24000:cl=mono -t {duration} -q:a 9 -acodec libmp3lame {audio_path} -y")
        
        # 创建元数据
        metadata = {
            "duration": duration,
            "word_timings": [],
            "created_at": time.time()
        }
        
        # 保存元数据
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False)
        
        return {
            "audio_path": str(audio_path),
            "duration": duration,
            "word_timings": []
        }
    
    def generate_speech(self, paragraph: Dict[str, Any]) -> Dict[str, Any]:
        """生成语音并返回音频路径和时长信息"""
        paragraph_id = paragraph["id"]
        
        # 如果是图片，创建空白音频
        if paragraph["type"] == "image":
            return self._generate_empty_audio(paragraph_id)
        
        # 要合成的文本
        text = paragraph["content"]
        if not text.strip():
            return self._generate_empty_audio(paragraph_id, 1.0)
        
        # 计算内容哈希
        content_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        
        # 检查全局缓存
        if self._is_in_global_cache(content_hash):
            logger.info(f"TTS全局缓存命中: {paragraph_id}")
            return self._copy_from_global_cache(text, paragraph_id)
            
        # 检查书籍特定缓存
        if self._is_generated(paragraph_id, text):
            # 读取元数据
            metadata_path = self._get_metadata_path(paragraph_id, content_hash)
            if not metadata_path.exists():
                metadata_path = self._get_metadata_path(paragraph_id)
                
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            # 获取对应的音频路径
            if os.path.exists(self._get_audio_path(paragraph_id, content_hash)):
                audio_path = self._get_audio_path(paragraph_id, content_hash)
            else:
                audio_path = self._get_audio_path(paragraph_id)
                
            logger.info(f"TTS书籍缓存命中: {paragraph_id}")
            
            return {
                "audio_path": str(audio_path),
                "duration": metadata["duration"],
                "word_timings": metadata["word_timings"]
            }
        
        # 如果没有配置Azure语音服务，创建空白音频
        if not self.speech_config:
            logger.warning(f"未配置Azure语音服务，为段落 {paragraph_id} 创建空白音频")
            return self._generate_empty_audio(paragraph_id, 1.0)
        
        # 设置输出格式和路径
        audio_path = self._get_audio_path(paragraph_id, content_hash)
        audio_config = speechsdk.audio.AudioOutputConfig(filename=str(audio_path))
        
        # 构建SSML
        ssml = f"""
        <speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">
            <voice name="{self.voice_name}">
                <prosody rate="{self.speech_rate}" pitch="{self.speech_pitch}">
                    {text}
                </prosody>
            </voice>
        </speak>
        """
        
        # 创建语音合成器
        speech_synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=self.speech_config, 
            audio_config=audio_config
        )
        
        # 用于存储单词时间信息
        word_timings = []
        
        # 订阅单词边界事件
        def word_boundary_callback(evt):
            """处理单词边界事件"""
            nonlocal word_timings
            
            # 处理audio_offset - 可能是整数微秒或timedelta对象
            if isinstance(evt.audio_offset, int):
                audio_offset = evt.audio_offset / 10000000  # 将微秒转换为秒
            else:  # 假设是timedelta对象
                audio_offset = evt.audio_offset.total_seconds()
            
            # 处理duration - 可能是整数微秒或timedelta对象
            if isinstance(evt.duration, int):
                duration = evt.duration / 10000000  # 将微秒转换为秒
            else:  # 假设是timedelta对象
                duration = evt.duration.total_seconds()
            
            word_timings.append({
                "text": evt.text,
                "audio_offset": audio_offset,
                "duration": duration
            })
        
        # 注册回调
        speech_synthesizer.synthesis_word_boundary.connect(word_boundary_callback)
        
        try:
            # 使用SSML合成语音
            result = speech_synthesizer.speak_ssml_async(ssml).get()
            
            # 检查结果
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                logger.info(f"语音合成成功: {paragraph_id}")
                
                # 计算音频时长（秒）
                if word_timings:
                    last_word = word_timings[-1]
                    duration = last_word["audio_offset"] + last_word["duration"]
                else:
                    # 如果没有单词时间信息，估算时长
                    duration = len(text) * 0.1  # 粗略估计
                
                # 保存元数据
                metadata = {
                    "duration": duration,
                    "word_timings": word_timings,
                    "created_at": time.time(),
                    "content_hash": content_hash
                }
                
                # 保存到书籍特定缓存
                with open(self._get_metadata_path(paragraph_id, content_hash), 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, ensure_ascii=False)
                
                # 保存到全局缓存
                self._save_to_global_cache(text, audio_path, metadata)
                
                return {
                    "audio_path": str(audio_path),
                    "duration": duration,
                    "word_timings": word_timings
                }
            else:
                logger.error(f"语音合成失败: {result.reason}")
                return self._generate_empty_audio(paragraph_id, 1.0)
        
        except Exception as e:
            logger.error(f"语音合成异常: {e}")
            return self._generate_empty_audio(paragraph_id, 1.0)
    
    def process_paragraphs(self, paragraphs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """处理多个段落"""
        processed_paragraphs = []
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # 并行处理段落
            future_to_paragraph = {executor.submit(self.generate_speech, paragraph): paragraph for paragraph in paragraphs}
            
            for future in future_to_paragraph:
                paragraph = future_to_paragraph[future]
                try:
                    speech_info = future.result()
                    # 合并语音信息到段落中
                    updated_paragraph = paragraph.copy()
                    updated_paragraph.update({
                        "audio_path": speech_info["audio_path"],
                        "duration": speech_info["duration"],
                        "word_timings": speech_info["word_timings"]
                    })
                    processed_paragraphs.append(updated_paragraph)
                except Exception as e:
                    logger.error(f"处理段落 {paragraph['id']} 失败: {e}")
                    # 使用原段落作为备选
                    processed_paragraphs.append(paragraph)
        
        # 按原始顺序排序
        processed_paragraphs.sort(key=lambda p: paragraphs.index(next(orig for orig in paragraphs if orig["id"] == p["id"])))
        
        return processed_paragraphs