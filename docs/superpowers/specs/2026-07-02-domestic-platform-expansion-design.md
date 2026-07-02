# 国产主流平台扩展（小红书 / 微博 / 视频号）后端设计说明

## 1. 背景

当前项目已经具备以下基础能力：

- 统一本地网页入口
- 统一 CLI 入口
- `adapter + pipeline + exporter` 多平台骨架
- 已接入平台：抖音 / 快手 / B站
- 音频、视频多格式导出

本次工作不是重写架构，而是在现有骨架上继续扩平台。

## 2. 本轮目标

把以下三个平台接入现有后端体系：

- 小红书
- 微博
- 视频号

本轮目标优先级已经确定为：

1. **接口逆向优先**
2. **先跑通链接解析主链路**
3. **平台能力允许不完全一致**

也就是说，本轮追求的是“先把三个平台接进统一后端”，而不是一次做满所有高级能力。

## 3. 范围

### 3.1 包含

- 新增三个平台 adapter
- 支持从分享文案中提取核心链接
- 支持短链展开 / 标准化链接
- 优先通过页面内嵌状态、初始化 JSON、接口返回提取媒体信息
- 必要时使用 Playwright 作为兜底抓流手段
- 输出统一 `MediaFetchResult`
- 接入现有导出链路

### 3.2 不包含

- 批量任务
- 账号体系
- 清晰度选择 UI
- 登录态内容保证
- 私密内容支持承诺
- 直播、图文、合集、课程、回放等复杂内容类型
- 风控绕过和复杂反爬策略

## 4. 技术路线

本轮采用 **方案 C：接口逆向优先**。

### 4.1 为什么不用纯浏览器抓取优先

纯浏览器抓取虽然首版容易出结果，但问题明显：

- 稳定性差
- 页面一改容易失效
- 元数据提取不完整
- 后续做清晰度选择会比较别扭

### 4.2 为什么不用一次做深接口系统

如果一开始就做完整 session / 签名 / 风控抽象，会明显拖慢接入速度。当前阶段更合适的做法是：

- 统一公共协议
- 平台复杂性收敛在各自 adapter 内部
- 先打通结构化提取主路径

### 4.3 结论

每个平台统一采用两层策略：

1. **主路径：结构化数据提取**
   - 页面初始化状态
   - 内嵌 JSON
   - 媒体对象
   - 可直接调用的播放信息接口
2. **兜底路径：Playwright 抓流**
   - 监听页面真实请求
   - 过滤音频 / 视频候选流
   - 用 DOM 或标题补基础元数据

## 5. 现有架构保持不变

继续沿用当前结构：

- `/Users/hjjtongxue/Documents/视频解析工具/app.py`
- `/Users/hjjtongxue/Documents/视频解析工具/douyin_fetch.py`
- `/Users/hjjtongxue/Documents/视频解析工具/fetchers/pipeline.py`
- `/Users/hjjtongxue/Documents/视频解析工具/fetchers/registry.py`
- `/Users/hjjtongxue/Documents/视频解析工具/fetchers/exporters.py`
- `/Users/hjjtongxue/Documents/视频解析工具/fetchers/adapters/*.py`

本轮只新增平台适配器和必要的数据模型补强，不推翻主链路。

## 6. 适配器接口设计

`BasePlatformAdapter` 继续保留当前三段式接口：

```python
class BasePlatformAdapter:
    platform_name = "base"

    def can_handle(self, raw_link: str) -> bool:
        ...

    def normalize_link(self, raw_link: str) -> str:
        ...

    def fetch_media(self, normalized_link: str) -> MediaFetchResult:
        ...
```

原因：

- 已经和当前工程结构贴合
- 新平台接入速度快
- 复杂逻辑可以收敛在 adapter 内部

## 7. 数据模型扩展原则

### 7.1 `MediaFetchResult`

继续作为平台返回的统一结果模型，并补强以下语义：

- 顶层保留：
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
- `metadata` 中补充：
  - `resolve_method`：`api` / `embedded-json` / `playwright-fallback`
  - `raw_platform_id`
  - 原始接口或页面提取出的附加字段

### 7.2 `MediaStream`

尽量完整填充这些字段：

- `url`
- `stream_type`
- `container`
- `codec`
- `width`
- `height`
- `bitrate`
- `filesize`
- `quality_label`

这样后续做清晰度选择、大小预估、默认最优流选择时无需重做模型。

## 8. 统一选流原则

本轮虽然不做清晰度选择 UI，但后端必须预留能力。

统一约定：

