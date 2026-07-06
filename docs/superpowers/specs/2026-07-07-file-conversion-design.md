# StreamDock 文件转换功能设计

日期：2026-07-07

## 1. 背景与目标

StreamDock 当前核心能力是多平台媒体解析与本地导出。下一阶段扩展为“本地文件处理工具箱”，新增文件格式转换功能。

目标不是做一个万能转换器，而是做一个可信的本地转换中心：

- 对成熟、稳定、质量可控的路径，提供本地转换。
- 对可以本地做但可能损失复杂格式的路径，标注为“本地基础”。
- 对高保真难度过高的路径，不硬做，只提供专业厂商推荐。

第一版目标规模：

- 本地稳定：约 45 到 60 条转换路径。
- 本地基础：约 15 到 25 条转换路径。
- 推荐厂商：约 10 到 15 条专业路径。

## 2. 产品入口与页面结构

新增顶部导航入口：

```text
产品｜支持平台｜在线使用｜文件转换｜更新日志
```

新增页面路由：

```text
/convert
```

页面主结构：

1. 转换工作台
   - 选择本地文件
   - 自动识别输入格式
   - 展示可选输出格式
   - 选择输出目录
   - 开始转换
   - 展示转换结果和运行日志

2. 能力矩阵
   - 本地稳定
   - 本地基础
   - 推荐厂商

3. 厂商推荐区
   - 对高难度转换给出推荐工具和适用说明
   - 不伪装成本地可完成能力

## 3. 后端架构

新增独立模块，不放入 `fetchers/`。

```text
converters/
├── __init__.py
├── models.py
├── registry.py
├── pipeline.py
└── adapters/
    ├── data.py
    ├── image.py
    ├── audio_video.py
    ├── subtitle.py
    ├── archive.py
    ├── document_basic.py
    └── vendor_only.py
```

职责划分：

- `converters/models.py`：定义转换任务、输入文件、输出文件、能力等级、转换结果。
- `converters/registry.py`：注册所有转换路径和能力等级。
- `converters/pipeline.py`：统一执行转换流程，负责校验、调用 adapter、返回结果。
- `converters/adapters/*`：按文件类型实现具体转换逻辑。

现有 `fetchers/` 继续只负责平台解析下载，两者职责分离：

```text
fetchers/      平台媒体解析与下载
converters/   本地文件格式转换
```

## 4. 能力等级定义

### 4.1 本地稳定

含义：

- 本机直接完成。
- 转换路线成熟。
- 质量可控。
- 可以作为主功能提供给用户。

页面标签：

```text
稳定
```

### 4.2 本地基础

含义：

- 本机直接完成。
- 简单文件效果可用。
- 复杂排版、字体、公式、批注、动画等可能有损。

页面标签：

```text
基础
```

提示文案：

```text
适合普通文件，不保证复杂排版或特殊元素完全一致。
```

### 4.3 推荐厂商

含义：

- 本地不提供转换。
- 转换质量高度依赖专业算法或商业软件。
- 页面展示推荐工具和适用场景。

页面标签：

```text
推荐厂商
```

提示文案：

```text
该转换对高保真或 OCR 能力要求较高，建议使用专业工具完成。
```

## 5. 第一版转换范围

### 5.1 本地稳定：数据表格类

```text
CSV → XLSX
CSV → JSON
CSV → TSV
CSV → TXT

TSV → CSV
TSV → XLSX
TSV → JSON

XLSX → CSV
XLSX → JSON
XLSX → TSV

JSON → CSV
JSON → XLSX
JSON → TXT

NDJSON → JSON
NDJSON → CSV

YAML → JSON
JSON → YAML

XML → JSON
JSON → XML

TOML → JSON
JSON → TOML
```

质量说明：结构化数据转换可控。XLSX 多工作表导出时，第一版默认导出第一个工作表，后续可支持工作表选择。

### 5.2 本地稳定：图片类

```text
PNG → JPG
PNG → WEBP
PNG → BMP
PNG → TIFF

JPG → PNG
JPG → WEBP
JPG → BMP
JPG → TIFF

WEBP → PNG
WEBP → JPG

BMP → PNG
BMP → JPG

TIFF → PNG
TIFF → JPG

GIF → PNG 序列
PNG 序列 → GIF
```

质量说明：基于成熟图片库，常规图片可稳定转换。透明通道转 JPG 时需要默认白底或用户选择背景色。

### 5.3 本地稳定：音频类

```text
MP3 → WAV
MP3 → M4A
MP3 → AAC
MP3 → FLAC
MP3 → OGG
MP3 → OPUS

WAV → MP3
WAV → M4A
WAV → FLAC
WAV → OGG

M4A → MP3
M4A → WAV
M4A → AAC

AAC → MP3
AAC → WAV

FLAC → MP3
FLAC → WAV

OGG → MP3
OPUS → MP3
```

质量说明：基于 ffmpeg，成熟稳定。默认提供常用码率，后续可开放高级参数。

### 5.4 本地稳定：视频类

```text
MP4 → MP3
MP4 → WAV
MP4 → M4A

MOV → MP4
MKV → MP4
WEBM → MP4

MP4 → GIF
MOV → GIF
WEBM → GIF

MP4 → WEBM
WEBM → MP4
```

质量说明：常规编码可稳定处理。特殊编码或损坏文件返回明确错误，不做静默失败。

### 5.5 本地稳定：字幕类

```text
SRT → VTT
VTT → SRT
ASS → SRT
ASS → VTT
TXT → SRT，基础时间轴模板
```

质量说明：字幕格式结构清晰，适合本地转换。ASS 的复杂样式转换到 SRT/VTT 时只保留文本和时间轴。

### 5.6 本地稳定：压缩包类

