# QQ 照片发送回传修复

2026-11-11 的实机问题与“文件→发送文件”选择器绘制故障不同：相册能列出
照片并勾选，但点发送后回到聊天，未出现图片消息。文件选择器的硬件加速
修复已由用户确认发送成功，不应用它替代相册发送流程。

## 原因

QQ 相册 `FlashTransferPickerCustomization.sendNormal()` 把选中照片封装为
`ALBUM_RESULT`，通过相册注入接口导航回原聊天 Activity。安装 APK 的发送
实现给返回 Intent 设置 `0x24000000`，即 `CLEAR_TOP | SINGLE_TOP`。
`SplashActivity` 在 APK 清单中使用 `singleTop`。

宿主只复用栈顶同组件 Activity，不处理目标在相册下面的上述标记。实机
日志连续两次出现新建 `SplashActivity`（栈深 3），新实例在 `doOnCreate()`
里自行结束，而非向已有聊天页调用 `onNewIntent()`。原聊天页重新显示，但
没有收到本次照片发送 Intent。相册的取消结果不能代替该导航 Intent。

## 修复范围

`SdActivityHost.reuseClearTop()` 在主线程处理目标位于当前 Activity 下方的
`CLEAR_TOP` 返回：只有目标 launch mode 或 `SINGLE_TOP` 标记允许保留实例时
才复用。复制完整 Intent，交给原 Activity 的 `onNewIntent()`，再按原宿主
异步结束子页面。已有聊天 Activity、照片结果和其余 Intent extras 都保留。
不改 QQ APK，不绕过权限，不自动选择或发送照片。

标准模式且未指定 `SINGLE_TOP` 的重建、启动请求结果关联、跨进程和无匹配
目标等情况仍走原有路径。已有栈顶复用规则、QQ 登录修复及文件选择器修复
保持不变；此补丁不声称覆盖 Android 全部 task/launchMode 语义。

## 验证

```sh
JAVA_HOME=/path/to/jdk python3 scripts/api29/tests/test-activity-clear-top.py
```

该测试编译真实 `reuseClearTop()` 方法，覆盖 12 种情况：组合标记、目标
singleTop/singleTask、标准模式 CLEAR_TOP、没有 CLEAR_TOP、带请求结果、远程
调用、无匹配目标、未就绪目标、栈顶目标、多层子页面、子页面已经申请退出。
检查聊天实例和照片 payload 不变、Intent 在恢复前交付、子页面结果不重复。

部署必须同时更新 runtime JAR 和 42 个匹配 boot-image 文件。构建、部署
和回滚记录在 `build/qq-photo-20261111-v1/`，保留全部既有成员访问标记及
hidden API 限制，且不改变已修复的登录等待和文件选择器方法。

实机验收需由用户从“照片”入口勾选并发送：日志应出现
`SDACTIVITY=reused|class=com.tencent.mobileqq.activity.SplashActivity|reason=clear-top-single-top`，
不再新建随后自毁的聊天 Activity，并且聊天中实际出现发送的照片。日志
中的页面绘制或 Intent 回传成功不能单独视为上传成功。

当前补丁已部署，ART DEX 校验、12 项页面复用回归、6 项登录启动回归和
3 项选择器绘制配置回归均通过。通过进程映射 inode 确认重启后的 QQ、MSF
和 Binder 都加载了新镜像。2026-11-11 用户从“照片”入口重试后明确确认
“可以发送了”，本次照片发送问题实机验收通过。该确认不代表所有类型的
图片、视频或其他 QQ 功能均已验证。
