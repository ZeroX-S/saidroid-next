# SaiDroid Next

Sailfish OS 上的独立 ART / Android 9（API 28）兼容运行时。Android 应用分别运行在普通用户进程中，通过原生 Wayland 窗口、输入、服务适配和 bionic 兼容层接入 Sailfish。

这是独立 ART 路线，与旧的容器后端项目不同。当前为实验性开发版本，仅维护 Android 9（API 28）运行时目标。

## 下载与安装

- [开发版安装包与校验文件](https://github.com/ZeroX-S/saidroid-next/releases)
- [安装、激活与回退说明](docs/INSTALL.md)
- [当前验证范围与已知问题](docs/STATUS.md)

RPM 的最低宿主依赖包括 glibc 2.38、libstdc++ 13.2、Qt 5、Wayland、EGL/GLES、PulseAudio、GStreamer 和 Python 3.9。系统版本号本身不足以确认兼容性；本包面向已具备项目 ART/Binder 基础环境的 aarch64 Sailfish OS 测试设备。

本包不包含 QQ、微信、小红书、知乎或其他商业应用 APK、账号数据、用户签名密钥及应用 AOT 缓存。

### WPE WebView 依赖

启用 WPE WebView 的运行时需要安装以下 aarch64 软件包。RPM 使用 `>=` 声明版本下限，下限取自随包的 `share/build/webview-runtime-20261109/runtime-manifest.json`。

| 软件包 | 最低版本 |
| --- | --- |
| libepoxy | 1.5.11-768.1 |
| libwpe | 1.17.0-768.1 |
| wpebackend-fdo | 1.17.0-768.1 |
| wpewebkit2 | 2.54.2-768.1 |
| wpewebkit2-qt5 | 2.54.2-768.1 |

这些软件包由 Atlantic Engine 仓库提供。手动下载时，从 aarch64 下载目录选择达到上述版本下限的五个 RPM。仓库持续更新构建号，较新的构建也满足对应的最低版本要求。[aarch64 下载目录](https://specsierra.github.io/atlantic-engine/aarch64/) · [软件源配置](https://specsierra.github.io/atlantic-engine/atlantic-ci.repo) · [上游项目](https://github.com/SpecSierra/atlantic-engine)

也可以在设备上以 root 身份添加软件源并安装依赖。

```sh
rpm --import https://specsierra.github.io/atlantic-engine/RPM-GPG-KEY-atlantic-ci
zypper ar -f https://specsierra.github.io/atlantic-engine/atlantic-ci.repo
zypper ref atlantic-ci
zypper in libepoxy libwpe wpebackend-fdo wpewebkit2 wpewebkit2-qt5
```

软件源公钥的完整指纹为 `A6CCF45E59F159B687BF268C5AE893A84F8F9C4B`。手动下载的 RPM 可与 SailDroid RPM 一起通过 `zypper in` 安装，所需版本由包管理器检查。

## 当前状态

主线已收敛至 Android 9（API 28）兼容运行时，包含框架与 SDK 公共成员恢复、JNI 与跨进程组件（Activity / Service / Provider / ManifestReceiver）管理、Wayland 显示事件与全屏/平板视口适配、Atlantic/WPE WebView 恢复、PulseAudio 麦克风及 RTP/SIP 语音支持、本地只读文件选择器，以及 QQ 登录等待、相册回传聊天、接收文件显式广播与非聚焦弹窗触摸路由修复。

完整应用内长时稳定性、微信服务号/小程序端到端验收及完整 CTS 仍待在目标设备上持续验证。

## 源码

```text
native/                 原生宿主、兼容层、窗口、输入、媒体、RTP 与 WebView
scripts/device/         Java 运行时与系统服务适配
scripts/api28/          API 28 框架、SDK 公共成员、SIP/RTP 与原生加载器构建工具
scripts/runtime/        共享核心覆盖层、组件打包与回归用例（目标固定为 API 28）
scripts/compat/         JNI、服务路由、SDK 覆盖率与打包 ART 预检工具
scripts/packaging/      版本隔离 RPM、Binder 配置、激活和回退工具
scripts/cts/            CTS 执行与统计工具
scripts/perf/           性能与窗口回归工具
third_party/            固定版本的上游 Git 子模块
patches/third-party/    上游依赖的本地改动
```

构建流程与依赖说明见 [docs/BUILD.md](docs/BUILD.md)，端口与兼容性回归测试见 [docs/TESTING-PORT-COMPATIBILITY.md](docs/TESTING-PORT-COMPATIBILITY.md)，架构演进路线与分阶段实操手册见 [docs/ROADMAP.md](docs/ROADMAP.md) 及 [docs/OPTIMIZATION-HANDBOOK.md](docs/OPTIMIZATION-HANDBOOK.md)。

## 许可

项目原创代码采用 Apache-2.0。已有上游代码和衍生文件继续遵循各自的文件头、LICENSE 和 NOTICE，包括 Apache、BSD/MIT、GPL Classpath exception 及 LGPL 等许可。[第三方来源与许可说明](THIRD-PARTY.md)。根目录许可证不替代这些上游许可。
