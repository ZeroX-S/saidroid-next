# SailDroid 架构审查与后续优化路线图

本文梳理 SailDroid（Android 9 / API 28 独立 ART 运行时）现行架构的核心短板、关键性能瓶颈及分阶段（P0~P3）演进路线，指导后续版本迭代。

---

## 一、现行架构拓扑

SailDroid 采用**独立 ART + Bionic 符号转译 + 进程内伪系统服务 + Wayland 原生窗口宿主**路线，每个 Android 应用（及其声明的 `:service`/`:provider`/`:receiver` 子进程）以普通用户身份运行在独立 Linux 进程中：

- **宿主控制平面**：`saildroid-app`（文件 capability 初始化调度与 `oom_score_adj` 后立即降权）→ `saildroid-host --session`（Session D-Bus 上的 `org.saildroid.HostManager1`）+ `SdBinderRegistry`（私有 Binder 上的服务注册表）。
- **应用运行时平面**：`saildroid-host` + `libsdhost29.so`（运行时兼容名，源码位于 [`native/compat/runtime-*.c`](../native/compat/)）→ [`SdRuntime`](../scripts/device/SdRuntime.java) + [`SdServices`](../scripts/device/SdServices.java)（23 个进程内系统服务适配）+ [`sdbridge.c`](../scripts/device/sdbridge.c)（`bionic_translation` 加载 Android 原生库）。
- **图形、WebView 与媒体辅助平面**：[`sdwindow.c`](../native/window/sdwindow.c)（Wayland 主窗口、HWUI `wl_subsurface` 与软件 SHM 合成）、[`sdwebviewd.cpp`](../native/webview/qt-helper/sdwebviewd.cpp)（外部 Qt5 + Atlantic WPE 进程）、[`camera-host.cpp`](../native/media/droid-camera/camera-host.cpp)（`sdcamera-helper` Camera1 桥接）、GStreamer 播放器与 PulseAudio 音频/RTP 通话。

---

## 二、核心架构短板

1. **无 Zygote 的每进程全量冷启动与“单包孤岛”模型**
   - 主进程、后台子进程乃至 `SdBinderRegistry` 均独立冷启动完整 ART 虚拟机（`-Xnoimage-dex2oat`），重复注册 JNI、初始化 23 个服务并用 `PackageParser` 全量解析 APK（[`SdApkPackage.java`](../scripts/device/SdApkPackage.java)）。
   - 进程内 `PackageManager` / `ActivityManager` 仅感知当前绑定的单一 APK，跨应用 `Intent` 分享、第三方登录（微信/QQ SSO）及跨包 `ContentProvider` 尚无法互通；[`SdRuntime.java`](../scripts/device/SdRuntime.java) 仍残留针对特定三方库（如 `MMKV`）的反射分支。
2. **动态代理 + 线性字符串匹配的脆弱服务分派**
   - [`scripts/device/`](../scripts/device/) 下 26 个服务类依赖 `java.lang.reflect.Proxy` + `InvocationHandler`，累计约 450 处 `.equals("...")` 线性分支与 `Object[]` 下标强转，缺乏 AIDL 编译期类型检查，且仍有千余个低频框架接口签名未覆盖。
3. **控制平面多通道耦合与轮询同步**
   - Session D-Bus、`XDG_RUNTIME_DIR/*.json` 状态文件、`window-*.sock` 控制套接字与私有 Binder 四套机制并存，跨进程拉起依赖 50ms 休眠轮询（[`host-entry.cpp`](../native/host/host-entry.cpp)、[`SdProcessStartup.java`](../scripts/device/SdProcessStartup.java)）。
4. **双链接器符号抢占与私有 C++ 符号耦合**
   - 依赖长 `LD_PRELOAD` 链与 `RTLD_GLOBAL` 注入；[`sdwebviewd.cpp`](../native/webview/qt-helper/sdwebviewd.cpp) 通过 `QLibrary::resolve` 直接绑定 `libqtwpe.so` 的 C++ 修饰符号，对上游组件重编敏感。
5. **构建体系与沙箱边界局限**
   - 原生模块仍由 Python 脚本直接拼接编译器命令（[`build-product.py`](../scripts/runtime/build-product.py)），缺乏 Meson/CMake 增量构建；69 组 Core Overlays（[`scripts/runtime/core/`](../scripts/runtime/core/)）维护成本高；多应用共享同一宿主 UID，缺乏文件系统命名空间隔离。

---

## 三、关键性能瓶颈

