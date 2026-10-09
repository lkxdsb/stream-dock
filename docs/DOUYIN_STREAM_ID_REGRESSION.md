# 抖音签名路径与视频流身份回归

用户短链：`https://v.douyin.com/HvwL94gt_Xk/`，标题关键字：男生择偶基本盘。

## 根因

预览与下载任务分别解析平台。抖音 CDN 会轮换域名，并刷新路径中
`/<32 位十六进制签名>/<8 位十六进制字段>/video/tos/...` 的临时前缀。
原 streamId 仅排除 query，仍将域名和整个路径纳入计算，因此同一档媒体重新解析后无法匹配。

## 修复边界

- 只针对 `.douyinvod.com` 子域及上述已观测路径规范化。
- 保留 `/video/tos/` 后的完整资源路径、编码、尺寸、码率和画质标签。
- 不将任意平台域名或任意路径当作等价资源；匹配失败仍明确报错，不静默下载默认画质。
- 单测覆盖 CDN/签名刷新、不同资源/编码/尺寸及伪造域名。
- 旧任务中的旧 ID 不会自动迁移，需重新识别再执行。

## 2026-10-09 验证

- 两份真实解析响应：22/22 视频流 ID 稳定且唯一，逐项回放 resolve_media_selection 成功。
- 本地服务已实际重启，加载新的 ID 算法。
- 实际 API 预览 → 携带 streamId 提交下载队列 → 任务独立重新解析 → MP4 下载完成。
- FFprobe 检查 MP4 容器、视频/音频流、尺寸与所选画质；FFmpeg 全文件解码通过。
- 三个时间点抽帧验证像素方差，音频全程 volumedetect 检查不是静音。
- 首轮真实下载任务在解析阶段遇到平台登录要求；第二轮成功。这是独立的上游访问不稳定性，未宣称已经修复或绕过。
- Python 全量回归：452 passed，41 subtests passed。

本地证据保存在忽略入库的 `report_figures/hvw-selection-replay.json`、
`report_figures/hvw-stream-fixed-live/acceptance.json`（失败）及
`report_figures/hvw-stream-fixed-live-second/acceptance.json`（成功）。

可选真实验收（会创建下载任务并保存真实文件，不应作为离线 CI）：

```bash
python scripts/test_stream_selection_live.py \
  --link 'https://v.douyin.com/HvwL94gt_Xk/' \
  --expected-title '男生择偶基本盘' \
  --output-dir report_figures/stream-selection-new-run
```

每次使用新的输出目录；不修改平台授权、不清理用户历史。
