# 安装开发版 RPM

发布包是面向 Sailfish OS 的 aarch64 独立 Android 9（API 28）运行时，不是 Android 系统镜像。当前仅支持 API 28 运行时包，需要普通用户 `defaultuser` 及其活跃的 Wayland / D-Bus 会话。

## 1. 核对包和依赖

从对应 Release 下载 RPM 与 `SHA256SUMS`，在保存文件的目录执行：

```sh
sha256sum -c SHA256SUMS
rpm -qp --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' saildroid-runtime-api28-<release>.aarch64.rpm
rpm -qpR saildroid-runtime-api28-<release>.aarch64.rpm
```

包需要 glibc >= 2.38、libstdc++ >= 13.2、Python >= 3.9，以及 Qt 5 / Wayland / EGL / PulseAudio / GStreamer 等宿主依赖；启用 WPE WebView 时还要求 Atlantic Engine 的最低版本组件（见根目录 `README.md`）。缺失依赖时先处理平台适配；不要使用 `--nodeps` 或直接替换系统 libc。

## 2. 安装与激活

先正常关闭所有 SailDroid 应用和管理器。已有安装的设备尤其需要在更新前退出所有相关进程。

通过 Sailfish 的 `devel-su` 进入 root shell 后安装并校验：

```sh
rpm -Uvh saildroid-runtime-api28-<release>.aarch64.rpm
rpm -V saildroid-runtime-api28-<release-id>
python3 /opt/saildroid/releases/<release-id>/bin/saildroid-setup status
```

若软件包采用显式激活策略（无自动激活脚本），或需要手动切换到指定已安装版本，执行：

```sh
python3 /opt/saildroid/releases/<release-id>/bin/saildroid-setup activate <release-id>
```

若软件包在封签的 `runtime.json` 中声明了 `saildroid-rpm-activation-v1`（`posttrans` 模式），RPM 仅包含固定的 `%pre`（检查任意已安装版本无运行中的 SailDroid 进程）与 `%posttrans`（调用该版本的 `saildroid-setup activate`）脚本，由 `saildroid-setup` 精确核对脚本内容。激活会校验完整性、配置私有 Binder（`binderfs` 或受信任的 `/dev/anbox-binder`、`/dev/puddlejumper` 节点）、原子切换兼容运行根链接 `/home/art/api29-root` 并通过真实应用注册表刷新桌面入口。

包中唯一带文件 capability 的可执行文件是原生 bootstrap `libexec/saildroid-app`（`cap_dac_override,cap_sys_resource=ep`，用于在 `0400` 权限内核上重置继承自桌面会话的 `oom_score_adj` 并设置 `RLIMIT_NICE=40`，随后在 `exec` 无特权宿主前清空全部 capability 并启用 `no_new_privs`）。应用宿主不会以 root 身份运行。

## 3. 回退或恢复中断的激活

正常关闭 SailDroid 应用和管理器后，以 root 执行所安装版本的 helper：

```sh
python3 /opt/saildroid/releases/<release-id>/bin/saildroid-setup rollback
```

如果激活事务被中断，使用 `recover` 恢复事务后再检查 `status`。回退保留 APK 和应用数据。若部署了与特定运行时绑定的应用 AOT 缓存，必须确保运行时与应用缓存的输入哈希匹配，不要混用不同版本的缓存。

## 4. 显示尺寸、底包链接与硬件身份

启动器会优先读取宿主 Wayland 输出尺寸；无法读取时回退到 1080x2160。其他面板可在启动应用前显式设置环境变量（可写入 `~/.config/environment.d/saildroid.conf`）：

```sh
SAILDROID_DISPLAY_WIDTH=1080
SAILDROID_DISPLAY_HEIGHT=2340
```

Android 9（API 28）底包上 `libsdhost29.so` 会把 ART 自带的 `libjavacore.so`/`libopenjdk*.so` 交给 glibc 加载，以匹配随包发布的 Java 核心。WebView 的 Qt/WPE 宿主视口上限为宽 2160、高 4096（RGBA 帧预算 33.75 MiB），超限时按比例缩放并换算触摸坐标。

机型/厂商等公开身份由 `scripts/runtime/capture-hardware-identity-phone.py` 在目标机抓取，打包时经 `package-component.py --hardware-profile` 写入组件 `build.prop`（端口别名登记在 `scripts/runtime/hardware-identity-aliases.json`）。

## 开发认证

远程与设备测试脚本从环境变量（如 `SSHPASS` 或 `SAILDROID_TEST_PASSWORD`）读取认证凭据，或使用 SSH 密钥。公开源码和安装包均不携带调试密码或签名私钥。
