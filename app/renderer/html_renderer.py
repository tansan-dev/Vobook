# app/renderer/html_renderer.py
import os
import json
from pathlib import Path
from typing import Dict, Any, List
import logging
from jinja2 import Environment, FileSystemLoader
from concurrent.futures import ThreadPoolExecutor
import base64

from app.config import (
    FONT_FAMILY, 
    FONT_SIZE, 
    LINE_HEIGHT, 
    BACKGROUND_COLOR, 
    TEXT_COLOR,
    HIGHLIGHT_COLOR,
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    MAX_WORKERS,
    TEMP_DIR
)

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class HtmlRenderer:
    def __init__(self, book_id: str):
        """
        初始化HTML渲染器
        
        Args:
            book_id: 书籍ID，用于管理HTML文件
        """
        self.book_id = book_id
        self.html_dir = TEMP_DIR / f"{book_id}_html"
        os.makedirs(self.html_dir, exist_ok=True)
        
        # 创建模板目录
        self.template_dir = Path(__file__).parent / "templates"
        os.makedirs(self.template_dir, exist_ok=True)
        
        # 创建模板文件（如果不存在）
        self._create_templates()
        
        # 初始化Jinja2环境
        self.env = Environment(loader=FileSystemLoader(self.template_dir))
    
    def _create_templates(self) -> None:
        """创建HTML模板文件"""
        # 文本段落模板
        text_template_path = self.template_dir / "text_template.html"
        if not text_template_path.exists():
            text_template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }}</title>
    <style>
        body {
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-color: {{ background_color }};
            font-family: {{ font_family }};
            color: {{ text_color }};
            overflow: hidden;
        }
        .container {
            width: {{ width }}px;
            height: {{ height }}px;
            padding: 50px;
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }
        .content {
            font-size: {{ font_size }};
            line-height: {{ line_height }};
            text-align: justify;
            white-space: pre-line;
        }
        .highlight {
            background-color: {{ highlight_color }};
            padding: 0 2px;
            border-radius: 2px;
        }
        .chapter-title {
            font-size: 24px;
            font-weight: bold;
            margin-bottom: 30px;
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="container">
        {% if show_chapter_title %}
        <h1 class="chapter-title">{{ chapter_title }}</h1>
        {% endif %}
        <div class="content" id="content">{{ content|safe }}</div>
    </div>

    <script>
        // 音频时长和单词时间信息
        const audioPath = "{{ audio_path }}";
        const duration = {{ duration }};
        const wordTimings = {{ word_timings|tojson }};
        
        // 文本内容
        const text = "{{ content_for_js }}";
        
        // 标记当前朗读的位置
        function highlightText(time) {
            // 找到当前时间点对应的单词
            let currentWord = null;
            for (let i = 0; i < wordTimings.length; i++) {
                const wordTiming = wordTimings[i];
                const wordStart = wordTiming.audio_offset;
                const wordEnd = wordStart + wordTiming.duration;
                
                if (time >= wordStart && time < wordEnd) {
                    currentWord = wordTiming;
                    break;
                }
            }
            
            if (currentWord) {
                // 获取当前单词在文本中的位置
                const phrase = currentWord.text;
                const contentElement = document.getElementById("content");
                const contentText = contentElement.textContent;
                
                // 创建带高亮的HTML
                let html = "";
                let lastIndex = 0;
                
                // 查找当前单词的所有匹配位置
                const regex = new RegExp(phrase, "g");
                let match;
                let firstMatch = true;
                
                while ((match = regex.exec(contentText)) !== null) {
                    // 只高亮第一个匹配项
                    if (firstMatch) {
                        html += contentText.substring(lastIndex, match.index);
                        html += `<span class="highlight">${phrase}</span>`;
                        lastIndex = match.index + phrase.length;
                        firstMatch = false;
                    }
                }
                
                html += contentText.substring(lastIndex);
                contentElement.innerHTML = html;
            }
        }
        
        // 计时器模拟音频播放
        let startTime = Date.now();
        let timer = null;
        
        function simulateAudioPlayback() {
            const elapsedTime = (Date.now() - startTime) / 1000;
            
            if (elapsedTime <= duration) {
                highlightText(elapsedTime);
                timer = requestAnimationFrame(simulateAudioPlayback);
            } else {
                // 播放结束后，通知录制器
                if (window.playbackComplete) {
                    window.playbackComplete();
                }
            }
        }
        
        // 开始模拟播放
        window.startPlayback = function() {
            startTime = Date.now();
            simulateAudioPlayback();
        };
        
        // 停止模拟播放
        window.stopPlayback = function() {
            if (timer) {
                cancelAnimationFrame(timer);
                timer = null;
            }
        };
        
        // 自动开始播放（可被Playwright控制）
        setTimeout(() => {
            if (window.autoPlay !== false) {
                window.startPlayback();
            }
        }, 500);
    </script>
</body>
</html>"""
            with open(text_template_path, 'w', encoding='utf-8') as f:
                f.write(text_template)
        
        # 图片模板
        image_template_path = self.template_dir / "image_template.html"
        if not image_template_path.exists():
            image_template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }}</title>
    <style>
        body {
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background-color: {{ background_color }};
            overflow: hidden;
        }
        .container {
            width: {{ width }}px;
            height: {{ height }}px;
            padding: 20px;
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
        }
        .image-container {
            max-width: 90%;
            max-height: 80vh;
            text-align: center;
        }
        img {
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="image-container">
            <img src="{{ image_data }}" alt="Book Illustration">
        </div>
    </div>

    <script>
        // 音频时长
        const audioPath = "{{ audio_path }}";
        const duration = {{ duration }};
        
        // 计时器模拟音频播放
        let startTime = Date.now();
        let timer = null;
        
        function simulateAudioPlayback() {
            const elapsedTime = (Date.now() - startTime) / 1000;
            
            if (elapsedTime <= duration) {
                timer = requestAnimationFrame(simulateAudioPlayback);
            } else {
                // 播放结束后，通知录制器
                if (window.playbackComplete) {
                    window.playbackComplete();
                }
            }
        }
        
        // 开始模拟播放
        window.startPlayback = function() {
            startTime = Date.now();
            simulateAudioPlayback();
        };
        
        // 停止模拟播放
        window.stopPlayback = function() {
            if (timer) {
                cancelAnimationFrame(timer);
                timer = null;
            }
        };
        
        // 自动开始播放（可被Playwright控制）
        setTimeout(() => {
            if (window.autoPlay !== false) {
                window.startPlayback();
            }
        }, 500);
    </script>
</body>
</html>"""
            with open(image_template_path, 'w', encoding='utf-8') as f:
                f.write(image_template)
    
    def _get_html_path(self, paragraph_id: str) -> Path:
        """获取HTML文件路径"""
        return self.html_dir / f"{paragraph_id}.html"
    
    def _encode_image(self, image_path: str) -> str:
        """将图片编码为base64"""
        try:
            with open(image_path, 'rb') as f:
                image_data = f.read()
            
            # 获取MIME类型
            ext = os.path.splitext(image_path)[1].lower()
            mime_type = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.webp': 'image/webp',
                '.svg': 'image/svg+xml'
            }.get(ext, 'image/jpeg')
            
            # 编码为base64
            encoded = base64.b64encode(image_data).decode('utf-8')
            return f"data:{mime_type};base64,{encoded}"
        except Exception as e:
            logger.error(f"图片编码失败: {e}")
            return ""
    
    def render_paragraph(self, paragraph: Dict[str, Any], chapter_title: str = "", show_chapter_title: bool = False) -> str:
        """渲染段落为HTML"""
        paragraph_id = paragraph["id"]
        paragraph_type = paragraph["type"]
        html_path = self._get_html_path(paragraph_id)
        
        # 加载适当的模板
        if paragraph_type == "image":
            template = self.env.get_template("image_template.html")
            # 编码图片为base64
            image_data = self._encode_image(paragraph["image_path"]) if paragraph.get("image_path") else ""
            
            # 渲染模板
            html_content = template.render(
                title=f"图片 {paragraph_id}",
                image_data=image_data,
                audio_path=paragraph.get("audio_path", ""),
                duration=paragraph.get("duration", 5.0),
                background_color=BACKGROUND_COLOR,
                width=VIDEO_WIDTH,
                height=VIDEO_HEIGHT
            )
        else:
            template = self.env.get_template("text_template.html")
            content = paragraph["content"]
            
            # 处理特殊字符，避免JavaScript错误
            content_for_js = content.replace('"', '\\"').replace('\n', '\\n')
            
            # 渲染模板
            html_content = template.render(
                title=f"段落 {paragraph_id}",
                content=content,
                content_for_js=content_for_js,
                chapter_title=chapter_title,
                show_chapter_title=show_chapter_title,
                audio_path=paragraph.get("audio_path", ""),
                duration=paragraph.get("duration", 1.0),
                word_timings=paragraph.get("word_timings", []),
                font_family=FONT_FAMILY,
                font_size=FONT_SIZE,
                line_height=LINE_HEIGHT,
                background_color=BACKGROUND_COLOR,
                text_color=TEXT_COLOR,
                highlight_color=HIGHLIGHT_COLOR,
                width=VIDEO_WIDTH,
                height=VIDEO_HEIGHT
            )
        
        # 保存HTML文件
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return str(html_path)
    
    def render_chapter(self, chapter: Dict[str, Any]) -> List[Dict[str, Any]]:
        """渲染整个章节"""
        chapter_title = chapter["title"]
        paragraphs = chapter["paragraphs"]
        rendered_paragraphs = []
        
        for i, paragraph in enumerate(paragraphs):
            # 第一段显示章节标题
            show_chapter_title = (i == 0)
            
            # 渲染段落
            html_path = self.render_paragraph(
                paragraph=paragraph,
                chapter_title=chapter_title,
                show_chapter_title=show_chapter_title
            )
            
            # 更新段落信息
            updated_paragraph = paragraph.copy()
            updated_paragraph["html_path"] = html_path
            rendered_paragraphs.append(updated_paragraph)
        
        return rendered_paragraphs
    
    def render_book(self, chapters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """渲染整本书"""
        rendered_chapters = []
        
        for chapter in chapters:
            # 渲染章节
            rendered_paragraphs = self.render_chapter(chapter)
            
            # 更新章节信息
            rendered_chapter = chapter.copy()
            rendered_chapter["paragraphs"] = rendered_paragraphs
            rendered_chapters.append(rendered_chapter)
        
        return rendered_chapters