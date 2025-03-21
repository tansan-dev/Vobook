# app/book_parser/toc_parser.py
import os
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import logging
from typing import List, Dict, Any, Optional, Tuple
import re

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TocParser:
    def __init__(self, book: epub.EpubBook):
        """
        初始化目录解析器
        
        Args:
            book: EPUB书籍对象
        """
        self.book = book
        self.toc_map = {}  # 存储目录ID与对应的内容映射
        self.chapters = []  # 存储章节信息
    
    def parse_toc(self) -> List[Dict[str, Any]]:
        """解析目录结构"""
        # 首先尝试使用NCX文件解析
        ncx_item = self._get_ncx_item()
        if ncx_item:
            return self._parse_ncx(ncx_item)
        
        # 如果没有NCX，尝试使用导航文档
        nav_item = self._get_nav_item()
        if nav_item:
            return self._parse_nav(nav_item)
        
        # 如果没有标准目录，使用spine创建基本目录
        return self._create_spine_toc()
    
    def _get_ncx_item(self) -> Optional[epub.EpubItem]:
        """获取NCX文件项"""
        for item in self.book.get_items():
            if item.get_type() == ebooklib.ITEM_NAVIGATION:
                return item
        return None
    
    def _get_nav_item(self) -> Optional[epub.EpubItem]:
        """获取EPUB3导航文档"""
        for item in self.book.get_items():
            if isinstance(item, epub.EpubHtml) and item.is_chapter():
                if hasattr(item, 'properties') and 'nav' in item.properties:
                    return item
        return None
    
    def _parse_ncx(self, ncx_item: epub.EpubItem) -> List[Dict[str, Any]]:
        """解析NCX文件获取目录结构"""
        ncx_content = ncx_item.get_content().decode('utf-8')
        
        # 使用ElementTree解析XML
        namespaces = {
            'ncx': 'http://www.daisy.org/z3986/2005/ncx/'
        }
        
        try:
            root = ET.fromstring(ncx_content)
            
            # 获取navMap元素
            nav_map = root.find('.//ncx:navMap', namespaces)
            if nav_map is None:
                logger.warning("NCX文件中未找到navMap元素")
                return self._create_spine_toc()
            
            # 解析导航点
            return self._parse_nav_points(nav_map, namespaces)
            
        except Exception as e:
            logger.error(f"解析NCX文件失败: {e}")
            return self._create_spine_toc()
    
    def _parse_nav_points(self, parent_element, namespaces, level=0) -> List[Dict[str, Any]]:
        """递归解析导航点"""
        nav_items = []
        
        for nav_point in parent_element.findall('./ncx:navPoint', namespaces):
            # 获取ID
            nav_id = nav_point.get('id', '')
            
            # 获取标题
            nav_label = nav_point.find('./ncx:navLabel/ncx:text', namespaces)
            title = nav_label.text if nav_label is not None and nav_label.text else "未命名章节"
            
            # 获取内容链接
            content_element = nav_point.find('./ncx:content', namespaces)
            content_src = content_element.get('src', '') if content_element is not None else ''
            
            # 处理链接（去除片段标识符）
            src_parts = content_src.split('#', 1)
            file_name = src_parts[0]
            fragment = src_parts[1] if len(src_parts) > 1 else None
            
            # 创建导航项
            nav_item = {
                'id': nav_id,
                'title': title,
                'level': level,
                'file_name': file_name,
                'fragment': fragment,
                'full_path': content_src,
                'children': []
            }
            
            # 递归解析子导航点
            children = self._parse_nav_points(nav_point, namespaces, level + 1)
            if children:
                nav_item['children'] = children
            
            nav_items.append(nav_item)
            
            # 存储ID与文件映射关系
            self.toc_map[nav_id] = {
                'file_name': file_name,
                'fragment': fragment,
                'title': title
            }
        
        return nav_items
    
    def _parse_nav(self, nav_item: epub.EpubItem) -> List[Dict[str, Any]]:
        """解析EPUB3导航文档"""
        nav_content = nav_item.get_content().decode('utf-8')
        soup = BeautifulSoup(nav_content, 'html.parser')
        
        # 查找导航列表
        nav_element = soup.find('nav', attrs={'epub:type': 'toc'})
        if not nav_element:
            nav_element = soup.find('nav')
        
        if not nav_element:
            logger.warning("导航文档中未找到nav元素")
            return self._create_spine_toc()
        
        # 查找导航列表
        ol_element = nav_element.find('ol')
        if not ol_element:
            logger.warning("导航文档中未找到ol元素")
            return self._create_spine_toc()
        
        # 解析导航项
        return self._parse_nav_items(ol_element)
    
    def _parse_nav_items(self, ol_element, level=0) -> List[Dict[str, Any]]:
        """递归解析导航项"""
        nav_items = []
        
        for li_element in ol_element.find_all('li', recursive=False):
            # 获取链接
            a_element = li_element.find('a')
            if not a_element:
                continue
            
            # 获取标题
            title = a_element.get_text().strip()
            href = a_element.get('href', '')
            
            # 处理链接（去除片段标识符）
            src_parts = href.split('#', 1)
            file_name = src_parts[0]
            fragment = src_parts[1] if len(src_parts) > 1 else None
            
            # 生成ID
            nav_id = f"nav_{len(self.toc_map)}"
            
            # 创建导航项
            nav_item = {
                'id': nav_id,
                'title': title,
                'level': level,
                'file_name': file_name,
                'fragment': fragment,
                'full_path': href,
                'children': []
            }
            
            # 递归解析子导航项
            child_ol = li_element.find('ol')
            if child_ol:
                children = self._parse_nav_items(child_ol, level + 1)
                if children:
                    nav_item['children'] = children
            
            nav_items.append(nav_item)
            
            # 存储ID与文件映射关系
            self.toc_map[nav_id] = {
                'file_name': file_name,
                'fragment': fragment,
                'title': title
            }
        
        return nav_items
    
    def _create_spine_toc(self) -> List[Dict[str, Any]]:
        """从spine创建基本目录"""
        toc_items = []
        
        for i, item in enumerate(self.book.spine):
            item_id = item[0]
            item_obj = self.book.get_item_with_id(item_id)
            
            if not item_obj:
                continue
            
            # 获取文件名
            file_name = item_obj.get_name()
            
            # 尝试从内容提取标题
            title = self._extract_title_from_item(item_obj) or f"章节 {i+1}"
            
            # 创建导航项
            nav_id = f"spine_{i}"
            nav_item = {
                'id': nav_id,
                'title': title,
                'level': 0,
                'file_name': file_name,
                'fragment': None,
                'full_path': file_name,
                'children': []
            }
            
            toc_items.append(nav_item)
            
            # 存储ID与文件映射关系
            self.toc_map[nav_id] = {
                'file_name': file_name,
                'fragment': None,
                'title': title
            }
        
        return toc_items
    
    def _extract_title_from_item(self, item: epub.EpubItem) -> Optional[str]:
        """从内容提取标题"""
        if not isinstance(item, epub.EpubHtml):
            return None
        
        try:
            content = item.get_content().decode('utf-8')
            soup = BeautifulSoup(content, 'html.parser')
            
            # 尝试从标题标签获取
            for tag in ['h1', 'h2', 'h3', 'title']:
                element = soup.find(tag)
                if element and element.get_text().strip():
                    return element.get_text().strip()
            
            return None
        except Exception:
            return None
    
    def get_chapter_content(self, file_name: str, fragment: Optional[str] = None) -> str:
        """获取指定文件的HTML内容"""
        # 查找对应的文件项
        for item in self.book.get_items():
            if isinstance(item, epub.EpubHtml) and item.get_name() == file_name:
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
            if parent.name in ['section', 'div', 'article'] or parent.get('class') and any(c in ['chapter', 'section'] for c in parent.get('class')):
                return parent
            
            parent = parent.parent
        
        # 如果没有找到合适的容器，返回片段元素本身
        return fragment_element
    
    def flatten_toc(self, toc_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """将多级目录扁平化为一级列表"""
        flat_items = []
        
        def process_items(items, parent_title=None):
            for item in items:
                flat_item = item.copy()
                
                # 添加父级标题
                if parent_title:
                    flat_item['parent_title'] = parent_title
                
                # 移除子项
                children = flat_item.pop('children', [])
                
                flat_items.append(flat_item)
                
                # 处理子项
                if children:
                    process_items(children, flat_item['title'])
        
        process_items(toc_items)
        return flat_items
    
    def print_toc_structure(self, toc_items: List[Dict[str, Any]], indent=0):
        """打印目录结构（用于调试）"""
        for item in toc_items:
            indent_str = "  " * indent
            print(f"{indent_str}- {item['title']} -> {item['full_path']}")
            
            if item['children']:
                self.print_toc_structure(item['children'], indent + 1)