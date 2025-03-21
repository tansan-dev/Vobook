# app/video_recorder/playwright_recorder.py
import os
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import json
import subprocess
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
    
    def _get_temp_video_path(self, paragraph_id: str) -> Path:
        """获取临时视频文件路径（加速版）"""
        return self.video_dir / f"{paragraph_id}_temp.mp4"
    
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
        temp_video_path = self._get_temp_video_path(paragraph_id)
        
        # 如果视频已存在，直接返回
        if video_path.exists():
            logger.info(f"视频已存在，跳过录制: {video_path}")
            return str(video_path)
        
        try:
            # 创建临时视频路径
            video_path_tmp = tempfile.mktemp(suffix=".webm")
            video_dir_tmp = os.path.dirname(video_path_tmp)
            
            # 启动Playwright
            async with async_playwright() as p:
                # 启动浏览器
                browser = await p.chromium.launch(headless=True)
                
                # 创建上下文，在这里配置视频录制
                context = await browser.new_context(
                    viewport={"width": VIDEO_WIDTH, "height": VIDEO_HEIGHT},
                    record_video_dir=video_dir_tmp,
                    record_video_size={"width": VIDEO_WIDTH, "height": VIDEO_HEIGHT}
                )
                
                # 开始跟踪（可选）
                await context.tracing.start(
                    screenshots=True,
                    snapshots=True,
                    sources=False,
                    title="Audiobook Recording"
                )
                
                # 创建页面
                page = await context.new_page()
                
                # 打开HTML文件
                file_url = f"file://{html_path}"
                await page.goto(file_url)
                
                # 注入控制脚本
                await page.evaluate(f"""
                    window.autoPlay = true;
                    window.speedFactor = {SPEED_FACTOR};
                
                    // 创建完成Promise
                    let playbackCompleteResolve;
                    window.playbackCompletePromise = new Promise(resolve => {{
                        playbackCompleteResolve = resolve;
                    }});
                    
                    window.playbackComplete = function() {{
                        if (playbackCompleteResolve) {{
                            playbackCompleteResolve();
                        }}
                    }};
                """)
                
                # 开始播放
                await page.evaluate("window.startPlayback();")
                
                # 等待播放完成
                try:
                    # 计算加速后的等待时间（加上安全边际）
                    accelerated_duration = duration / SPEED_FACTOR + 1.0
                    
                    # 设置超时
                    wait_task = asyncio.create_task(
                        page.evaluate("window.playbackCompletePromise")
                    )
                    
                    # 等待播放完成或超时
                    await asyncio.wait_for(wait_task, timeout=accelerated_duration)
                except asyncio.TimeoutError:
                    logger.warning(f"播放超时，强制结束: {paragraph_id}")
                
                # 获取视频路径 - 正确的方式
                recorded_video_path = None
                try:
                    # 注意：在某些版本中，需要访问page.video，然后调用await video.path()
                    recorded_video_path = await page.video.path()
                except Exception as e:
                    logger.warning(f"获取视频路径失败: {e}")
                    
                # 停止跟踪
                await context.tracing.stop(path=f"{self.video_dir}/trace_{paragraph_id}.zip")
                
                # 关闭上下文和浏览器 
                await context.close()
                await browser.close()
                
                # 处理录制的视频
                if recorded_video_path and os.path.exists(recorded_video_path):
                    # 使用ffmpeg处理视频，减速至原始速度
                    speed_factor_inverse = 1.0 / SPEED_FACTOR
                    logger.info(f"正在处理视频，减速至原始速度: {speed_factor_inverse}")
                    
                    ffmpeg_cmd = [
                        "ffmpeg", "-y",
                        "-i", recorded_video_path,
                        "-filter:v", f"setpts={speed_factor_inverse}*PTS",
                        "-c:v", "libx264",
                        "-preset", "medium",
                        "-crf", "23",
                        str(video_path)
                    ]
                    
                    process = subprocess.run(
                        ffmpeg_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    
                    if process.returncode != 0:
                        logger.error(f"视频处理失败: {process.stderr.decode()}")
                        return ""
                    
                    # 清理临时文件
                    try:
                        os.remove(recorded_video_path)
                    except:
                        pass
                    
                    logger.info(f"视频录制成功: {video_path}")
                    return str(video_path)
                else:
                    # 如果没有获取到视频路径，尝试从目录中查找
                    video_files = [f for f in os.listdir(video_dir_tmp) 
                                if f.endswith('.webm') and os.path.isfile(os.path.join(video_dir_tmp, f))]
                    
                    if video_files:
                        recorded_video = os.path.join(video_dir_tmp, video_files[0])
                        
                        # 使用ffmpeg处理视频
                        speed_factor_inverse = 1.0 / SPEED_FACTOR
                        logger.info(f"正在处理查找到的视频，减速至原始速度: {speed_factor_inverse}")
                        
                        ffmpeg_cmd = [
                            "ffmpeg", "-y",
                            "-i", recorded_video,
                            "-filter:v", f"setpts={speed_factor_inverse}*PTS",
                            "-c:v", "libx264",
                            "-preset", "medium",
                            "-crf", "23",
                            str(video_path)
                        ]
                        
                        process = subprocess.run(
                            ffmpeg_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE
                        )
                        
                        if process.returncode != 0:
                            logger.error(f"视频处理失败: {process.stderr.decode()}")
                            return ""
                        
                        # 清理临时文件
                        try:
                            os.remove(recorded_video)
                        except:
                            pass
                        
                        logger.info(f"视频录制成功: {video_path}")
                        return str(video_path)
                    else:
                        logger.error("未找到录制的视频文件")
                        return ""
        
        except Exception as e:
            logger.error(f"视频录制失败: {e}")
            return ""
    
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