| 编号 | 瓶颈域 | 严重度 | 根因摘要 |
|---|---|---|---|
| **P1** | WebView 离屏回读与管道传帧 | **致命** | [`sdwebviewd.cpp`](../native/webview/qt-helper/sdwebviewd.cpp) 每帧执行 `fbo->toImage()`（同步 `glReadPixels` 阻塞 GPU）并经 `stdout` 匿名管道向 [`SdWebEngine.java`](../scripts/device/SdWebEngine.java) 传输 9~33 MB RGBA 原始像素，全链路 7~8 次拷贝且单帧串行 `frame_ack`；每个 WebView 独立拉起 3 个进程 |
| **P2** | 应用与子进程冷启动串行阻塞 | **致命** | 全局单槽 `TryAcquireHeavy` 队列串行化所有 ART 进程启动；50ms 轮询等待叠加无 Zygote 类加载与大体积 APK 重复解析 |
| **P3** | 待机后台轮询与 `/proc` 遍历 | **高** | [`SdAudio.java`](../scripts/device/SdAudio.java) + [`host-audio.cpp`](../native/host/host-audio.cpp) 每 2s 新建并销毁一次 PulseAudio 连接；`SdThermal`（2s）、`SdTimeZone`（5s）常驻唤醒；[`host-manager.cpp`](../native/host/host-manager.cpp) 每 250ms 巡检并在进程退出后扫描全系统 `/proc` |
| **P4** | JNI 热路径查找与分配开销 | **高** | 渲染/音频 JNI 回调未全量缓存 `jmethodID`、窗口重排与多点触控数组每帧重复分配（已在 P0 阶段着手收敛） |
| **P5** | 相机预览与多图层软件合成 CPU 标量循环 | **高** | [`camera-host.cpp`](../native/media/droid-camera/camera-host.cpp) 每帧通过 `socketpair` 拷贝并由 CPU 标量双循环做 NV21→RGBA 与跨列旋转；软件模式 >1 图层退化为全屏 `getPixels` 拷贝 |
| **P6** | 跨进程广播线性枚举 | **中** | [`SdRemoteServices.java`](../scripts/device/SdRemoteServices.java) 每次广播调用 `listServices` 全量枚举私有 Binder 服务并逐一同步检查 |
| **P7** | 多进程内存（PSS）重复占用 | **中** | 缺乏 Zygote COW 页面共享；App AOT 暂未覆盖 Split APK 与动态插件 DEX |

---

## 四、分阶段演进路线

### 阶段 P0：工程消债与热路径止血（已完成）

- [x] 将散落在历史兼容实验目录中的活跃生产源码（`SdPendingIntents`、`SdManifestReceivers`、`audio-connection.hpp`）迁回标准目录。
- [x] 清理 700+ 个无引用的历史一次性调试脚本与 `baseline` 快照副本；将活跃源码路径从 `api29` 中性化为 `scripts/runtime/` 与 `native/compat/runtime-*`（保留设备端 `/home/art/api29-root` 与 `libsdhost29.so` 运行时兼容契约）。
- [x] 展开 [`sdwindow.c`](../native/window/sdwindow.c) 超长单行代码；全量缓存窗口/音频 JNI `jmethodID` 与 Direct `ByteBuffer` 引用；缓存 [`host-manager.cpp`](../native/host/host-manager.cpp) D-Bus 调用方凭据；复用 [`SdWindowSession.java`](../scripts/device/SdWindowSession.java) 窗口序与触控事件数组、惰性初始化 [`SdSurfaceStore.java`](../scripts/device/SdSurfaceStore.java) 合成画笔并缓存 [`SdApkPackage.java`](../scripts/device/SdApkPackage.java) 权限表。
- [x] 建立统一回归测试入口 [`tools/run-tests.py`](../tools/run-tests.py)（含隔离 D-Bus / PulseAudio / Weston Wayland 实装守护进程、`fakeroot` 打包属性夹具与 `qemu-aarch64-static` 跨架构验证）及 GitHub Actions 自动预检门禁。

### 阶段 P1：零拷贝媒体/WebView 管线与全面事件驱动（核心落地，持续演进）

