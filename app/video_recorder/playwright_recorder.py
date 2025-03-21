# app/video_recorder/playwright_recorder.py
import os
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import json
import subprocess
import time
import re
from concurrent.futures import ThreadPoolExecutor

from playwright.async_api import async_playwright
import tempfile

from app.config import (
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    VIDEO_FPS,
    SPEED_FACTOR,
    MAX_WORKERS,
    TEMP_DIR
)

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PlaywrightRecorder:
    def __init__(self, book_id: str):
        """
        初始化Playwright录制器
        
        Args:
            book_id: 书籍ID，用于管理视频文件
        """
        self.book_id = book_id
        self.video_dir = TEMP_DIR / f"{book_id}_video"
        os.makedirs(self.video_dir, exist_ok=True)
    
    def _get_video_path(self, paragraph_id: str) -> Path:
        """获取视频文件路径"""
        return self.video_dir / f"{paragraph_id}.mp4"
    
    def _get_frames_dir(self, paragraph_id: str) -> Path:
        """获取帧图像目录"""
        frames_dir = self.video_dir / f"{paragraph_id}_frames"
        os.makedirs(frames_dir, exist_ok=True)
        return frames_dir
    
    async def capture_frames(self, page, duration, frames_dir, fps=VIDEO_FPS):
        """按指定的帧率捕获页面截图"""
        total_frames = int(duration * fps)
        frame_interval = 1.0 / fps
        
        logger.info(f"开始截图，总帧数: {total_frames}, 间隔: {frame_interval}秒")
        
        for frame_index in range(total_frames):
            frame_time = frame_index * frame_interval
            
            # 计算当前时间进度并设置到页面中
            await page.evaluate(f"window.updatePlaybackTime({frame_time})")
            
            # 截图并保存
            frame_path = os.path.join(frames_dir, f"frame_{frame_index:06d}.png")
            await page.screenshot(path=frame_path, type='png')
            
            # 等待直到下一帧的时间
            if frame_index < total_frames - 1:
                # 使用精确定时
                await asyncio.sleep(frame_interval * 0.8)  # 略微加快截图速度，避免延迟
        
        logger.info(f"截图完成，共 {total_frames} 帧")
        return total_frames
    
    def frames_to_video(self, frames_dir, output_path, fps=VIDEO_FPS):
        """将帧图像合成为视频"""
        try:
            frame_pattern = os.path.join(frames_dir, "frame_%06d.png")
            
            # 使用ffmpeg将帧序列转换为视频
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-framerate", str(fps),
                "-i", frame_pattern,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-r", str(fps),
                "-preset", "medium",
                "-crf", "23",
                output_path
            ]
            
            logger.info(f"开始合成视频: {' '.join(ffmpeg_cmd)}")
            
            process = subprocess.run(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            if process.returncode != 0:
                logger.error(f"视频合成失败: {process.stderr.decode()}")
                return False
            
            logger.info(f"视频合成成功: {output_path}")
            return True
        except Exception as e:
            logger.error(f"视频合成异常: {e}")
            return False
    
    async def record_paragraph(self, paragraph: Dict[str, Any]) -> str:
        """录制单个段落的视频"""
        paragraph_id = paragraph["id"]
        html_path = paragraph.get("html_path")
        audio_path = paragraph.get("audio_path")
        duration = paragraph.get("duration", 5.0)
        
        if not html_path or not os.path.exists(html_path):
            logger.error(f"HTML文件不存在: {html_path}")
            return ""
        
        # 视频输出路径
        video_path = self._get_video_path(paragraph_id)
        
        # 如果视频已存在，直接返回
        if video_path.exists():
            logger.info(f"视频已存在，跳过录制: {video_path}")
            return str(video_path)
        
        # 帧图像目录
        frames_dir = self._get_frames_dir(paragraph_id)
        
        try:
            # 启动Playwright
            async with async_playwright() as p:
                # 启动浏览器
                browser = await p.chromium.launch(headless=True)
                
                # 创建上下文
                context = await browser.new_context(
                    viewport={"width": VIDEO_WIDTH, "height": VIDEO_HEIGHT}
                )
                
                # 创建页面
                page = await context.new_page()
                
                # 打开HTML文件
                file_url = f"file://{html_path}"
                await page.goto(file_url)
                
                # 准备word_timings数据
                word_timings = paragraph.get("word_timings", [])
                
                # 优化word_timings，合并短小分段为句子级别
                optimized_timings = self._optimize_word_timings(word_timings, paragraph.get("content", ""))
                
                # 注入控制脚本 - 使用优化后的timings
                await page.evaluate(f"""
                    // 设置全局变量
                    window.duration = {duration};
                    window.currentTime = 0;
                    
                    // 更新播放时间的函数
                    window.updatePlaybackTime = function(time) {{
                        window.currentTime = time;
                        highlightTextAtTime(time);
                    }};
                    
                    // 高亮函数 - 优化版本
                    function highlightTextAtTime(time) {{
                        // 获取优化后的timings和内容元素
                        const wordTimings = {json.dumps(optimized_timings)};
                        const contentElement = document.getElementById("content");
                        
                        if (!contentElement || !wordTimings || wordTimings.length === 0) {{
                            return;
                        }}
                        
                        // 找到当前时间点对应的文本片段
                        let currentSegment = null;
                        for (let i = 0; i < wordTimings.length; i++) {{
                            const timing = wordTimings[i];
                            const segmentStart = timing.audio_offset;
                            const segmentEnd = segmentStart + timing.duration;
                            
                            if (time >= segmentStart && time < segmentEnd) {{
                                currentSegment = timing;
                                break;
                            }}
                        }}
                        
                        if (currentSegment) {{
                            const phrase = currentSegment.text;
                            const contentText = contentElement.textContent;
                            
                            // 创建带高亮的HTML
                            let html = "";
                            let lastIndex = 0;
                            
                            // 使用更精确的方法定位文本
                            const segmentIndex = contentText.indexOf(phrase);
                            if (segmentIndex >= 0) {{
                                html = contentText.substring(0, segmentIndex);
                                html += `<span class="highlight">${{phrase}}</span>`;
                                html += contentText.substring(segmentIndex + phrase.length);
                                contentElement.innerHTML = html;
                            }}
                        }}
                    }}
                """)
                
                # 添加启动延迟，确保页面完全加载
                await asyncio.sleep(0.5)
                
                # 按帧率捕获页面截图
                await self.capture_frames(page, duration, frames_dir)
                
                # 关闭浏览器
                await browser.close()
            
            # 将帧图像合成为视频
            if self.frames_to_video(frames_dir, str(video_path)):
                logger.info(f"视频录制成功: {video_path}")
                
                # 保留帧目录用于调试
                # shutil.rmtree(frames_dir)
                
                return str(video_path)
            else:
                logger.error(f"视频合成失败: {paragraph_id}")
                return ""
            
        except Exception as e:
            logger.error(f"视频录制失败: {e}")
            return ""
    
    def _optimize_word_timings(self, word_timings, content):
        """优化word_timings，合并为更有意义的文本段落"""
        if not word_timings:
            return []
            
        # 如果内容很短，直接返回完整内容的timing
        if len(content) < 50 and len(word_timings) > 0:
            first_timing = word_timings[0]
            last_timing = word_timings[-1]
            total_duration = (last_timing['audio_offset'] + last_timing['duration']) - first_timing['audio_offset']
            
            return [{
                'text': content,
                'audio_offset': first_timing['audio_offset'],
                'duration': total_duration
            }]
        
        # 按中文句子分隔符合并
        sentence_markers = ['。', '！', '？', '；', '，', '.', '!', '?', ';', ',']
        result = []
        
        current_sentence = ''
        sentence_start_time = 0
        sentence_duration = 0
        
        for i, timing in enumerate(word_timings):
            text = timing['text']
            current_sentence += text
            
            # 如果是第一个词，记录开始时间
            if i == 0 or not current_sentence:
                sentence_start_time = timing['audio_offset']
            
            # 检查是否应该结束当前句子
            is_end_of_sentence = False
            
            # 检查是否包含句末标点
            if any(marker in text for marker in sentence_markers):
                is_end_of_sentence = True
            
            # 最后一个词
            if i == len(word_timings) - 1:
                is_end_of_sentence = True
            
            # 如果已经积累了足够长的片段
            if len(current_sentence) > 15:
                is_end_of_sentence = True
            
            # 如果应该结束当前句子
            if is_end_of_sentence and current_sentence:
                end_time = timing['audio_offset'] + timing['duration']
                sentence_duration = end_time - sentence_start_time
                
                result.append({
                    'text': current_sentence,
                    'audio_offset': sentence_start_time,
                    'duration': sentence_duration
                })
                
                current_sentence = ''
        
        # 处理可能剩余的片段
        if current_sentence and word_timings:
            last_timing = word_timings[-1]
            end_time = last_timing['audio_offset'] + last_timing['duration']
            sentence_duration = end_time - sentence_start_time
            
            result.append({
                'text': current_sentence,
                'audio_offset': sentence_start_time,
                'duration': sentence_duration
            })
        
        return result
    
    async def record_paragraphs(self, paragraphs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """录制多个段落"""
        # 使用信号量限制并发
        semaphore = asyncio.Semaphore(MAX_WORKERS)
        
        async def record_with_semaphore(paragraph):
            async with semaphore:
                return await self.record_paragraph(paragraph)
        
        # 创建任务
        tasks = [record_with_semaphore(paragraph) for paragraph in paragraphs]
        video_paths = await asyncio.gather(*tasks)
        
        # 更新段落信息
        updated_paragraphs = []
        for paragraph, video_path in zip(paragraphs, video_paths):
            updated_paragraph = paragraph.copy()
            updated_paragraph["video_path"] = video_path
            updated_paragraphs.append(updated_paragraph)
        
        return updated_paragraphs
    
    def record_chapter(self, chapter: Dict[str, Any]) -> Dict[str, Any]:
        """录制整个章节"""
        paragraphs = chapter["paragraphs"]
        
        # 使用asyncio运行异步函数
        updated_paragraphs = asyncio.run(self.record_paragraphs(paragraphs))
        
        # 更新章节信息
        updated_chapter = chapter.copy()
        updated_chapter["paragraphs"] = updated_paragraphs
        
        return updated_chapter
    
    def record_book(self, chapters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """录制整本书"""
        updated_chapters = []
        
        for chapter in chapters:
            # 录制章节
            updated_chapter = self.record_chapter(chapter)
            updated_chapters.append(updated_chapter)
        
        return updated_chapters