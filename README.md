# StreamDock

StreamDock 是一个本地优先的媒体解析与文件处理工作台。它将多平台视频解析、文件格式转换、字幕处理、PDF 深度解析和异步任务管理集中在同一个 FastAPI Web 应用中，结果默认保存在用户指定的本地目录。

> 请仅处理你拥有或已获授权使用的内容，并遵守来源平台条款与当地法律。

## 功能概览

### 多平台媒体解析

- 统一处理链接识别、短链还原、作品信息提取、候选流分析、清晰度选择、下载和输出校验。
- 优先使用页面或接口中的结构化数据，失败时可回退到 Playwright 浏览器播放态。
- 支持视频、音频、图文作品、封面和原生字幕等资源；分离的音视频流通过 FFmpeg 合并。
- 视频文件校验完成后即可结束媒体任务，ASR/OCR 字幕识别在独立后台队列继续执行。

| 平台 | 当前状态 | 主要能力 |
| --- | --- | --- |
| 抖音 | 稳定 | 视频、图文作品、无水印图片集、浏览器登录态 |
| Bilibili | 稳定 | DASH、progressive `durl`、多档画质、音视频合并、可选 Cookie |
| 快手 | 稳定 | 视频候选源、HLS 下载与合并 |
| 小红书 | 部分支持 | 视频、图文识别、浏览器回退 |
| 微博 | 部分支持 | 视频变体识别、浏览器回退 |
| 视频号 | 受限 | 分享链接、预览接口、浏览器回退 |
| YouTube | 实验性 | 公开视频格式枚举、音视频合并 |
| TikTok | 实验性 | 公开分享页、候选源与浏览器回退 |
| X / Twitter | 实验性 | 推文视频变体与码率选择 |

平台返回结果受登录状态、内容权限、地区限制和页面结构变化影响。工具不会绕过账号本身无权访问的内容。

### 文件格式转换

- 当前能力矩阵登记了 176 条转换路径，覆盖文档、表格、图片、音频、视频、字幕、电子书和压缩包。
- 成熟路径使用 Pillow、openpyxl、python-docx、FFmpeg 等本地引擎。
- Office 与开放文档格式可调用 LibreOffice；复杂排版、公式、批注和动画可能有损。
- 支持格式探测、目标格式校验、同格式批量任务、超时控制、临时文件清理和结果打开。
- 对暂不适合本地处理的复杂格式给出专业工具建议，而不是伪造转换结果。

### 字幕工作台

- 导入并解析 SRT、VTT 和 TXT。
- 在浏览器中编辑字幕时间轴与文本，并导出为 SRT、VTT 或 TXT。
- 媒体解析按“平台原生字幕 → ASR → 画面 OCR”顺序补充字幕。
- ASR/OCR 失败不会覆盖已经成功下载的视频结果。

### PDF 深度解析

- 分析文本层、图片比例和页面特征，推荐自动、文本或 OCR 策略。
- 使用独立的 MinerU 环境执行深度解析，避免与主程序依赖冲突。
- 通过异步任务展示进度、结构化 Markdown、结果文件和归档状态。
- MinerU 不可用时会通过健康检查给出明确提示，不影响其他工作台使用。

### 任务与运行状态

- 媒体、字幕、文件转换和 PDF 任务统一进入本地任务中心。
- 支持查看详情、重试、删除、清理已完成任务，以及暂停和恢复媒体等待队列。
- `TaskStore` 持久化任务状态，服务异常退出后会标记未完成的后台工作。
- 错误目录提供结构化错误码、可重试状态和建议操作。
- 环境检查覆盖 Python、FFmpeg/FFprobe、Playwright、ASR、OCR、PDF 引擎和输出目录。

## 快速开始

### 环境要求

- Python 3.11+
- FFmpeg 和 FFprobe
- macOS、Linux 或 Windows；项目当前主要在 macOS 环境验证
- 推荐使用 Conda 隔离 Python 依赖

以 macOS 为例，可先安装 FFmpeg：

```bash
brew install ffmpeg
```

### 安装与启动

```bash
git clone https://github.com/lkxdsb/stream-dock.git
cd stream-dock

conda create -n jj python=3.11 -y
conda activate jj
pip install -r requirements.txt

uvicorn app:app --host 127.0.0.1 --port 8002 --reload
```

打开 <http://127.0.0.1:8002>。

macOS 也可以直接双击 `start_streamdock.command`。脚本会使用 `jj` 环境、检查端口、等待健康检查通过并自动打开浏览器。

如需使用浏览器回退能力，安装 Chromium：

```bash
playwright install chromium
```

### 可选依赖

| 能力 | 依赖 |
| --- | --- |
| Office / OpenDocument 转换 | LibreOffice |
| 语音字幕 | `faster-whisper`、OpenAI Whisper 或 Whisper CLI |
| 画面字幕 OCR | Tesseract OCR、FFmpeg |
| PDF 深度解析 | 独立 MinerU 环境 |

