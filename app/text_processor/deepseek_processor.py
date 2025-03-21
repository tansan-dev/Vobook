# app/text_processor/deepseek_processor.py
import requests
import json
import os
import time
from typing import Dict, Any, List
import hashlib
from pathlib import Path
import logging
from concurrent.futures import ThreadPoolExecutor

from app.config import DEEPSEEK_API_KEY, DEEPSEEK_API_URL, MAX_WORKERS, TEMP_DIR, CACHE_DIR, CACHE_ENABLED

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DeepSeekProcessor:
    def __init__(self, book_id: str):
        """
        初始化DeepSeek处理器
        
        Args:
            book_id: 书籍ID，用于缓存管理
        """
        self.api_key = DEEPSEEK_API_KEY
        self.api_url = DEEPSEEK_API_URL
        self.book_id = book_id
        
        # 使用全局缓存目录，而不是依赖book_id的临时目录
        self.global_cache_dir = CACHE_DIR / "deepseek_cache"
        os.makedirs(self.global_cache_dir, exist_ok=True)
        
        # 为了保持向后兼容，仍然创建book_id相关的缓存目录
        self.book_cache_dir = TEMP_DIR / f"{book_id}_deepseek_cache"
        os.makedirs(self.book_cache_dir, exist_ok=True)
    
    def _get_cache_path(self, text: str) -> Path:
        """获取缓存文件路径"""
        # 使用文本的哈希值作为缓存文件名
        text_hash = hashlib.md5(text.encode()).hexdigest()
        
        # 优先检查全局缓存
        global_cache_path = self.global_cache_dir / f"{text_hash}.json"
        if global_cache_path.exists():
            return global_cache_path
            
        # 然后检查书籍特定缓存
        book_cache_path = self.book_cache_dir / f"{text_hash}.json"
        return book_cache_path
    
    def _is_cached(self, text: str) -> bool:
        """检查是否已缓存（全局或书籍特定）"""
        if not CACHE_ENABLED:
            return False
            
        cache_path = self._get_cache_path(text)
        return cache_path.exists()
    
    def _get_from_cache(self, text: str) -> str:
        """从缓存获取结果"""
        if not CACHE_ENABLED:
            return None
            
        cache_path = self._get_cache_path(text)
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 记录缓存命中日志
                is_global = str(cache_path).startswith(str(self.global_cache_dir))
                logger.info(f"DeepSeek缓存命中: {cache_path.name} ({'全局' if is_global else '书籍特定'}缓存)")
                return data.get('result', text)
            except Exception as e:
                logger.error(f"读取缓存失败: {e}")
        return None
    
    def _save_to_cache(self, text: str, result: str) -> None:
        """保存结果到缓存"""
        if not CACHE_ENABLED:
            return
            
        # 使用文本的哈希值作为缓存文件名
        text_hash = hashlib.md5(text.encode()).hexdigest()
        
        # 同时保存到全局缓存和书籍特定缓存
        global_cache_path = self.global_cache_dir / f"{text_hash}.json"
        book_cache_path = self.book_cache_dir / f"{text_hash}.json"
        
        cache_data = {
            'original': text,
            'result': result,
            'timestamp': time.time(),
            'book_id': self.book_id  # 记录来源书籍ID，便于管理
        }
        
        try:
            # 保存到全局缓存
            with open(global_cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False)
                
            # 保存到书籍特定缓存
            with open(book_cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False)
                
            logger.info(f"DeepSeek结果已缓存: {text_hash}")
        except Exception as e:
            logger.error(f"保存缓存失败: {e}")
    
    def convert_to_oral(self, text: str) -> str:
        """将书面语转换为口语化表达"""
        # 先检查缓存
        if self._is_cached(text):
            cached_result = self._get_from_cache(text)
            if cached_result:
                return cached_result
        
        # 如果未缓存，调用 API
        if not self.api_key:
            logger.warning("未提供DeepSeek API密钥，将使用原文本")
            return text
        
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            # 构建 DeepSeek 请求
            payload = {
                "model": "deepseek-v3-241226",
                "messages": [
                    {
                        "role": "system", 
                        "content": "你是一个专业的有声书朗读转换助手。请将以下书面语文本改写成适合朗读的自然口语，保持原意的同时让表达更加流畅自然。不要添加额外解释，直接输出转换后的文本。"
                    },
                    {
                        "role": "user",
                        "content": f"请将下面这段文字转换成适合有声书朗读的口语化表达，保持原文意思不变：\n\n{text}"
                    }
                ],
                "temperature": 0.3,
                "max_tokens": 2000
            }
            
            response = requests.post(self.api_url, headers=headers, json=payload)
            
            if response.status_code == 200:
                result = response.json()
                oral_text = result['choices'][0]['message']['content']
                
                # 清理多余的引号和说明文字
                oral_text = oral_text.strip('"\'')
                oral_text = oral_text.replace("以下是转换后的口语化表达：", "")
                oral_text = oral_text.replace("以下是适合有声书朗读的口语化表达：", "")
                oral_text = oral_text.strip()
                
                # 缓存结果
                self._save_to_cache(text, oral_text)
                
                return oral_text
            else:
                logger.error(f"DeepSeek API 请求失败: {response.status_code} - {response.text}")
                return text
                
        except Exception as e:
            logger.error(f"调用 DeepSeek API 失败: {e}")
            return text
    
    def process_paragraph(self, paragraph: Dict[str, Any]) -> Dict[str, Any]:
        """处理单个段落"""
        # 如果是图片，直接返回
        if paragraph["type"] == "image":
            return paragraph
        
        # 处理文本段落
        original_text = paragraph["content"]
        oral_text = self.convert_to_oral(original_text)
        
        # 更新段落内容
        processed_paragraph = paragraph.copy()
        processed_paragraph["original_content"] = original_text
        processed_paragraph["content"] = oral_text
        
        return processed_paragraph
    
    def process_chapters(self, chapters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """处理所有章节的段落"""
        processed_chapters = []
        
        for chapter in chapters:
            # 创建章节副本
            processed_chapter = chapter.copy()
            paragraphs = chapter["paragraphs"]
            
            # 使用线程池并行处理段落
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                processed_paragraphs = list(executor.map(self.process_paragraph, paragraphs))
            
            processed_chapter["paragraphs"] = processed_paragraphs
            processed_chapters.append(processed_chapter)
        
        return processed_chapters