- `video_streams`：保存已发现的视频流列表
- `audio_streams`：保存已发现的音频流列表
- `preferred_video`：默认推荐视频流
- `preferred_audio`：默认推荐音频流

默认策略：

- 视频：优先分辨率高，其次码率高
- 音频：优先码率高
- 若平台只返回单流，则直接作为 preferred

## 9. 错误语义

本轮先统一错误语义，不强求一次抽完整异常体系：

- `UnsupportedLink`
- `NormalizeFailed`
- `MetadataFetchFailed`
- `NoUsableStreamFound`

即使初版暂时仍以 `ValueError` / `RuntimeError` 表达，也应在 adapter 代码结构上按这四层含义组织。

## 10. 三个平台的首版策略

### 10.1 小红书

#### 主路径

- 从分享文案提取 URL
- 展开短链并标准化
- 请求页面 HTML
- 提取页面初始化状态或内嵌 JSON
- 获取：
  - note id
  - 标题
  - 作者
  - 封面
  - 视频流或媒体源

#### 兜底路径

- Playwright 打开页面
- 监听媒体请求
- 识别 mp4 / m3u8 / 音视频流候选
- 结合标题和 DOM 补元数据

#### 首版边界

- 优先支持公开视频笔记
- 图文和复杂混合内容暂不纳入承诺

### 10.2 微博

#### 主路径

- 解析分享 URL
- 标准化到可访问页面
- 请求 HTML 或 H5 页面
- 优先提取页面中的媒体对象，如 `page_info` / `media_info` 等结构
- 获取：
  - mid 或媒体对象 id
  - 摘要 / 标题
  - 作者
  - 封面
  - 视频流地址

#### 兜底路径

- Playwright 打开最终页
- 监听真实播放请求
- 提取视频流
- 用 DOM 补标题、作者等基本信息

#### 首版边界

- 只承诺公开视频
- 直播、登录态限制内容不纳入本轮完成标准

### 10.3 视频号

#### 主路径

- 解析分享链接
- 跟随跳转拿到最终页面
- 请求 HTML
- 查找页面内嵌状态、播放器初始化数据或预取数据
- 获取：
  - 视频唯一标识
  - 标题
  - 封面
  - 作者（能拿则拿）
  - 媒体播放地址

#### 兜底路径

- Playwright 打开页面
- 监听真实播放流
- 识别视频流、音频流或分段流候选
- 组合为 `preferred_video` / `preferred_audio`

#### 首版边界

- 这是三者中对抗性最高的平台
- 第一版重点是公开单视频主链路

## 11. 开发顺序

固定顺序：

1. 小红书
2. 微博
3. 视频号

原因：

- 小红书适合作为“结构化提取优先”的模板平台
- 微博可复用同类思路
- 视频号最适合最后做，因为进入浏览器兜底的概率最大

## 12. 测试策略

### 12.1 Adapter 单测

每个平台至少覆盖：

- `can_handle`
- `normalize_link`
- `fetch_media` 在 mock HTML / mock API 响应下输出正确 `MediaFetchResult`

### 12.2 Registry / Pipeline 单测

覆盖：

- 新平台是否注册成功
- `detect_platform_adapter()` 是否正确命中
- `run_pipeline(dry_run=True)` 是否能返回平台、标准化链接、标题

### 12.3 API 形状测试

保证 `/api/fetch` 返回契约不被破坏：

- `success`
- `platform`
- `outputPath`
- 错误信息结构

## 13. 第一阶段完成标准

本轮完成标准定义为：

1. 新增小红书 / 微博 / 视频号三个 adapter 文件
2. registry 能识别 6 个平台
3. 每个平台至少有一条可测的 `fetch_media()` 成功路径
4. 现有导出链路无需大改即可承接结果

这意味着：

- 第一轮完成不等于“所有真实链接稳定可下”
- 第一轮完成等于“平台骨架和首条统一链路已经打通”

## 14. 风险与处理

### 风险 1：页面结构频繁变化

处理：

- 主路径优先提结构化数据
- 保留 Playwright 兜底

### 风险 2：公开页可访问性不足

处理：

- 首版只承诺公开内容
- 登录态和私密内容后续单独评估

### 风险 3：平台间能力差异

处理：

- 统一返回模型
- 允许首版平台能力不完全一致
- 后续再补齐清晰度、登录态、稳定性

## 15. 本轮结论

本轮后端扩展的最终决策是：

- 继续沿用现有多平台骨架
- 新增小红书 / 微博 / 视频号三个 adapter
- 采用“结构化数据提取优先，Playwright 兜底”的双层策略
- 第一轮只追求公开内容主链路跑通
- 为后续清晰度选择、稳定性增强保留接口和流模型