```text
ZIP → TAR
TAR → ZIP
TAR.GZ → ZIP
ZIP → 解压文件夹
文件夹 → ZIP
文件夹 → TAR.GZ
```

质量说明：仅处理普通文件压缩与解压。加密压缩包第一版不支持，返回提示。

### 5.7 本地基础：轻文档类

```text
Markdown → HTML
Markdown → TXT
Markdown → PDF

HTML → TXT
HTML → PDF
HTML → Markdown，基础版

TXT → HTML
TXT → Markdown
TXT → PDF
```

质量说明：轻文档转换可用，但 HTML 到 Markdown 只做基础结构保留。

### 5.8 本地基础：Office 基础转换

```text
DOCX → TXT
DOCX → HTML
DOCX → PDF，基础版

PPTX → PDF，基础版
PPTX → 图片序列，基础版

XLSX → PDF，基础版
XLSX → HTML，基础版
```

质量说明：适合普通文档，不保证复杂排版、公式、批注、艺术字、复杂表格、动画完全一致。

### 5.9 本地基础：SVG 与电子书

```text
SVG → PNG
SVG → JPG
SVG → PDF

EPUB → TXT
EPUB → HTML
EPUB → PDF，基础版
```

质量说明：复杂 SVG 的字体、滤镜、外部资源可能有差异。EPUB 仅做基础章节内容转换。

### 5.10 推荐厂商

```text
PDF → Word
PDF → Excel
PDF → PPT
扫描 PDF → Word
扫描 PDF → Excel
图片 OCR → Word
图片 OCR → Excel
复杂 Word → PDF 高保真
复杂 PPT → PDF 高保真
CAD → PDF / 图片
PSD / AI / Sketch / Figma 文件转换
```

推荐厂商：

```text
Adobe Acrobat
Microsoft 365
WPS
ABBYY FineReader
Smallpdf
iLovePDF
Google Docs
CloudConvert
Convertio
```

## 6. 用户流程

```text
选择文件
  ↓
自动识别输入格式
  ↓
展示可用转换路径
  ↓
选择输出格式
  ↓
选择保存目录
  ↓
开始转换
  ↓
展示结果、日志、打开文件入口
```

如果用户选择“推荐厂商”路径：

```text
选择转换路径
  ↓
展示原因说明
  ↓
展示推荐厂商和适用场景
  ↓
不执行本地转换
```

## 7. API 设计

新增 API：

```text
GET  /convert
GET  /api/convert/capabilities
POST /api/convert/probe
POST /api/convert/run
POST /api/convert/select-output-dir
```

说明：

- `/api/convert/capabilities`：返回能力矩阵。
- `/api/convert/probe`：根据文件名、扩展名、MIME 和必要的文件头判断输入格式。
- `/api/convert/run`：执行转换。
- `/api/convert/select-output-dir`：复用现有目录选择能力或封装同类逻辑。

## 8. 前端模块

新增模板与静态文件：

```text
templates/convert.html
static/css/convert.css
static/js/convert-capabilities.js
static/js/convert-form.js
static/js/convert-logs.js
static/js/convert-result.js
```

页面风格与 `/use`、`/platforms` 保持一致：

- 顶部导航统一。
- 左侧可使用分类导航。
- 主区域为转换工作台。
- 底部或右侧展示日志和最近转换。

## 9. 错误处理

统一错误类型：

- 不支持的输入格式。
- 不支持的转换路径。
- 文件损坏或无法读取。
- 缺少本地依赖，例如 ffmpeg 或 LibreOffice。
- 输出目录不可写。
- 转换超时或外部命令失败。

错误文案原则：

- 告诉用户发生了什么。
- 告诉用户能否换一种方式解决。
- 不暴露冗长堆栈到 UI，但日志中保留关键命令和错误摘要。

## 10. 依赖策略

优先使用成熟本地依赖：

- 表格：openpyxl、csv、json、yaml、toml、xml 相关库。
- 图片：Pillow。
- 音视频：ffmpeg。
- 字幕：自写轻量解析或成熟字幕库。
- 压缩包：zipfile、tarfile。
- 文档基础：python-docx、markdown、HTML 解析库、可选 LibreOffice。

依赖原则：

- 第一版不引入重型云服务。
- 高风险转换不硬做。
- 缺失依赖时给出清晰安装提示。

## 11. 分阶段开发计划

### Task 1：页面入口与能力矩阵

- 新增 `/convert` 页面。
- 导航加入“文件转换”。
- 展示能力矩阵。
- 标注“稳定 / 基础 / 推荐厂商”。
- 不要求所有真实转换接通。

### Task 2：接入本地稳定转换

优先实现：

- 数据表格。
- 图片。
- 音频。
- 视频。
- 字幕。
- 压缩包。

### Task 3：接入本地基础转换

实现：

- Markdown / HTML / TXT。
- DOCX / PPTX / XLSX 基础导出。
- SVG / EPUB。

### Task 4：厂商推荐区

实现：

- 专业转换列表。
- 厂商适用场景说明。
- 不触发本地转换。

## 12. 非目标

第一版不做：

- 云端上传转换。
- PDF 转 Word / Excel / PPT 的本地高保真转换。
- OCR。
- CAD / PSD / AI / Sketch / Figma 专业格式解析。
- 高级批量任务队列。
- 复杂参数面板。

这些可作为后续产品方向，但不进入第一版实现范围。

## 13. 验收标准

第一版完成时应满足：

- `/convert` 页面可访问。
- 用户能看懂哪些转换是本地稳定、哪些是本地基础、哪些推荐厂商。
- 稳定转换路径中至少一批可真实执行。
- 转换失败时有清晰错误说明。
- 输出路径可选择。
- 页面风格与 StreamDock 当前 UI 一致。
- 不影响已有 `/`、`/use`、`/platforms` 功能。
