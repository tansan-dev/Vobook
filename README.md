# 有声书视频生成工具

从 EPUB 电子书自动生成有声书视频，包含文字朗读、荧光笔高亮、图文排版等效果。

## 功能特点

- 支持标准 EPUB 格式电子书解析
- DeepSeek API 将书面语转换为口语化表达
- Azure TTS 语音合成，自然真实的朗读效果
- 精美的图文排版，Apple Books 风格
- 文字荧光笔高亮标注，同步跟随朗读进度
- 完整的视频生成，支持背景音乐

## 安装

1. 克隆代码库：

```bash
git clone https://github.com/yourusername/epub-audiobook-video-generator.git
cd epub-audiobook-video-generator
```

2. 安装依赖：

```bash
pip install -r requirements.txt
```

3. 安装系统依赖：

- FFmpeg：用于视频处理
- Playwright：用于浏览器自动化

```bash
# 安装Playwright浏览器
playwright install
```

## 配置

在使用前，请配置以下环境变量：

```bash
# DeepSeek API配置
export DEEPSEEK_API_KEY="your_deepseek_api_key"

# Azure语音服务配置
export AZURE_SPEECH_KEY="your_azure_speech_key"
export AZURE_SPEECH_REGION="eastasia"
```

## 使用方法

1. 将 EPUB 文件放入`data/inputs`目录

2. 查看电子书章节结构：

```bash
python -m app.main --epub data/inputs/your_book.epub --list-chapters
```

这将显示书籍的完整目录结构和每个章节的 ID，便于选择特定章节生成视频。

3. 运行程序生成视频：

```bash
# 生成所有章节
python -m app.main --epub data/inputs/your_book.epub

# 生成指定章节（使用章节ID）
python -m app.main --epub data/inputs/your_book.epub --chapters navPoint-1,navPoint-5,navPoint-10
```

如果不指定章节，程序会提供交互式界面让您选择要生成的章节。

可选参数：

- `--bgm`：背景音乐路径
- `--max-chars`：每段最大字符数，默认 500
- `--chapters`：指定生成的章节 ID，多个 ID 用逗号分隔
- `--list-chapters`：仅列出章节结构不生成视频

4. 生成的视频将保存在`data/outputs`目录中

## 项目结构

```
epub-audiobook-video-generator/
├── app/
│   ├── __init__.py
│   ├── main.py                  # 主程序入口
│   ├── config.py                # 配置文件
│   ├── book_parser/             # EPUB解析模块
│   ├── text_processor/          # 文本处理模块
│   ├── voice_generator/         # 语音生成模块
│   ├── renderer/                # 渲染模块
│   ├── video_recorder/          # 视频录制模块
│   └── video_processor/         # 视频处理模块
├── data/                        # 数据目录
│   ├── inputs/                  # 输入文件
│   ├── temp/                    # 临时文件
│   └── outputs/                 # 输出文件
├── requirements.txt             # 依赖项
└── README.md                    # 项目说明
```

## 自定义配置

可在`app/config.py`中修改以下配置：

- 视频尺寸、帧率、格式
- 文字字体、大小、行高
- 背景色、文字颜色、高亮颜色
- 语音音色、语速、音调
- 并发处理线程数

## 许可

MIT License
