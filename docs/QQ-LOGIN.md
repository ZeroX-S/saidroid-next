# QQ 登录子进程启动修复

2026-11-10 的 API28 r323k 实机日志显示，QQ 的 `:MSF` 和 `:tool` 进程仅
APK 类加载就耗时约 37 秒，而原 Activity、Service 和 Provider 发布等待只有
30 秒。调用方先报告失败，子进程随后才发布 Binder endpoint。

`SdProcessStartup` 统一这三个入口的有界等待为 120 秒，只接受存活的 Binder，
并继续传播中断和 Binder 查询异常。不修改 APK、账号、权限或 ART 校验策略。
该等待预算允许启动排队、未缓存 APK 的类加载和 Application 初始化；它不是
完整登录超时配置，也不能证明所有登录后功能正常。

远程 Activity 返回结果并清空自身 Activity 栈时保留其应用进程、Service 和
Binder endpoint，避免验证后的下一步再次冷启动。再次显式启动远程 Activity
会恢复前台状态。用户关闭任务以及主应用退出后的宿主清理仍终止相应进程。
主应用自己的空栈退出规则不变。

## 部署必须同步更新启动镜像

该组件把 `lib/runtime.jar` 一起编入 boot image。实机曾出现 JAR 已替换、但
`boot-runtime.vdex` 仍没有 `SdProcessStartup`，日志继续执行旧 30 秒等待的情况。
只替换 JAR 或重新打开 QQ 不足以启用修复。

必须使用当前组件的完整 boot classpath、相同的逻辑 DEX 路径和原有
`preloaded-classes` 重建整套 `.art`、`.oat`、`.vdex` 文件，并同步更新
`share/build/boot-image-manifest.json` 及 `runtime.json` 的镜像摘要。
安装前备份并通过宿主接口关闭使用这些镜像的应用和 Binder 进程；校验所有
输入、输出摘要且确认没有残留镜像映射后再替换。失败时恢复原文件，不清除
应用数据、不关闭 ART 校验，也不改核心 framework JAR 的隐藏 API 标记。

2026-11-10 的实机热修复构建记录保存在
`build/qq-login-20261110-v4/boot-image/`。该组件的 13 个 framework boot JAR
和 runtime JAR 生成 42 个镜像文件；不要把其他版本的固定文件数用于此组件。
重启后的验收应确认新进程映射到新镜像，远程 Service 发布成功，以及验证
Activity 结束后出现 `SDACTIVITY=remote_stack_empty|process_retained=true`。

本次部署已校验 42 个镜像文件，并通过进程映射的 inode 确认新启动的 QQ、
MSF 和 Binder 使用新镜像。QQ 登录页已绘制，MSF 约 34.5 秒才完成初始化，
调用方仍成功收到 `remote_process_ready`，未出现旧启动超时。记录分别在
`boot-image/launch-validation.json` 和 `boot-image/loaded-image-validation.json`；
这些启动检查不代表完整登录已经成功。

随后用户在实机完成两次验证；两次 `RESULT_OK` 都由同一个 `:tool` 进程
交付，且两次结束时都记录了进程保留。主进程随后结束登录 Activity 并进入
QQ 主界面，实际屏幕已确认显示消息/聊天列表，本次登录问题实测通过。
最终验收记录为 `boot-image/login-acceptance.json`，截图仅本机私有保存，不
在文档中记录账号、会话内容或认证数据。发送消息等其他功能不在本次验收范围。

## 回归与登录验收

等待逻辑回归：

```sh
JAVA_HOME=/path/to/jdk python3 scripts/api29/tests/test-process-startup.py
```

覆盖立即就绪、超过旧 30 秒窗口后就绪、死亡 Binder、最终超时、中断和
Binder 查询异常。`native/host/tests/device-remote-activity.py` 还检查两个完整
的真实 Binder Activity 往返，第二次必须复用同一 PID 和 launch ID，并正确
交付结果及恢复窗口焦点。该设备测试需要其现有的独立 APK、输入工具和锁环境。

安装后的验收需要用户操作 QQ 登录；不得将验证码回调或 `RESULT_OK` 单独视为
登录成功。修复不自动提交密码、短信验证码或其他账号认证数据。
