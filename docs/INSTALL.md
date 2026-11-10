# 安装开发版 RPM

API28/API29 完整运行时并存、预览、冷切换和回滚见
[多 API 运行时说明](MULTI-API-RUNTIMES.md)。切换入口只选择已有完整 release；
不会把下面的 API29 发布包转换成 API28。

发布包是 aarch64 独立运行时，不是 Android 系统镜像。已验证环境：Pixel 3a XL、Sailfish OS 5.2.0.16、glibc 2.41。当前包需要已有的项目 ART/Binder 基础环境、普通用户 `defaultuser` 及其 Wayland / D-Bus 会话。其他设备和全新系统的自动配置尚未验证。

## 1. 核对包和依赖

从同一 Release 下载 RPM 与 `SHA256SUMS`，在保存文件的目录执行：

```sh
sha256sum -c SHA256SUMS
rpm -qp --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' saildroid-runtime-api29-r321o-dev-20261106-0.321.15-1.aarch64.rpm
rpm -qpR saildroid-runtime-api29-r321o-dev-20261106-0.321.15-1.aarch64.rpm
```

包需要 glibc >= 2.38、libstdc++ >= 13.2、Python >= 3.9，以及 Qt 5 / Wayland / EGL / GStreamer 等宿主依赖。缺失依赖时先处理平台适配；不要使用 `--nodeps` 或直接替换系统 libc。WebView 还依赖目标平台的 Qt/WPE 集成，不能从静态依赖完整性推导其功能可用。

## 2. 安装与显式激活

先正常关闭所有 SailDroid 应用和管理器，停止正在进行的开发测试。已有安装的设备尤其需要在 RPM 更新前退出所有相关进程，避免覆盖运行中的版本目录。

通过 Sailfish 的 `devel-su` 进入 root shell，然后执行：

```sh
rpm -Uvh saildroid-runtime-api29-r321o-dev-20261106-0.321.15-1.aarch64.rpm
rpm -V saildroid-runtime-api29-r321o-dev-20261106
python3 /opt/saildroid/releases/api29-r321o-dev-20261106/bin/saildroid-setup status
python3 /opt/saildroid/releases/api29-r321o-dev-20261106/bin/saildroid-setup activate api29-r321o-dev-20261106
reboot
```

`rpm -V` 预期无输出。RPM 没有安装脚本，不会自行激活、启动应用或编译应用缓存。显式激活会核对完整性、准备兼容存储、切换 `/home/art/api29-root` 并通过真实应用注册表刷新入口；它不会安装商业 APK。

更新后完成普通重启和手机解锁，先确认桌面触摸、滑动正常，再测试应用。保留先前可用版本供回退。包中唯一文件 capability 是原生 bootstrap 的 `cap_sys_resource=ep`，应用宿主不会以 root 身份运行。

`r321o` 使用新的隔离版本目录，与旧 `r321n` 并存；包含公共启动代理查询权限修复及匹配的启动镜像，且去除了随包开发脚本的内置认证默认值。

## 3. 回退或恢复中断的激活

正常关闭 SailDroid 应用和管理器后，以 root 执行所安装版本的 helper：

```sh
python3 /opt/saildroid/releases/api29-r321o-dev-20261106/bin/saildroid-setup rollback
reboot
```

如果激活事务被中断，使用 `recover` 恢复事务后再检查 `status`。回退保留 APK 和应用数据；它不会凭空安装缺少的旧版本。若此前部署了与旧运行时绑定的应用 AOT 缓存，必须同步恢复对应缓存，或使用工具重新生成；本次开发设备的旧缓存保存在本地备份中，不在发行 RPM 内。运行时与应用缓存的输入哈希必须匹配，不要将新旧版本的缓存混用。

## 4. 非 1080x2160 屏幕与 Android 9 底包

启动器会优先读取宿主 Wayland 输出尺寸；无法读取时回退到已验证的 1080x2160（Pixel 3a XL / bonito）。其他面板也可以在启动应用前显式设置以下环境变量（可写入用户会话的 `~/.config/environment.d/saildroid.conf`）：

```sh
SAILDROID_DISPLAY_WIDTH=1080
SAILDROID_DISPLAY_HEIGHT=2340
```

Android 9（API 28）底包上 `libsdhost29.so` 会把 ART 自带的 `libjavacore.so`/`libopenjdk*.so` 交给 glibc 加载，以匹配随包发布的 Java 核心。WebView 的 Qt/WPE 宿主限制为宽 2160、高 4096、RGBA 帧 9 MiB。初始加载和窗口调整使用同一尺寸预算，超限时按比例缩小；触摸坐标按实际视图与宿主视口尺寸换算，已在预算内的视口保持原尺寸。

机型/厂商等公开身份不是运行时写死的：`scripts/api29/capture-hardware-identity-phone.py` 在目标机上抓取公开字段，打包时经 `package-component.py --hardware-profile` 写入组件 `build.prop`，同时保存身份配置、解析结果和别名表用于追溯。Sailfish 硬件 ID 与 Android 底包 `ro.product.device` 不一致的端口在 `scripts/api29/hardware-identity-aliases.json` 登记别名（如 `fajita → OnePlus6T`）。指定配置但无法确认一致身份时打包报错；未指定配置时保留编译期默认值。

## 开发认证

设备脚本默认使用 SSH 别名 `bonito`。自行配置 SSH 密钥，或在执行需要 `sshpass` 的历史开发脚本前提供环境变量 `SSHPASS`。公开源码和公开修订包都不携带调试密码或签名私钥。
