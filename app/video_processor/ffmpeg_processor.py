# app/video_processor/ffmpeg_processor.py
import os
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
import tempfile
import json

from app.config import (
    VIDEO_FORMAT,
    OUTPUT_DIR
)

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class FFmpegProcessor:
    def __init__(self, book_id: str, book_title: str):
        """
        初始化FFmpeg处理器
        
        Args:
            book_id: 书籍ID
            book_title: 书籍标题
        """
        self.book_id = book_id
        self.book_title = book_title
        self.output_dir = OUTPUT_DIR / f"{book_id}_{book_title}"
        os.makedirs(self.output_dir, exist_ok=True)
    
    def create_concat_file(self, video_paths: List[str]) -> str:
        """创建视频合并文件"""
        # 创建临时文件
        fd, concat_file_path = tempfile.mkstemp(suffix='.txt')
        os.close(fd)
        
        # 写入合并文件
        with open(concat_file_path, 'w', encoding='utf-8') as f:
            for video_path in video_paths:
                if os.path.exists(video_path):
                    f.write(f"file '{video_path}'\n")
        
        return concat_file_path
    
    def merge_videos(self, video_paths: List[str], output_path: str, audio_path: Optional[str] = None) -> bool:
        """合并多个视频文件"""
        if not video_paths:
            logger.error("没有视频文件可合并")
            return False
        
        try:
            # 创建合并文件
            concat_file = self.create_concat_file(video_paths)
            
            # 基本FFmpeg命令
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file
            ]
            
            # 如果有背景音乐，添加音频混合
            if audio_path and os.path.exists(audio_path):
                ffmpeg_cmd.extend([
                    "-i", audio_path,
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-map", "0:v",
                    "-map", "0:a",
                    "-map", "1:a",
                    "-shortest",
                    "-af", "volume=0.8,amerge",
                    "-ac", "2"
                ])
            else:
                # 没有背景音乐，只复制原始音频
                ffmpeg_cmd.extend([
                    "-c", "copy"
                ])
            
            # 输出文件
            ffmpeg_cmd.append(output_path)
            
            # 执行FFmpeg命令
            process = subprocess.run(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # 清理临时文件
            try:
                os.remove(concat_file)
            except:
                pass
            
            if process.returncode != 0:
                logger.error(f"视频合并失败: {process.stderr.decode()}")
                return False
            
            logger.info(f"视频合并成功: {output_path}")
            return True
        
        except Exception as e:
            logger.error(f"视频合并异常: {e}")
            return False
    
    def process_chapter(self, chapter: Dict[str, Any]) -> str:
        """处理章节视频"""
        chapter_id = chapter["id"]
        chapter_title = chapter["title"]
        paragraphs = chapter["paragraphs"]
        
        # 收集章节中所有视频路径
        video_paths = []
        for paragraph in paragraphs:
            video_path = paragraph.get("video_path")
            if video_path and os.path.exists(video_path):
                video_paths.append(video_path)
        
        if not video_paths:
            logger.error(f"章节 {chapter_title} 没有可用视频")
            return ""
        
        # 章节输出路径
        chapter_output_path = self.output_dir / f"{chapter_id}_{chapter_title}.{VIDEO_FORMAT}"
        
        # 合并章节视频
        if self.merge_videos(video_paths, str(chapter_output_path)):
            return str(chapter_output_path)
        else:
            return ""
    
    def process_book(self, chapters: List[Dict[str, Any]], bgm_path: Optional[str] = None) -> str:
        """处理整本书视频"""
        # 先处理各章节
        chapter_videos = []
        for chapter in chapters:
            chapter_video = self.process_chapter(chapter)
            if chapter_video:
                chapter_videos.append(chapter_video)
        
        if not chapter_videos:
            logger.error("没有可用的章节视频")
            return ""
        
        # 输出完整书籍视频
        book_output_path = self.output_dir / f"{self.book_id}_{self.book_title}_完整版.{VIDEO_FORMAT}"
        
        # 合并所有章节视频
        if self.merge_videos(chapter_videos, str(book_output_path), bgm_path):
            # 创建项目信息文件
            self.create_project_info(chapters, str(book_output_path))
            return str(book_output_path)
        else:
            return ""
    
    def create_project_info(self, chapters: List[Dict[str, Any]], output_path: str) -> None:
        """创建项目信息文件"""
        info = {
            "book_id": self.book_id,
            "book_title": self.book_title,
            "output_path": output_path,
            "chapters": []
        }
        
        # 收集章节信息
        for chapter in chapters:
            chapter_info = {
                "id": chapter["id"],
                "title": chapter["title"],
                "paragraphs_count": len(chapter["paragraphs"])
            }
            info["chapters"].append(chapter_info)
        
        # 保存信息文件
        info_path = self.output_dir / f"{self.book_id}_info.json"
        with open(info_path, 'w', encoding='utf-8') as f:
            json.dump(info, f, ensure_ascii=False, indent=2)