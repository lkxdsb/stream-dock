# 海外平台扩展（YouTube / TikTok / X）后端设计说明

## 1. 背景

当前项目已经具备：

- 本地网页入口
- 统一 CLI 入口
- `adapter + pipeline + exporter` 多平台骨架
- 国内平台接入能力（抖音 / 快手 / B站 / 小红书 / 微博 / 视频号）
- 多格式音频 / 视频导出
- 基础对抗性增强能力：
  - 精确 host 校验
  - browser fallback
  - timeout 保护
  - 更稳的结构化 JSON 提取

因此，当前扩展海外平台不需要重做框架，而是继续沿用已有适配器体系。

## 2. 本轮目标

接入以下三个海外平台：

- YouTube
- TikTok
- X（Twitter）

本轮目标已经确认：

1. **只做公开视频 / 音频内容**
2. **先做公开链接可解析**
3. **平台首版能力允许不完全一致**
4. **结构化提取优先，浏览器兜底**

本轮不是做“全能海外解析器”，而是把海外平台纳入统一主链路。

## 3. 范围

### 3.1 包含

- 新增三个海外平台 adapter
- 支持分享文案中的 URL 提取
- 支持 canonical URL 标准化
- 支持结构化媒体信息提取
- 结构化提取失败时使用 Playwright fallback
- 接入现有 `MediaFetchResult`
- 接入现有下载 / 转码 / 导出链路

### 3.2 不包含

- 登录态内容
- 私密内容
- 受限地区内容
- 播放列表 / 合集 / 线程聚合
- 直播 / 回放 / Space
- 字幕 / 章节 / 高级元数据
- 批量任务
- 多账号能力
- 平台风控绕过

## 4. 总体策略

### 4.1 架构不变

继续沿用当前结构：

- `/Users/hjjtongxue/Documents/视频解析工具/app.py`
- `/Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py`
- `/Users/hjjtongxue/Documents/视频解析工具/fetchers/pipeline.py`
- `/Users/hjjtongxue/Documents/视频解析工具/fetchers/registry.py`
- `/Users/hjjtongxue/Documents/视频解析工具/fetchers/exporters.py`
- `/Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/*.py`

本轮只是在现有 adapter 体系中继续接入海外平台。

### 4.2 双层提取策略

每个平台都采用统一的两层策略：

#### 主路径：结构化提取

- 页面初始化状态
- 内嵌 JSON
- 播放信息对象
- 媒体流列表

#### 兜底路径：浏览器抓流

- Playwright 打开页面
- 监听真实媒体请求
- 补齐标题、作者、封面等基础元数据

### 4.3 平台顺序

固定顺序：

1. **YouTube**
2. **TikTok**
3. **X**

原因：

- YouTube 最适合作为海外平台模板：更完整的音视频分离与流集合
- TikTok 与抖音思路最接近，便于复用短视频经验
- X 内容形态最杂，适合最后接入

## 5. 平台级设计

## 5.1 YouTube

### 目标

- 覆盖公开 `watch` 链接和可公开访问的标准视频页
- 返回视频流与音频流
- 接入现有导出能力

### 主路径

1. 提取 share URL
2. 标准化到 canonical video URL
3. 请求页面 HTML
4. 提取页面中的播放信息对象与媒体格式列表
5. 获取：
   - video id
   - 标题
   - 作者
   - 封面
   - 视频流列表
   - 音频流列表

### 兜底路径

- Playwright 打开页面
- 监听视频 / 音频请求
- 抓取真实媒体流
- 补齐元数据

### 首版边界

- 只做公开视频
- 不做播放列表
- 不做直播
- 不做字幕
- 不承诺 age gate / region lock / login required 内容

## 5.2 TikTok

### 目标

- 覆盖公开 TikTok 视频分享链接
- 返回视频内容，尽量提取音频
- 接入统一导出链路

### 主路径

1. 提取 share URL
2. 展开短链 / 跳转
3. 标准化到 canonical URL
4. 提取页面状态 / 视频对象 / 播放信息
5. 获取：
   - video id
   - 标题或描述
   - 作者
   - 封面
   - 视频流
   - 可选音频流

### 兜底路径

- Playwright 打开视频页
- 监听真实视频 / 音频请求
- 提取可用流
- 回填基础元数据

### 首版边界

- 只做公开视频
- 不做合集
- 不做主页批量
- 不承诺登录态和受限内容

## 5.3 X（Twitter）