- [x] **WebView P1a 共享内存双缓冲零管道传帧**：[`sdwebviewd.cpp`](../native/webview/qt-helper/sdwebviewd.cpp) 与 [`SdWebEngine.java`](../scripts/device/SdWebEngine.java) 改用 `0600` 共享内存双缓冲映射（`shm_rgba8888`）替代 `stdout` 管道传输 9~33 MB RGBA 像素，保留 `rgba8888` 自动回退能力。
- [ ] **WebView P1b GPU 零回读合成**：打通 `wpebackend-fdo` `EGLImage` / `zwp_linux_dmabuf_v1` 导入 Android `SurfaceTexture` 或挂载 `wl_subsurface`，彻底消除 `glReadPixels` CPU 回读并支持多实例共享网络进程。
- [x] **PulseAudio 长连接事件订阅与零轮询路由监控**：[`host-audio.cpp`](../native/host/host-audio.cpp) + [`SdAudio.java`](../scripts/device/SdAudio.java) 改为常驻 `pa_mainloop` + `pa_context_subscribe` 内存快照与 `awaitAudioRouteChange` 条件变量唤醒，消除每查询重连与 Java 端 2s 轮询。
- [x] **`HostManager1` 状态信号实时唤醒与广播并发池**：[`host-manager.cpp`](../native/host/host-manager.cpp) 广播 `StateChanged` 信号，[`host-entry.cpp`](../native/host/host-entry.cpp) 通过 GDBus 工作线程过滤器实时唤醒启动等待；[`SdManifestReceivers.java`](../scripts/device/SdManifestReceivers.java) 引入按目标进程分组串行的有界并发接收器线程池。
- [ ] **守护进程 `pidfd` 化与外围轮询收敛**：[`host-manager.cpp`](../native/host/host-manager.cpp) 采用 `pidfd_open` / cgroup 替代 250ms 定时器与 `/proc` 扫描；`SdThermal` 改为按监听器与前台状态按需采样。
- [x] **Camera1 零分配缓冲复用与行指针外提**：[`camera-host.cpp`](../native/media/droid-camera/camera-host.cpp) 复用每客户端事件/RGBA 缓冲并在 `0°` 常见路径外提 Y/UV 行指针与无分支饱和裁剪。
- [ ] **Camera1 P1b 硬件直通**：`memfd` 环形帧池 + GLES YUV 着色器（或 `libyuv` NEON）进一步卸载旋转转换。

### 阶段 P2：轻量系统守护进程、编译期服务 Stub 与类 Zygote 孵化

- [ ] **编译期 AIDL `Stub` 代码生成**：替换 26 个反射 `Proxy` 与 450 处字符串匹配分支，实现静态类型校验与 `O(1)` 事务码分派。
- [ ] **原生 `saildroid-system-daemon`**：下沉私有 Binder 注册表至轻量原生进程（替代完整 ART 的 `SdBinderRegistry`），集中维护持久化 APK 解析索引（`mmap` 只读共享）与跨应用 Intent / Provider / Broadcast 路由表，打通应用间分享与第三方登录。
- [ ] **`saildroid-zygote` 预热孵化与增量 AOT**：预装载 ART Boot Image、`bionic_translation` 与核心服务后 `fork()` 应用与子进程，大幅降低子进程冷启动延迟与多进程 PSS 内存；扩展 `dex2oat` 支持 Split APK 与共享库上下文自动编译。

### 阶段 P3：构建体系现代化与命名空间沙箱

- [ ] 引入 Meson / CMake + Ninja 管理 `native/` 增量交叉编译，全面清除历史脚本中的宿主机绝对路径硬编码。
- [ ] 将 [`scripts/runtime/core/`](../scripts/runtime/core/) 69 组覆盖层收敛为结构化上游补丁或单一模块。
- [ ] 基于 Linux User / Mount Namespace（或 `bubblewrap`）按应用隔离 `/home/art/data/<package>` 视图与会话总线访问权限。

---

## 五、核心性能验收基线目标

| 维度 | P0+P1 阶段目标 | P2 完成目标 |
|---|---|---|
| 大型应用冷启动首帧（TTFF） | 较基线缩短 25%~35% | **< 1.2 s** |
| 后台子进程（`:service`/`:receiver`）拉起耗时 | **< 250 ms** | **< 120 ms** |
| WebView 全屏滚动帧率 | P1a: 45+ fps / P1b: **稳定 60 fps** | 稳定 60 fps（多实例共享网络进程） |
| 相机 1080p 30fps 单帧 CPU 转换耗时 | **< 1.5 ms/帧** | **< 1.0 ms/帧** |
| 静置/后台挂起每秒无效唤醒次数 | **< 0.1 次/s** | 后台冻结趋近 **0 次/s** |
| 每新增子进程独享内存（USS/PSS 增量） | 下降 10~15 MB | **15 ~ 25 MB/进程** |
