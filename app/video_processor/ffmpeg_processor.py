# app/video_processor/ffmpeg_processor.py
import os
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
import tempfile
import json
import shutil

from app.config import (
    VIDEO_FORMAT,
    OUTPUT_DIR,
    VIDEO_FPS
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
    
    def create_concat_file(self, video_paths: List[str], with_transitions: bool = True) -> str:
        """创建视频合并文件，支持添加转场效果"""
        # 创建临时文件
        fd, concat_file_path = tempfile.mkstemp(suffix='.txt')
        os.close(fd)
        
        # 写入合并文件
        with open(concat_file_path, 'w', encoding='utf-8') as f:
            for video_path in video_paths:
                if os.path.exists(video_path):
                    f.write(f"file '{video_path}'\n")
                    # 如果启用转场并且不是最后一个视频，添加转场设置
                    if with_transitions and video_path != video_paths[-1]:
                        # 默认使用交叉淡入淡出
                        f.write(f"duration 0.5\n")  # 0.5秒转场
                        f.write(f"transition xfade duration 0.5\n")
        
        return concat_file_path
    
    def add_fade_effects(self, video_path: str, output_path: str) -> str:
        """添加淡入淡出效果到视频"""
        if not os.path.exists(video_path):
            logger.error(f"视频文件不存在: {video_path}")
            return video_path
            
        # 获取视频时长
        try:
            probe_cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", video_path
            ]
            duration = float(subprocess.check_output(probe_cmd).decode('utf-8').strip())
            
            # 添加淡入淡出效果
            # 淡入: 0-0.5秒, 淡出: 最后0.5秒
            fade_cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-filter_complex", f"fade=t=in:st=0:d=0.5,fade=t=out:st={duration-0.5}:d=0.5",
                "-c:a", "copy",  # 复制音频不变
                output_path
            ]
            
            subprocess.run(fade_cmd, check=True)
            return output_path
        except Exception as e:
            logger.error(f"添加淡入淡出效果失败: {e}")
            return video_path
    
    def process_paragraph(self, paragraph: Dict[str, Any]) -> str:
        """处理单个段落视频，确保音频正确融合"""
        paragraph_id = paragraph["id"]
        video_path = paragraph.get("video_path")
        audio_path = paragraph.get("audio_path")
        
        if not video_path or not os.path.exists(video_path):
            logger.error(f"段落 {paragraph_id} 没有可用视频")
            return ""
        
        # 如果没有音频，直接返回原视频
        if not audio_path or not os.path.exists(audio_path):
            logger.warning(f"段落 {paragraph_id} 没有对应的音频")
            return video_path
        
        # 输出带音频的视频路径
        output_path = Path(str(video_path).replace(".mp4", "_with_audio.mp4"))
        
        # 如果已存在，直接返回
        if output_path.exists():
            return str(output_path)
        
        # 获取视频时长
        try:
            probe_cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", video_path
            ]
            video_duration = float(subprocess.check_output(probe_cmd).decode('utf-8').strip())
            logger.info(f"视频时长: {video_duration}秒")
            
            # 获取音频时长
            probe_cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", audio_path
            ]
            audio_duration = float(subprocess.check_output(probe_cmd).decode('utf-8').strip())
            logger.info(f"音频时长: {audio_duration}秒")
            
            # 如果视频时长与音频时长差异过大，需要调整视频速度
            if abs(video_duration - audio_duration) > 0.5:  # 0.5秒容差
                logger.warning(f"视频时长 ({video_duration}秒) 与音频时长 ({audio_duration}秒) 不匹配，调整视频时长")
                
                # 创建临时视频
                temp_video = str(output_path).replace("_with_audio.mp4", "_temp.mp4")
                
                # 调整视频时长以匹配音频
                adjust_cmd = [
                    "ffmpeg", "-y", 
                    "-i", video_path,
                    "-filter:v", f"setpts={audio_duration/video_duration}*PTS",
                    "-an", temp_video
                ]
                
                subprocess.run(adjust_cmd, check=True)
                
                # 使用调整后的视频
                video_path = temp_video
        except Exception as e:
            logger.error(f"获取媒体时长失败: {e}")
        
        # 合并视频和音频
        try:
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", audio_path,
                "-c:v", "copy",  # 复制视频流不重新编码
                "-c:a", "aac",   # 音频转换为AAC
                "-map", "0:v",   # 使用第一个输入的视频
                "-map", "1:a",   # 使用第二个输入的音频
                "-shortest",     # 使用最短输入的时长
                str(output_path)
            ]
            
            logger.info(f"正在为段落 {paragraph_id} 添加音频: {' '.join(ffmpeg_cmd)}")
            
            process = subprocess.run(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            if process.returncode != 0:
                logger.error(f"添加音频失败: {process.stderr.decode()}")
                return video_path  # 失败时返回原始视频
            
            # 删除临时文件
            temp_video = str(output_path).replace("_with_audio.mp4", "_temp.mp4")
            if os.path.exists(temp_video):
                os.remove(temp_video)
                
            # 添加淡入淡出效果
            fade_output = str(output_path).replace("_with_audio.mp4", "_with_fade.mp4")
            if not os.path.exists(fade_output):
                fade_output = self.add_fade_effects(str(output_path), fade_output)
                # 如果成功添加了淡入淡出，使用新路径
                if os.path.exists(fade_output) and os.path.getsize(fade_output) > 0:
                    return fade_output
            
            return str(output_path)
        except Exception as e:
            logger.error(f"处理段落视频异常: {e}")
            return video_path  # 发生异常时返回原始视频
    
    def merge_videos(self, video_paths: List[str], output_path: str, audio_path: Optional[str] = None) -> bool:
        """合并多个视频文件，添加平滑转场"""
        if not video_paths:
            logger.error("没有视频文件可合并")
            return False
        
        try:
            # 创建包含转场效果的合并文件
            concat_file = self.create_concat_file(video_paths, with_transitions=True)
            
            # 基本FFmpeg命令，使用过滤器实现平滑转场
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
                    "-filter_complex", "amerge=inputs=2",
                    "-ac", "2"
                ])
            else:
                # 没有背景音乐，只复制原始音频和视频
                ffmpeg_cmd.extend([
                    "-c", "copy"
                ])
            
            # 输出文件
            ffmpeg_cmd.append(output_path)
            
            logger.info(f"合并视频命令: {' '.join(ffmpeg_cmd)}")
            
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
                
                # 如果带转场效果失败，尝试简单合并
                logger.info("尝试不使用转场效果进行合并...")
                concat_file_simple = self.create_concat_file(video_paths, with_transitions=False)
                
                simple_cmd = [
                    "ffmpeg", "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", concat_file_simple,
                    "-c", "copy",
                    output_path
                ]
                
                process = subprocess.run(
                    simple_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                
                try:
                    os.remove(concat_file_simple)
                except:
                    pass
                
                if process.returncode != 0:
                    logger.error(f"简单视频合并也失败了: {process.stderr.decode()}")
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
        
        # 为每个段落添加音频和淡入淡出效果
        processed_videos = []
        for paragraph in paragraphs:
            processed_video = self.process_paragraph(paragraph)
            if processed_video:
                processed_videos.append(processed_video)
        
        if not processed_videos:
            logger.error(f"章节 {chapter_title} 没有可用视频")
            return ""
        
        # 章节输出路径
        chapter_output_path = self.output_dir / f"{chapter_id}_{chapter_title}.{VIDEO_FORMAT}"
        
        # 合并章节视频
        if self.merge_videos(processed_videos, str(chapter_output_path)):
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