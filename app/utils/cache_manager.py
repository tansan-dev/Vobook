import os
import time
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from app.config import TEMP_DIR, CACHE_DIR, CACHE_INDEX_FILE, CACHE_MAX_AGE

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CacheManager:
    """缓存管理工具类"""
    
    @staticmethod
    def init_cache_dirs():
        """初始化缓存目录"""
        os.makedirs(CACHE_DIR, exist_ok=True)
        
        # 创建不同类型的缓存子目录
        cache_types = ['deepseek_cache', 'tts_cache', 'html_cache', 'video_cache']
        for cache_type in cache_types:
            os.makedirs(CACHE_DIR / cache_type, exist_ok=True)
    
    @staticmethod
    def get_cache_stats() -> Dict[str, Any]:
        """获取缓存统计信息"""
        if not os.path.exists(CACHE_INDEX_FILE):
            return {"books": 0, "size": 0, "types": {}}
        
        stats = {
            "books": 0,
            "size": 0,
            "types": {
                "deepseek": {"files": 0, "size": 0},
                "tts": {"files": 0, "size": 0},
                "html": {"files": 0, "size": 0},
                "video": {"files": 0, "size": 0}
            }
        }
        
        # 统计书籍数量
        try:
            with open(CACHE_INDEX_FILE, 'r', encoding='utf-8') as f:
                cache_index = json.load(f)
                stats["books"] = len(cache_index)
        except:
            pass
            
        # DeepSeek缓存统计
        deepseek_dir = CACHE_DIR / "deepseek_cache"
        if os.path.exists(deepseek_dir):
            files = [f for f in os.listdir(deepseek_dir) if f.endswith('.json')]
            stats["types"]["deepseek"]["files"] = len(files)
            stats["types"]["deepseek"]["size"] = sum(os.path.getsize(deepseek_dir / f) for f in files)
        
        # TTS缓存统计
        tts_dir = CACHE_DIR / "tts_cache"
        if os.path.exists(tts_dir):
            json_files = [f for f in os.listdir(tts_dir) if f.endswith('.json')]
            mp3_files = [f for f in os.listdir(tts_dir) if f.endswith('.mp3')]
            stats["types"]["tts"]["files"] = len(json_files) + len(mp3_files)
            stats["types"]["tts"]["size"] = sum(os.path.getsize(tts_dir / f) for f in os.listdir(tts_dir))
        
        # 总缓存大小
        stats["size"] = stats["types"]["deepseek"]["size"] + stats["types"]["tts"]["size"]
        
        return stats
    
    @staticmethod
    def update_access_time(epub_path: str, book_id: str = None):
        """更新书籍的缓存访问时间"""
        if not os.path.exists(CACHE_INDEX_FILE):
            return
            
        try:
            with open(CACHE_INDEX_FILE, 'r', encoding='utf-8') as f:
                cache_index = json.load(f)
                
            # 更新访问时间
            if epub_path in cache_index:
                cache_index[epub_path]['last_accessed'] = time.time()
                
                # 如果提供了book_id，确保一致性
                if book_id and cache_index[epub_path]['book_id'] != book_id:
                    logger.warning(f"缓存索引中的book_id与当前不一致: {cache_index[epub_path]['book_id']} vs {book_id}")
                    cache_index[epub_path]['book_id'] = book_id
                
            elif book_id:
                # 如果索引中没有此路径但有book_id，查找匹配的book_id条目
                for path, info in list(cache_index.items()):
                    if info['book_id'] == book_id:
                        # 发现相同book_id的条目，更新路径
                        logger.info(f"更新缓存索引: {path} -> {epub_path}")
                        cache_index[epub_path] = info
                        cache_index[epub_path]['last_accessed'] = time.time()
                        del cache_index[path]
                        break
            
            with open(CACHE_INDEX_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"更新缓存访问时间失败: {e}")
    
    @staticmethod
    def clean_expired_cache(max_age_days: int = None):
        """清理过期的缓存"""
        if max_age_days is None:
            max_age_days = CACHE_MAX_AGE
            
        if not os.path.exists(CACHE_INDEX_FILE):
            return 0
            
        now = time.time()
        max_age_seconds = max_age_days * 24 * 60 * 60
        
        cleaned_count = 0
        try:
            with open(CACHE_INDEX_FILE, 'r', encoding='utf-8') as f:
                cache_index = json.load(f)
                
            # 标记要删除的条目
            to_delete = []
            
            for path, info in cache_index.items():
                last_accessed = info.get('last_accessed', 0)
                age = now - last_accessed
                
                if age > max_age_seconds:
                    # 清理过期的缓存目录
                    cache_dir = info.get('cache_dir')
                    book_id = info.get('book_id')
                    
                    if cache_dir and os.path.exists(cache_dir):
                        shutil.rmtree(cache_dir)
                        cleaned_count += 1
                    
                    # 清理临时目录中的相关文件
                    if book_id:
                        temp_pattern = f"{book_id}_*"
                        for temp_file in TEMP_DIR.glob(temp_pattern):
                            if os.path.isfile(temp_file):
                                os.remove(temp_file)
                            elif os.path.isdir(temp_file):
                                shutil.rmtree(temp_file)
                    
                    to_delete.append(path)
            
            # 从索引中删除
            for path in to_delete:
                del cache_index[path]
                
            # 保存更新后的索引
            with open(CACHE_INDEX_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_index, f, ensure_ascii=False, indent=2)
            
            # 清理全局缓存中的孤立文件（没有对应的book_id）
            # 这里可以添加更复杂的清理逻辑
            
            logger.info(f"缓存清理完成，删除了 {len(to_delete)} 个过期缓存")
            return len(to_delete)
        except Exception as e:
            logger.error(f"缓存清理失败: {e}")
            return 0
    
    @staticmethod
    def clean_book_cache(book_id: str):
        """清理指定书籍的缓存"""
        try:
            # 找到对应的缓存索引条目
            if os.path.exists(CACHE_INDEX_FILE):
                with open(CACHE_INDEX_FILE, 'r', encoding='utf-8') as f:
                    cache_index = json.load(f)
                
                # 查找包含此book_id的条目
                to_delete = []
                for path, info in cache_index.items():
                    if info.get('book_id') == book_id:
                        # 清理缓存目录
                        cache_dir = info.get('cache_dir')
                        if cache_dir and os.path.exists(cache_dir):
                            shutil.rmtree(cache_dir)
                        to_delete.append(path)
                
                # 从索引中删除
                for path in to_delete:
                    del cache_index[path]
                
                # 保存更新后的索引
                with open(CACHE_INDEX_FILE, 'w', encoding='utf-8') as f:
                    json.dump(cache_index, f, ensure_ascii=False, indent=2)
            
            # 清理临时目录中的相关文件
            temp_pattern = f"{book_id}_*"
            for temp_file in TEMP_DIR.glob(temp_pattern):
                if os.path.isfile(temp_file):
                    os.remove(temp_file)
                elif os.path.isdir(temp_file):
                    shutil.rmtree(temp_file)
            
            logger.info(f"已清理书籍缓存: {book_id}")
            return True
        except Exception as e:
            logger.error(f"清理书籍缓存失败: {e}")
            return False