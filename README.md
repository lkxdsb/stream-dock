# StreamDock

StreamDock 是一个本地优先的媒体处理工具，当前包含三组核心能力：

- 视频链接解析：支持多平台链接识别、候选流分析、清晰度策略、音视频合流和输出质量检查。
- 文件格式转换：支持文档、表格、图片、音视频、字幕和压缩包的成熟本地转换路径，并支持同格式批量任务。
- PDF 解析：独立 PDF 工作台、异步任务、自动策略回退、结构化 Markdown 浏览和结果归档。

> 请仅处理你拥有或已获授权使用的内容，并遵守来源平台条款与当地法律。

## 本地运行

环境要求：Python 3.11+、FFmpeg。推荐使用项目已验证的 Conda 环境 `jj`。

```bash
conda activate jj
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8002 --reload
```

访问：<http://127.0.0.1:8002>

也可以双击 macOS 启动脚本 `start_streamdock.command`。

## PDF 引擎（可选）

PDF 深度解析使用独立环境，避免与主程序依赖冲突：

```bash
bash scripts/setup_mineru_env.sh
```

首次运行会下载模型，模型不应提交到 Git 仓库。第三方许可说明见 `THIRD_PARTY_NOTICES.md`。

## 测试

```bash
conda run -n jj python -m unittest discover -s tests -v
```

## 隐私与安全

- 默认仅监听 `127.0.0.1`，不对公网开放。
- 文件转换和任务结果保存在用户选择的本地目录。
- 上传大小、任务超时、输出目录和临时文件均有边界控制。
- 浏览器登录态仅用于用户主动授权的平台能力，不应上传或提交 Cookie。

## 项目结构

- `app.py`：FastAPI 路由与任务编排
- `fetchers/`：平台适配、媒体流筛选、下载与导出
- `converters/`：文件转换能力与格式矩阵
- `pdf_engine/`：PDF 分析、解析、质量评估与引擎适配
- `tasks/`：媒体、转换、PDF 异步任务队列
- `templates/`、`static/`：模块化页面、样式和交互
- `runtime_checks.py`：环境、输出与媒体质量检查
- `tests/`：单元及接口回归测试

## 发布说明

项目当前适合本地试用。创建 GitHub 仓库前请确认许可证、仓库可见性，并检查提交中不存在 Cookie、下载内容、模型权重和个人路径。