PDF 环境安装：

```bash
bash scripts/setup_mineru_env.sh
```

首次执行深度解析时可能下载模型。模型文件不应提交到 Git 仓库，相关第三方许可见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

## 页面入口

| 地址 | 功能 |
| --- | --- |
| `/` | 产品首页与运行环境概览 |
| `/use` | 媒体链接解析与下载 |
| `/platforms` | 平台能力、限制和运行状态 |
| `/convert` | 文件转换、批量任务和能力矩阵 |
| `/subtitles` | 字幕导入、编辑与导出 |
| `/pdf` | PDF 分析和深度解析 |
| `/updates` | 产品更新记录 |
| `/about` | 项目说明 |

环境健康接口：<http://127.0.0.1:8002/api/health>

## 常用配置

| 环境变量 | 用途 |
| --- | --- |
| `STREAMDOCK_PORT` | `start_streamdock.command` 使用的监听端口，默认 `8002` |
| `STREAMDOCK_TASK_STORAGE_PATH` | 自定义任务状态存储路径 |
| `STREAMDOCK_ALLOW_LAN_API=1` | 允许非本机来源访问 API；默认关闭 |
| `STREAMDOCK_MINERU_EXECUTABLE` | 指定 MinerU 可执行文件 |
| `STREAMDOCK_SUBTITLE_ASR_MODEL` | 指定 ASR 模型，默认 `base` |
| `STREAMDOCK_SUBTITLE_ASR_DEVICE` | 指定 ASR 设备，默认 `cpu` |
| `STREAMDOCK_SUBTITLE_ASR_LANG` | 指定 ASR 语言，默认 `zh` |
| `STREAMDOCK_SUBTITLE_OCR_LANG` | 指定 Tesseract 语言，默认 `chi_sim+eng` |
| `BILIBILI_COOKIE` | 手动提供 Bilibili Cookie |
| `BILIBILI_COOKIE_FILE` | 从本地文件读取 Bilibili Cookie |

Cookie 仅应通过本机环境或未跟踪文件提供，不要写入源码、日志、Issue 或提交记录。

## 测试

运行完整回归测试：

```bash
conda run -n jj python -m unittest discover -s tests -v
```

也可以在已经安装 pytest 的开发环境中运行：

```bash
conda run -n jj python -m pytest -q
```

检查前端脚本和 Git diff：

```bash
for file in static/js/*.js; do node --check "$file"; done
git diff --check
```

## 项目结构

```text
stream-dock/
├── app.py                 # FastAPI 页面、API 与任务编排
├── fetchers/
│   ├── adapters/          # 各平台链接规范化与媒体信息提取
│   ├── pipeline.py        # 统一探测、下载、导出与字幕策略
│   └── downloader.py      # 直链、HLS 与 yt-dlp 下载
├── converters/
│   ├── adapters/          # 文档、图片、媒体、字幕和归档转换器
│   ├── registry.py        # 转换能力矩阵
│   └── pipeline.py        # 转换探测与执行
├── subtitles/             # 字幕解析、校验和导出
├── pdf_engine/            # PDF 分析、策略、质量评估与 MinerU 适配
├── tasks/                 # 媒体、字幕、转换、PDF 队列与状态存储
├── templates/             # Jinja2 页面模板
├── static/                # 样式、交互脚本和图标
├── runtime_checks.py      # 环境、代理、输出和媒体质量检查
├── tests/                 # 单元、API、任务与平台回归测试
└── scripts/               # 环境安装、鲁棒性测试和构建脚本
```

核心媒体流程：

```text
输入链接
  → 平台识别与链接规范化
  → 结构化信息提取
  → 浏览器回退（按需）
  → 媒体候选与清晰度选择
  → 下载 / FFmpeg 合并
  → 输出质量检查
  → 后台字幕任务（按需）
```

## 隐私与安全

- 服务默认仅监听 `127.0.0.1`，API 默认拒绝非本机来源。
- 上传文件、转换结果和任务结果保存在本地，不需要上传到 StreamDock 服务器。
- 上传大小、批量数量、任务超时、磁盘空间、输出目录和临时文件均有边界控制。
- 浏览器登录态只用于用户主动授权的平台解析，不会提升账号本身权限。
- `.gitignore` 已排除常见 Cookie、日志、输出目录、缓存和临时下载文件；发布前仍应人工检查。

## 当前边界

- 平台页面、接口和风控策略会变化，实验性平台不保证长期稳定。
- 受登录、会员、地区、版权、作者设置或下架状态限制的内容可能无法解析。
- 本地格式转换以可验证结果为目标，不承诺复杂排版和专有格式的完全保真。
- ASR、OCR 和 PDF 模型会占用额外磁盘、内存和处理时间。

## License

项目当前尚未添加统一的开源许可证。在明确许可证之前，仓库公开可见不代表自动授予复制、修改或再分发权限。