### 目标

- 覆盖带视频的公开状态页
- 提取状态中的视频内容
- 接入统一导出链路

### 主路径

1. 提取帖子 URL
2. 标准化到 status canonical URL
3. 请求页面 HTML
4. 提取页面媒体对象、视频对象、播放变体
5. 获取：
   - status id
   - 文本摘要
   - 作者
   - 封面
   - 视频变体流列表

### 兜底路径

- Playwright 打开公开帖子
- 监听真实媒体请求
- 提取视频变体
- 补齐标题 / 作者 / 封面

### 首版边界

- 只处理带视频的公开帖子
- 不做纯图文导出
- 不做 Space / 直播 / 长线程聚合
- 不承诺登录态限制内容

## 6. 数据模型原则

继续使用现有模型：

- `MediaStream`
- `MediaFetchResult`
- `ExportRequest`

不重构大模型，只补充语义。

### 6.1 顶层字段必须稳定

海外平台必须稳定返回：

- `platform`
- `content_type`
- `title`
- `source_url`
- `final_url`
- `cover_url`
- `author`
- `video_streams`
- `audio_streams`
- `preferred_video`
- `preferred_audio`

### 6.2 `metadata` 统一约定

建议统一约定：

- `resolve_method`
  - `api`
  - `embedded-json`
  - `playwright-fallback`
- `raw_platform_id`
  - YouTube: `video_id`
  - TikTok: `video_id`
  - X: `status_id`
- `capture_strategy`
  - 主路径或 fallback
- `page_kind`
  - `watch`
  - `short_video`
  - `status_video`

### 6.3 `MediaStream` 尽量填满

尽量填充：

- `container`
- `codec`
- `width`
- `height`
- `bitrate`
- `filesize`
- `quality_label`

尤其是 YouTube 与 X，这些字段对后续清晰度选择非常关键。

## 7. 测试策略

继续保持当前项目已经验证过的三层测试结构。

### 7.1 Adapter 单测

每个平台至少覆盖：

- `can_handle()`
- `normalize_link()`
- `fetch_media()` 成功路径
- 伪造域名误命中防御
- fallback 路径可走通

### 7.2 Registry / Pipeline 单测

覆盖：

- registry 新平台注册
- `detect_platform_adapter()` 命中：
  - YouTube
  - TikTok
  - X
- `run_pipeline(dry_run=True)` 不被新平台破坏

### 7.3 API 契约测试

继续保证：

- `/api/fetch` 返回 `platform`
- timeout 返回稳定错误
- 新平台名称能正常透出

## 8. 开发顺序

严格按以下顺序：

### Phase 1：YouTube

- host 校验
- canonical URL 标准化
- 结构化播放信息提取
- 视频 / 音频流构建
- fallback
- 单测

### Phase 2：TikTok

- host 校验
- 短链 / 跳转标准化
- 页面状态提取
- fallback
- 单测

### Phase 3：X

- host 校验
- status URL 标准化
- 媒体对象提取
- fallback
- 单测

## 9. 第一阶段完成标准

本轮完成标准定义为：

1. 新增 YouTube / TikTok / X 三个 adapter
2. registry 能识别这三个海外平台
3. 每个平台至少有一条公开视频 / 音频成功路径
4. 每个平台都接入现有统一导出链路
5. 每个平台都具备：
   - host 精确校验
   - 结构化提取主路径
   - browser fallback
   - 对应单测
6. API 契约不被破坏
7. 全量测试通过

这意味着：

- 第一轮完成不等于“所有真实链接都稳定”
- 第一轮完成等于“海外平台已经正式接入主系统”

## 10. 风险与处理

### 风险 1：平台页面结构变化快

处理：

- 主路径优先结构化提取
- 一旦失败进入 Playwright fallback

### 风险 2：公开视频与真实可取流之间仍有差距

处理：

- 首版只承诺公开内容主链路
- 登录态与区域限制后续单独评估

### 风险 3：平台能力天然不一致

处理：

- 统一 `MediaFetchResult`
- 接受首版能力不完全一致
- 后续再补齐清晰度与稳定性

## 11. 本轮结论

本轮海外平台扩展的最终方向已经明确：

- 平台：YouTube / TikTok / X
- 内容：公开视频 / 音频
- 路线：结构化提取优先，Playwright fallback 兜底
- 顺序：YouTube → TikTok → X
- 标准：先打通主链路，不追求一步做满
