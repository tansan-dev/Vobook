# app/main.py
import os
import argparse
import logging
import time
import json
import shutil
import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from app.book_parser.epub_parser import EpubParser
from app.book_parser.content_splitter import ContentSplitter
from app.text_processor.deepseek_processor import DeepSeekProcessor
from app.voice_generator.azure_tts import AzureTTS
from app.renderer.html_renderer import HtmlRenderer
from app.video_recorder.playwright_recorder import PlaywrightRecorder
from app.video_processor.ffmpeg_processor import FFmpegProcessor
from app.config import INPUT_DIR, OUTPUT_DIR, TEMP_DIR, CACHE_DIR, CACHE_INDEX_FILE, CACHE_ENABLED

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CacheManager:
    """缓存管理器，负责缓存查找和管理"""
    
    @staticmethod
    def get_book_cache_info(epub_path: str) -> Optional[Dict[str, Any]]:
        """获取书籍的缓存信息"""
        if not CACHE_ENABLED:
            return None
            
        if not os.path.exists(CACHE_INDEX_FILE):
            return None
        
        try:
            with open(CACHE_INDEX_FILE, 'r', encoding='utf-8') as f:
                cache_index = json.load(f)
                
            # 尝试查找精确匹配
            if epub_path in cache_index:
                return cache_index[epub_path]
                
            # 尝试查找文件名匹配
            epub_basename = os.path.basename(epub_path)
            for path, info in cache_index.items():
                if os.path.basename(path) == epub_basename:
                    return info
        except Exception as e:
            logger.error(f"读取缓存索引失败: {e}")
        
        return None
    
    @staticmethod
    def clean_cache(max_age_days: int = 30) -> None:
        """清理过期缓存"""
        if not os.path.exists(CACHE_INDEX_FILE):
            return
            
        now = time.time()
        max_age_seconds = max_age_days * 24 * 60 * 60
        
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
                    if cache_dir and os.path.exists(cache_dir):
                        shutil.rmtree(cache_dir)
                    to_delete.append(path)
            
            # 从索引中删除
            for path in to_delete:
                del cache_index[path]
                
            # 保存更新后的索引
            with open(CACHE_INDEX_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_index, f, ensure_ascii=False, indent=2)
                
            logger.info(f"缓存清理完成，删除了 {len(to_delete)} 个过期缓存")
        except Exception as e:
            logger.error(f"缓存清理失败: {e}")

