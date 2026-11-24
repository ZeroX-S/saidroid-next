# 当前验证范围（Android 9 / API 28）

主线运行时已统一收敛为 Android 9（API 28）兼容目标，移除了旧的 API 29 运行时支持与 `r321o` 历史快照。

## 已整合与验证的关键范围

| 模块 | 状态与说明 |
|---|---|
| API 28 框架与公共 SDK | 对齐框架 ABI、JNI 注册表（`native/api28-jni-entries.inc`）与 Java CLI；恢复 185 个缺失的 API 28 公共 SDK 成员 |
| 跨进程组件生命周期 | Activity、Service、ContentProvider 与 ManifestReceiver 统一支持私有 Binder 跨进程启动及 120 秒有界存活等待（`SdProcessStartup`）；远程 Activity 空栈保留应用进程 |
| Activity 栈与窗口路由 | 支持 `CLEAR_TOP \| SINGLE_TOP` 已有实例复用（`reuseClearTop`）；分离首次按下触摸目标选择与键盘焦点选择（`touchTarget`），恢复非聚焦 `PopupWindow` 点击 |
| 普通显式广播分发 | `SdActivityManagerService.broadcastIntent` 接通显式组件广播至 `SdManifestReceivers`，并与 `SdServiceEndpoint` 事务 9 配套工作 |
| 显示、WebView 与文件选择 | 原生显示事件接入 Wayland；集成 Atlantic/WPE 运行库及页面错误恢复；本地只读文件选择器（`SdDocumentPicker` / `SdDocumentsProvider`）按窗口后端匹配硬件加速 |
| 音视频与语音通话 | PulseAudio 麦克风权限与录音桥接、Camera1 预览与纹理更新、GStreamer 元数据/缩略图宽高比，以及 API 28 SIP 注册与 PulseAudio RTP 通话 |
| 安装与激活 | 支持可选封签 RPM 自动激活（`%pre` 检查跨版本运行进程，`%posttrans` 触发激活）及无 `binderfs` 内核上的受信任静态 Binder 节点兜底 |

## 待持续完成的设备端验收

- 微信服务号、公众号与小程序页面的长时稳定性端到端验收。
- 多设备端口上的完整商业应用交互回归与完整 CTS 验证。
- 详细 QQ 问题定位与回归说明见 `docs/QQ-LOGIN.md`、`docs/QQ-PHOTO-SEND.md`、`docs/QQ-RECEIVED-FILE-OPEN.md` 和 `docs/QQ-FILE-FORWARD.md`。
