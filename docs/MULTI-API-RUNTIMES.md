# API28/API29 运行时选择与冷切换

这轮实现完整运行时并存、只读候选检查和全局冷切换。每次启动只初始化所选
release 的一个框架、JNI 集合和 ART；切换沿用安装工具的锁、日志、回滚和恢复
事务。当前仍只有一个活动运行时、一个 HostManager 和一个 Binder 服务域。

## 必须区分的版本

| 版本 | 作用 | 选择规则 |
| --- | --- | --- |
| 手机 vendor / libhybris API | 相机、图形等设备原生库 ABI | 由实际设备适配确定；不能只改 SDK 属性 |
| SailDroid framework API | 应用可见的类、资源和 `SDK_INT` | 由完整 release 的 `runtime.json` 声明，28 或 29 |
| ART / libcore ABI | VM、boot image、核心 Java/JNI 实现 | 必须与该 release 的 boot jars 和原生库成套验证；不等同于 framework API |
| APK minSdk / targetSdk | 最低平台要求、应用兼容行为 | 读取真实 APK；不伪造、不把 targetSdk 当作必须选择的运行时版本 |

Android 的 [uses-sdk 文档](https://developer.android.com/guide/topics/manifest/uses-sdk-element)
区分最低平台要求和 targetSdk 兼容行为。比如 minSdk 26、targetSdk 33 的应用，
不能仅凭 targetSdk 33 就判定必须建立 API33 运行时；运行成功还依赖实际 API
调用和后端能力。minSdk 29 的应用则不能靠把 targetSdk 改成 28 来适配 API28。

## 已实现的入口

以下命令由**新构建、已封装的 setup helper**提供，历史已安装版本不会因源码
更新自动得到这些命令。`SETUP` 指向该版本自己的绝对路径，例如
`/opt/saildroid/releases/<release-id>/bin/saildroid-setup`。按现有安装流程以 root
执行，并在设备锁内进行有状态操作。

```sh
"$SETUP" profiles
"$SETUP" select-api 28
"$SETUP" select-api 28 --release <api28-release-id>
# 退出所有 SailDroid 应用及其 native session / broker / helper 后：
"$SETUP" select-api 28 --release <api28-release-id> --apply
"$SETUP" rollback
# 仅在工具报告中断事务时：
"$SETUP" recover
```

`profiles` 检查 `/opt/saildroid/releases` 的实际封装内容，包含文件哈希、路径、
所有权、权限、RPM 和 capability 检查。无效目录会保留诊断原因。工具读取
`runtime.json.api`，不从 release 名称推测 API，也不下载或安装运行时。

`select-api` 默认只预览，不创建状态目录、切换链接或写 launcher。若同一 API
有多个有效 release，必须提供 `--release`，不按文件时间或版本名称猜测。
预览会列出仍在运行的进程及中断事务；应用阶段会重新检查和取得启动锁。

`--apply` 只选择已有完整 release。运行中应用、会话、broker、WebView/media
helper 或编译辅助进程未退出时拒绝操作，不主动杀进程。哈希、API 或安装依赖
检查失败同样拒绝切换。文件快照、launcher 刷新失败和掉电恢复均复用原有事务。
框架的 `build.prop`、activation manifest（存在 API 字段时）必须与 runtime API
一致。兼容旧的未记录 API 的 activation manifest；旧 release 没有 `build.prop`
时仍按原有包验证规则处理。

活动链接仍使用历史名称 `/home/art/api29-root`。它现在可能指向完整 API28
release；这个路径不是 SDK 声明。保留它是为了兼容已有 launcher、CLI 和
bootclasspath location，不能在切换时只替换它下面的某几个 JAR 或原生库。
应用 APK 和数据不会被此工具迁移或清空；这不保证应用自身在不同框架版本间
写出的数据库格式可逆。对重要应用数据，真机验收前应保留既有备份。

## 打包与初始化边界

`build-setup-payload-vm.py --api 28|29` 按目标 API 构建 setup 的小型 DEX，默认
仍为 29。这个参数只控制 setup payload，不能把 API29 产品转换为 API28。
`seal-setup-manifest-vm.py` 从实际 `runtime.json` 获取 API，再核对框架属性；
不会再硬编码 `api=29`。

完整 API28 release 仍需自己的 Java 编译输入、API28 native registration、
framework resources、boot image、libcore/ART ABI、libhybris 插件和 CLI 验收。
现有 `scripts/api29/build-product.py --api 28|29` 已选择对应框架、Java 源码
变体、DEX 最低 API 和原生显示事件 ABI。PR #3 的源码已整合到开发分支，
两套产品构建及定向回归通过；权限改为 root 管理、绑定 APK 哈希的只读策略。
可信交互授权界面和完整 API28 手机运行时闭包仍需单独验收，详见
[PR3 整合说明](PR3-INTEGRATION.md)。
安装文件校验通过表示包完整，不表示该 API 的 UI、权限或 CTS 功能已通过。

冷切换在旧进程退出后重新启动选中的独立宿主，在创建 VM 前确定所有库路径和
bootclasspath。API 切换不会改写已经运行的 ART、`Build.VERSION.SDK_INT` 或
应用 targetSdk。当前所有 framework services 仍按现有逻辑安装，没有宣称
实现服务按需初始化或测得启动速度提升。

## 后续优化顺序

1. 完成 API28 独立、可重建的完整运行时闭包，并建立可信的宿主交互授权服务。
   当前 root 策略已关闭旧的自写授权文件入口；应用内对话框不能新增授权。
2. 对每个完整 profile 记录 framework/native API、ART/libcore ABI、boot image
   指纹与支持的 vendor 适配；封装、native host 和 Java 启动共同校验。
3. 在真实设备分别通过 CLI、窗口/输入、WebView、媒体、权限、生命周期和
   CTS 定向验收，再进行 API29→28→29 的真实冷切换。每次核对进程路径、
   框架 SDK、launcher、应用数据和回滚结果。
4. 按启动阶段记录耗时及 PSS，检查哪些后端可以按角色延迟加载。只有具备依赖
   声明、幂等初始化和失败处理的服务才延迟；不能简单跳过任意 JNI 注册项。
5. 按应用选择 API 前，先拆分 HostManager D-Bus 名称、Binder driver/服务域、
   运行目录、锁、ART cache、跨应用 Intent/provider 路由及进程回收规则。
   同一应用的主进程和所有声明子进程必须锁定同一个 release 和启动代次。

同一 ART 进程内热换框架不在此方案中。当前 native host 使用
`JniInvocation`/`JNI_CreateJavaVM`，框架类、JNI 绑定和窗口都属于该进程。
将来产品中的“动态切换”应当先结束指定应用的整组进程，再从新 profile
冷启动；不同 API 并发需要上述服务域隔离，不能只增加一个环境变量。

## 本轮验证范围

在 aarch64 Linux 构建 VM 中执行：

```sh
python3 scripts/packaging/test-setup-vm.py --output <new-output>
python3 scripts/packaging/build-setup-payload-vm.py \
  --api 28 --bootstrap-jar <pristine-cli.jar> --r8 <r8.jar> --output <new-output>
# 再以 --api 29 构建另一输出目录。
```

安装事务夹具在 umask 022、077 下覆盖跨 API 切换、回滚、刷新失败、启动锁、
残留 helper、歧义候选、损坏包、属性不匹配、只读预览及中断恢复。helper
检查使用真实 `/proc` 中的一次性 VM 进程。API28/29 的 seal round-trip 和两个
setup payload 的 Java/D8/hidden-API 编码构建也包括在内。

2026-11-10 验证结果：两种 umask 各 59 项安装事务用例通过（共 118 项），
两套 setup payload 构建通过；新 registry DEX 在现有 API29 ART CLI 中的
5 项隔离测试也通过，包括错误 root、boot main、隐藏 registry 反射拒绝、
正常 launcher 刷新及损坏应用记录拒绝。

这些是安装事务和辅助构建验证，API28 fixture 不代表真实 API28 ART 已启动。
上述管理层首轮验证未安装手机包、切换手机活动运行时、重跑真机 UI 或完整
CTS。后续 PR3 整合的构建、API29 真机冷激活及 QQ/WebView 验证记录见下文链接。

## PR3 整合

源码构建按 `--api` 选择完整的框架接口族，详见
[PR3-INTEGRATION.md](PR3-INTEGRATION.md)。API28 辅助包编译通过不代表
API28 完整手机运行时已通过验收，也不能据此改写 API29 root 的版本属性。