class AudiobookVideoGenerator:
    def __init__(self, epub_path: str, max_chars_per_segment: int = 500, bgm_path: Optional[str] = None, 
                 selected_chapters: Optional[List[str]] = None, use_cache: bool = True, clean_cache: bool = False):
        """
        初始化有声书视频生成器
        
        Args:
            epub_path: EPUB文件路径
            max_chars_per_segment: 每段最大字符数
            bgm_path: 背景音乐路径（可选）
            selected_chapters: 选择处理的章节ID列表（可选）
            use_cache: 是否使用缓存
            clean_cache: 是否清理现有缓存重新生成
        """
        self.epub_path = epub_path
        self.max_chars_per_segment = max_chars_per_segment
        self.bgm_path = bgm_path
        self.selected_chapters = selected_chapters
        self.use_cache = use_cache
        self.clean_cache = clean_cache
        self.book_info = None
        self.book_id = None
        self.book_title = None
        self.toc_items = None
        self.flat_toc = None
        
        # 记录运行时间
        self.start_time = time.time()
        
        # 初始化时就获取或生成book_id
        self._initialize_book_id()
    
    def _initialize_book_id(self):
        """初始化book_id，尝试从缓存恢复或创建新的"""
        if self.clean_cache:
            # 如果请求清理缓存，不尝试恢复
            self._parse_book_info()
            logger.info(f"已创建新的Book ID: {self.book_id}")
            return
            
        # 尝试从缓存获取
        if self.use_cache:
            cache_info = CacheManager.get_book_cache_info(self.epub_path)
            if cache_info:
                self.book_id = cache_info['book_id']
                self.book_title = cache_info['title']
                logger.info(f"从缓存恢复Book ID: {self.book_id}, 书名: {self.book_title}")
                
                # 更新最后访问时间
                self._update_cache_access_time()
                return
        
        # 如果没有从缓存恢复，解析新的
        self._parse_book_info()
        logger.info(f"已创建新的Book ID: {self.book_id}")
    
    def _parse_book_info(self):
        """解析书籍基本信息以获取book_id"""
        parser = EpubParser(self.epub_path)
        self.book_info = parser.get_book_info()
        self.book_id = self.book_info["id"]
        self.book_title = self.book_info["title"]
        self.toc_items = parser.get_toc()
        self.flat_toc = parser.get_flat_toc()
    
    def _update_cache_access_time(self):
        """更新缓存的最后访问时间"""
        if not os.path.exists(CACHE_INDEX_FILE):
            return
            
        try:
            with open(CACHE_INDEX_FILE, 'r', encoding='utf-8') as f:
                cache_index = json.load(f)
                
            if self.epub_path in cache_index:
                cache_index[self.epub_path]['last_accessed'] = time.time()
                
            with open(CACHE_INDEX_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"更新缓存访问时间失败: {e}")
    
    def parse_book(self):
        """解析电子书"""
        logger.info(f"开始解析电子书: {self.epub_path}")
        
        # 如果已经初始化过book_id，不再重复解析
        if not self.toc_items:
            parser = EpubParser(self.epub_path)
            self.toc_items = parser.get_toc()
            self.flat_toc = parser.get_flat_toc()
        
        # 打印目录结构供用户参考
        self._print_toc_structure()
        
        # 解析章节（支持选定章节）
        if not hasattr(self, 'parser'):
            self.parser = EpubParser(self.epub_path)
        
        chapters = self.parser.parse_chapters(self.selected_chapters)
        logger.info(f"解析完成，共 {len(chapters)} 个章节")
        
        # 保存进度
        self._save_progress("parse_book", chapters)
        
        return chapters
    
    def _print_toc_structure(self):
        """打印目录结构"""
        logger.info("目录结构:")
        
        def print_toc(items, indent=0):
            for item in items:
                logger.info(f"{' ' * indent}- [{item['id']}] {item['title']} -> {item['file_name']}{('#' + item['fragment'] if item['fragment'] else '')}")
                if item.get("children"):
                    print_toc(item["children"], indent + 2)
        
        print_toc(self.toc_items)
    
    def split_content(self, chapters):
        """分段内容"""
        logger.info("开始内容分段")
        
        # 分段处理
        splitter = ContentSplitter(max_chars_per_segment=self.max_chars_per_segment)
        split_chapters = splitter.split_book_content(chapters)
        
        # 统计段落数量
        total_paragraphs = sum(len(chapter["paragraphs"]) for chapter in split_chapters)
        logger.info(f"分段完成，共 {total_paragraphs} 个段落")
        
        # 保存进度
        self._save_progress("split_content", split_chapters)
        
        return split_chapters
    
    def process_text(self, chapters):
        """处理文本，转换为口语化表达"""
        logger.info("开始文本口语化处理")
        
        # 初始化文本处理器
        processor = DeepSeekProcessor(self.book_id)
        
        # 处理所有章节
        processed_chapters = processor.process_chapters(chapters)
        logger.info("文本口语化处理完成")
        
        # 保存进度
        self._save_progress("process_text", processed_chapters)
        
        return processed_chapters
    
    def generate_speech(self, chapters):
        """生成语音"""
        logger.info("开始语音合成")
        
        # 初始化语音生成器
        tts = AzureTTS(self.book_id)
        
        # 处理所有章节
        processed_chapters = []
        for chapter in chapters:
            # 处理章节中的段落
            processed_paragraphs = tts.process_paragraphs(chapter["paragraphs"])
            
            # 更新章节信息
            processed_chapter = chapter.copy()
            processed_chapter["paragraphs"] = processed_paragraphs
            processed_chapters.append(processed_chapter)
        
        logger.info("语音合成完成")
        
        # 保存进度
        self._save_progress("generate_speech", processed_chapters)
        
        return processed_chapters
    
    def render_html(self, chapters):
        """渲染HTML页面"""
        logger.info("开始渲染HTML页面")
        
        # 初始化HTML渲染器
        renderer = HtmlRenderer(self.book_id)
        
        # 渲染整本书
        rendered_chapters = renderer.render_book(chapters)
        logger.info("HTML渲染完成")
        
        # 保存进度
        self._save_progress("render_html", rendered_chapters)
        
        return rendered_chapters
    
    def record_videos(self, chapters):
        """录制视频"""
        logger.info("开始录制视频")
        
        # 初始化视频录制器
        recorder = PlaywrightRecorder(self.book_id)
        
        # 录制整本书
        recorded_chapters = recorder.record_book(chapters)
        logger.info("视频录制完成")
        
        # 保存进度
        self._save_progress("record_videos", recorded_chapters)
        
        return recorded_chapters
    
    def process_videos(self, chapters):
        """处理视频"""
        logger.info("开始处理视频")
        
        # 初始化视频处理器
        processor = FFmpegProcessor(self.book_id, self.book_title)
        
        # 处理整本书
        output_path = processor.process_book(chapters, self.bgm_path)
        
        if output_path:
            logger.info(f"视频处理完成，输出路径: {output_path}")
            return output_path
        else:
            logger.error("视频处理失败")
            return None
    
    def generate(self):
        """生成有声书视频"""
        logger.info(f"开始生成有声书视频: {self.epub_path}")
        
        # 检查是否清理缓存
        if self.clean_cache:
            self._clean_book_cache()
            last_stage = None
        else:
            # 检查是否有之前的进度
            last_stage, data = self._load_progress()
        
        # 执行各阶段
        if last_stage is None or last_stage == "":
            chapters = self.parse_book()
        else:
            chapters = data
            logger.info(f"从 {last_stage} 阶段继续执行")
        
        if last_stage is None or last_stage <= "parse_book":
            chapters = self.split_content(chapters)
        
        if last_stage is None or last_stage <= "split_content":
            chapters = self.process_text(chapters)
        
        if last_stage is None or last_stage <= "process_text":
            chapters = self.generate_speech(chapters)
        
        if last_stage is None or last_stage <= "generate_speech":
            chapters = self.render_html(chapters)
        
        if last_stage is None or last_stage <= "render_html":
            chapters = self.record_videos(chapters)
        
        # 最后处理视频
        output_path = self.process_videos(chapters)
        
        # 计算运行时间
        elapsed_time = time.time() - self.start_time
        hours, remainder = divmod(elapsed_time, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        logger.info(f"生成完成，耗时: {int(hours)}小时{int(minutes)}分钟{int(seconds)}秒")
        logger.info(f"输出路径: {output_path}")
        
        return output_path
    
    def _clean_book_cache(self):
        """清理当前书籍的缓存"""
        # 移除进度文件
        progress_path = self._get_progress_path()
        if os.path.exists(progress_path):
            os.remove(progress_path)
            
        # 移除各阶段数据文件
        stages = ["parse_book", "split_content", "process_text", "generate_speech", "render_html", "record_videos"]
        for stage in stages:
            data_path = TEMP_DIR / f"{self.book_id}_{stage}_data.json"
            if os.path.exists(data_path):
                os.remove(data_path)
                
        logger.info(f"已清理书籍缓存: {self.book_id}")
    
    def _get_progress_path(self):
        """获取进度文件路径"""
        return TEMP_DIR / f"{self.book_id}_progress.json"
    
    def _save_progress(self, stage: str, data):
        """保存进度"""
        if not self.use_cache:
            return
            
        progress_path = self._get_progress_path()
        
        progress = {
            "stage": stage,
            "timestamp": time.time(),
            "book_id": self.book_id,
            "book_title": self.book_title
        }
        
        with open(progress_path, 'w', encoding='utf-8') as f:
            json.dump(progress, f, ensure_ascii=False)
        
        # 保存数据
        data_path = TEMP_DIR / f"{self.book_id}_{stage}_data.json"
        with open(data_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, default=str)
    
    def _load_progress(self):
        """加载进度"""
        if not self.use_cache:
            return None, None
            
        progress_path = self._get_progress_path()
        
        if not os.path.exists(progress_path):
            return None, None
        
        try:
            with open(progress_path, 'r', encoding='utf-8') as f:
                progress = json.load(f)
            
            stage = progress["stage"]
            data_path = TEMP_DIR / f"{self.book_id}_{stage}_data.json"
            
            if os.path.exists(data_path):
                with open(data_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return stage, data
            else:
                return None, None
        except Exception as e:
            logger.error(f"加载进度失败: {e}")
            return None, None


def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="有声书视频生成工具")
    parser.add_argument("--epub", type=str, help="EPUB文件路径")
    parser.add_argument("--bgm", type=str, help="背景音乐路径", default=None)
    parser.add_argument("--max-chars", type=int, help="每段最大字符数", default=500)
    parser.add_argument("--chapters", type=str, help="指定生成的章节ID，多个ID用逗号分隔", default=None)
    parser.add_argument("--list-chapters", action="store_true", help="仅列出章节结构不生成视频")
    parser.add_argument("--no-cache", action="store_true", help="不使用缓存，重新生成所有内容")
    parser.add_argument("--clean-cache", action="store_true", help="清除现有缓存后重新生成")
    parser.add_argument("--clean-all-cache", action="store_true", help="清理所有过期缓存")
    args = parser.parse_args()
    
    # 如果请求清理所有缓存
    if args.clean_all_cache:
        CacheManager.clean_cache()
        return
    
    # 获取EPUB路径
    epub_path = args.epub
    if not epub_path:
        print("请选择EPUB文件:")
        files = os.listdir(INPUT_DIR)
        epub_files = [f for f in files if f.endswith(".epub")]
        
        if not epub_files:
            print("未找到EPUB文件，请将文件放入inputs目录")
            return
        
        for i, epub_file in enumerate(epub_files):
            print(f"{i+1}. {epub_file}")
        
        choice = int(input("请输入序号: ")) - 1
        if 0 <= choice < len(epub_files):
            epub_path = os.path.join(INPUT_DIR, epub_files[choice])
        else:
            print("无效的选择")
            return

    # 解析选定的章节
    selected_chapters = None
    
    # 如果指定了章节参数
    if args.chapters:
        selected_chapters = [chapter_id.strip() for chapter_id in args.chapters.split(",")]
    # 如果没有指定章节，提供交互式选择
    else:
        # 检查是否有缓存信息可以使用
        cache_info = None
        if not args.no_cache:
            cache_info = CacheManager.get_book_cache_info(epub_path)
        
        # 创建一个临时解析器用于获取目录
        parser = EpubParser(epub_path)
        toc_items = parser.get_toc()
        flat_toc = parser.get_flat_toc()
        
        print("\n📚 EPUB目录结构：")
        print(f"文件: {os.path.basename(epub_path)}")
        print(f"标题: {parser.title}")
        print(f"作者: {parser.author}\n")
        
        # 如果有缓存，显示缓存信息
        if cache_info:
            cache_time = datetime.datetime.fromtimestamp(cache_info.get('last_accessed', 0))
            print(f"[发现缓存] ID: {cache_info['book_id']}, 上次使用: {cache_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"使用 --clean-cache 选项可清除此书的缓存\n")
        
        # 打印扁平化的目录供用户选择
        for i, item in enumerate(flat_toc):
            level_indent = "  " * item['level']
            fragment_info = f"#{item['fragment']}" if item['fragment'] else ""
            print(f"{i+1}. {level_indent}{item['title']} -> {item['file_name']}{fragment_info} [{item['id']}]")
        
        # 询问用户选择章节
        print("\n请选择要生成的章节（输入序号，多个序号用逗号分隔，输入'all'选择所有章节，输入'q'退出）：")
        choice = input("> ").strip()
        
        if choice.lower() == 'q':
            print("已取消操作")
            return
        
        if choice.lower() == 'all':
            # 不指定章节，将处理所有内容
            selected_chapters = None
        else:
            try:
                # 解析用户选择的序号
                selected_indices = [int(idx.strip()) - 1 for idx in choice.split(",")]
                selected_chapters = []
                
                for idx in selected_indices:
                    if 0 <= idx < len(flat_toc):
                        selected_chapters.append(flat_toc[idx]['id'])
                    else:
                        print(f"警告：无效的序号 {idx+1}，已忽略")
                
                if not selected_chapters:
                    print("未选择有效章节，将处理所有内容")
                    selected_chapters = None
                else:
                    print(f"已选择 {len(selected_chapters)} 个章节")
            except ValueError:
                print("输入格式错误，将处理所有内容")
                selected_chapters = None
    
    # 创建生成器
    generator = AudiobookVideoGenerator(
        epub_path=epub_path,
        max_chars_per_segment=args.max_chars,
        bgm_path=args.bgm,
        selected_chapters=selected_chapters,
        use_cache=not args.no_cache,
        clean_cache=args.clean_cache
    )
    
    # 如果仅列出章节，则只解析书籍并打印目录
    if args.list_chapters:
        parser = EpubParser(epub_path)
        toc_items = parser.get_toc()
        
        def print_toc(items, indent=0):
            for item in items:
                indent_str = "  " * indent
                print(f"{indent_str}- [{item['id']}] {item['title']} -> {item['file_name']}{('#' + item['fragment'] if item['fragment'] else '')}")
                if item.get("children"):
                    print_toc(item["children"], indent + 1)
        
        print("\n📚 EPUB目录结构：")
        print(f"文件: {os.path.basename(epub_path)}")
        print(f"标题: {parser.title}")
        print(f"作者: {parser.author}\n")
        print_toc(toc_items)
        print("\n使用示例：")
        print(f"python -m app.main --epub {epub_path} --chapters ID1,ID2,ID3")
        return
    
    # 生成视频
    generator.generate()


if __name__ == "__main__":
    main()