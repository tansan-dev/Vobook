# app/book_parser/epub_parser.py
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import os
import re
import uuid
import json
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional, Set
from app.config import TEMP_DIR
from app.book_parser.toc_parser import TocParser

class EpubParser:
    def __init__(self, epub_path: str):
        """
        初始化EPUB解析器
        
        Args:
            epub_path: EPUB文件路径
        """
        self.epub_path = epub_path
        self.book = epub.read_epub(epub_path)
        self.title = self.book.get_metadata('DC', 'title')[0][0] if self.book.get_metadata('DC', 'title') else "未知标题"
        self.author = self.book.get_metadata('DC', 'creator')[0][0] if self.book.get_metadata('DC', 'creator') else "未知作者"
        self.book_id = str(uuid.uuid4())[:8]
        self.book_dir = TEMP_DIR / f"{self.book_id}_{self.title}"
        self.images_dir = self.book_dir / "images"
        os.makedirs(self.book_dir, exist_ok=True)
        os.makedirs(self.images_dir, exist_ok=True)
        
        # 解析目录结构
        self.toc_parser = TocParser(self.book)
        self.toc_items = self.toc_parser.parse_toc()
        self.flat_toc = self.toc_parser.flatten_toc(self.toc_items)
        
    def get_book_info(self) -> Dict[str, Any]:
        """获取电子书基本信息"""
        return {
            "id": self.book_id,
            "title": self.title,
            "author": self.author,
            "path": str(self.book_dir),
            "toc_count": len(self.flat_toc)
        }
    
    def get_toc(self) -> List[Dict[str, Any]]:
        """获取目录结构"""
        return self.toc_items
    
    def get_flat_toc(self) -> List[Dict[str, Any]]:
        """获取扁平化的目录结构"""
        return self.flat_toc
    
    def save_toc(self) -> str:
        """保存目录结构到文件"""
        toc_path = self.book_dir / "toc.json"
        
        with open(toc_path, 'w', encoding='utf-8') as f:
            json.dump(self.toc_items, f, ensure_ascii=False, indent=2)
        
        flat_toc_path = self.book_dir / "flat_toc.json"
        with open(flat_toc_path, 'w', encoding='utf-8') as f:
            json.dump(self.flat_toc, f, ensure_ascii=False, indent=2)
        
        return str(toc_path)
    
    def extract_images(self) -> Dict[str, str]:
        """提取电子书中的所有图片"""
        image_map = {}
        
        for item in self.book.get_items_of_type(ebooklib.ITEM_IMAGE):
            image_filename = os.path.basename(item.get_name())
            image_path = self.images_dir / image_filename
            
            with open(image_path, 'wb') as f:
                f.write(item.content)
            
            # 记录图片ID和路径的映射关系
            image_id = item.get_id()
            image_map[image_id] = str(image_path)
        
        return image_map
    
    def parse_chapters(self, selected_chapters: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        解析所有章节内容
        
        Args:
            selected_chapters: 可选，要解析的章节ID列表，如果为None则解析所有章节
        """
        chapters = []
        image_map = self.extract_images()
        
        if selected_chapters:
            # 解析选定的章节
            return self._parse_selected_chapters(selected_chapters, image_map)
        
        # 如果没有选定章节，使用传统方法解析所有内容
        for item in self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            # 跳过目录、封面等非内容页
            if 'cover' in item.get_name().lower() or 'toc' in item.get_name().lower():
                continue
                
            content = item.get_content().decode('utf-8')
            soup = BeautifulSoup(content, 'html.parser')
            
            chapter_title = self._extract_title(soup)
            chapter_id = item.get_id()
            
            # 处理章节中的图片路径
            for img in soup.find_all('img'):
                if img.get('src'):
                    img_src = img['src']
                    # 处理相对路径
                    img_id = img_src.split('/')[-1]
                    if img_id in image_map:
                        img['src'] = image_map[img_id]
            
            # 解析章节内容
            paragraphs = self._extract_paragraphs(soup, image_map)
            
            chapters.append({
                "id": chapter_id,
                "title": chapter_title,
                "file_name": item.get_name(),
                "paragraphs": paragraphs
            })
        
        return chapters
    
    def _parse_selected_chapters(self, chapter_ids: List[str], image_map: Dict[str, str]) -> List[Dict[str, Any]]:
        """解析选定的章节"""
        chapters = []
        processed_files = set()  # 跟踪已处理的文件
        
        for chapter_id in chapter_ids:
            # 在目录中查找章节信息
            chapter_info = None
            for toc_item in self.flat_toc:
                if toc_item['id'] == chapter_id:
                    chapter_info = toc_item
                    break
            
            if not chapter_info:
                continue
            
            file_name = chapter_info['file_name']
            fragment = chapter_info['fragment']
            chapter_title = chapter_info['title']
            
            # 确保文件只处理一次
            if file_name in processed_files and not fragment:
                continue
            
            processed_files.add(file_name)
            
            # 获取内容
            content = self._get_chapter_content(file_name, fragment, image_map)
            
            if not content:
                continue
            
            # 解析章节内容
            soup = BeautifulSoup(content, 'html.parser')
            
            # 处理章节中的图片路径
            for img in soup.find_all('img'):
                if img.get('src'):
                    img_src = img['src']
                    # 处理相对路径
                    img_id = img_src.split('/')[-1]
                    if img_id in image_map:
                        img['src'] = image_map[img_id]
            
            # 解析章节内容
            paragraphs = self._extract_paragraphs(soup, image_map)
            
            chapters.append({
                "id": chapter_id,
                "title": chapter_title,
                "file_name": file_name,
                "fragment": fragment,
                "paragraphs": paragraphs
            })
        
        return chapters
    
    def _get_chapter_content(self, file_name: str, fragment: Optional[str], image_map: Dict[str, str]) -> str:
        """获取章节内容"""
        # 查找文件
        for item in self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            if item.get_name() == file_name:
                content = item.get_content().decode('utf-8')
                
                # 如果有片段标识符，提取相应部分
                if fragment:
                    soup = BeautifulSoup(content, 'html.parser')
                    fragment_element = soup.find(id=fragment)
                    
                    if fragment_element:
                        # 尝试获取片段所在章节的内容
                        section = self._get_section_for_fragment(soup, fragment_element)
                        if section:
                            return str(section)
                        else:
                            return str(fragment_element)
                
                return content
        
        return ""
    
    def _get_section_for_fragment(self, soup: BeautifulSoup, fragment_element) -> Optional[Any]:
        """获取片段所在的章节内容"""
        # 尝试向上查找章节容器
        parent = fragment_element
        
        for _ in range(5):  # 最多向上查找5层
            if parent is None:
                break
                
            # 检查当前元素是否是章节容器
            if parent.name in ['section', 'div', 'article'] or (parent.get('class') and any(c in ['chapter', 'section'] for c in parent.get('class'))):
                return parent
            
            parent = parent.parent
        
        # 如果没有找到合适的容器，返回片段元素本身
        return fragment_element
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """从HTML中提取章节标题"""
        title_tags = ['h1', 'h2', 'h3', 'h4']
        for tag in title_tags:
            if soup.find(tag):
                return soup.find(tag).get_text().strip()
        return "未命名章节"
    
    def _extract_paragraphs(self, soup: BeautifulSoup, image_map: Dict[str, str]) -> List[Dict[str, Any]]:
        """从章节HTML中提取段落和图片"""
        paragraphs = []
        
        # 获取正文内容
        content_tags = ['p', 'div', 'img']
        content_elements = []
        
        for tag in soup.find_all(content_tags):
            # 跳过空段落
            if tag.name in ['p', 'div'] and not tag.get_text().strip():
                continue
            
            content_elements.append(tag)
        
        # 处理段落和图片
        for idx, element in enumerate(content_elements):
            if element.name == 'img':
                # 处理图片
                img_src = element.get('src', '')
                if img_src:
                    # 找到实际图片路径
                    img_path = img_src
                    for img_id, path in image_map.items():
                        if img_id in img_src:
                            img_path = path
                            break
                    
                    paragraphs.append({
                        "id": f"p_{idx}",
                        "type": "image",
                        "content": "",
                        "image_path": img_path
                    })
            else:
                # 处理文本段落
                text = element.get_text().strip()
                if text:
                    # 检查是否包含内嵌图片
                    embedded_images = element.find_all('img')
                    if embedded_images:
                        for img in embedded_images:
                            img_src = img.get('src', '')
                            if img_src:
                                # 找到实际图片路径
                                img_path = img_src
                                for img_id, path in image_map.items():
                                    if img_id in img_src:
                                        img_path = path
                                        break
                                
                                paragraphs.append({
                                    "id": f"p_{idx}_img",
                                    "type": "image",
                                    "content": "",
                                    "image_path": img_path
                                })
                    
                    paragraphs.append({
                        "id": f"p_{idx}",
                        "type": "text",
                        "content": text,
                        "image_path": None
                    })
        
        return paragraphs