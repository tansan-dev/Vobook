# app/book_parser/content_splitter.py
from typing import List, Dict, Any
import re
import hashlib

class ContentSplitter:
    def __init__(self, max_chars_per_segment: int = 500):
        """
        初始化内容分段器
        
        Args:
            max_chars_per_segment: 每段最大字符数
        """
        self.max_chars = max_chars_per_segment
    
    def split_paragraph(self, paragraph: Dict[str, Any]) -> List[Dict[str, Any]]:
        """将长段落拆分为多个小段落"""
        # 如果是图片，直接返回
        if paragraph["type"] == "image":
            return [paragraph]
        
        content = paragraph["content"]
        # 如果段落长度小于最大长度，直接返回
        if len(content) <= self.max_chars:
            return [paragraph]
        
        # 按句子分割内容
        sentences = self._split_into_sentences(content)
        segments = []
        current_segment = ""
        
        for sentence in sentences:
            # 如果当前段落加上新句子不超过最大长度，则添加
            if len(current_segment) + len(sentence) <= self.max_chars:
                current_segment += sentence
            else:
                # 否则创建新段落
                if current_segment:
                    # 使用内容哈希创建稳定ID
                    content_hash = hashlib.md5(current_segment.encode('utf-8')).hexdigest()[:8]
                    segments.append({
                        "id": f"{paragraph['id']}_{content_hash}",
                        "type": "text",
                        "content": current_segment.strip(),
                        "image_path": None
                    })
                current_segment = sentence
        
        # 添加最后一个段落
        if current_segment:
            # 使用内容哈希创建稳定ID
            content_hash = hashlib.md5(current_segment.encode('utf-8')).hexdigest()[:8]
            segments.append({
                "id": f"{paragraph['id']}_{content_hash}",
                "type": "text",
                "content": current_segment.strip(),
                "image_path": None
            })
        
        return segments
    
    def _split_into_sentences(self, text: str) -> List[str]:
        """将文本按句子分割"""
        # 中文分句规则：按句号、问号、感叹号等标点符号分割
        sentence_endings = r'([。！？\!\?]+)'
        parts = re.split(sentence_endings, text)
        
        sentences = []
        for i in range(0, len(parts), 2):
            if i + 1 < len(parts):
                # 将句子和标点符号合并
                sentences.append(parts[i] + parts[i+1])
            else:
                sentences.append(parts[i])
        
        return sentences
    
    def split_book_content(self, chapters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """将整本书的内容分段"""
        split_chapters = []
        
        for chapter in chapters:
            split_paragraphs = []
            
            for paragraph in chapter["paragraphs"]:
                split_paragraphs.extend(self.split_paragraph(paragraph))
            
            split_chapter = chapter.copy()
            split_chapter["paragraphs"] = split_paragraphs
            split_chapters.append(split_chapter)
        
        return split_chapters