# SaiDroid Next

Sailfish OS 上的独立 ART / Android 10（API 29）兼容运行时。Android 应用分别运行在普通用户进程中，通过原生 Wayland 窗口、输入、服务适配和 bionic 兼容层接入 Sailfish。

这是独立 ART 路线，与旧的容器后端项目不同。当前为实验性开发版本。

## 下载与安装

- [开发版安装包与校验文件](https://github.com/ZeroX-S/saidroid-next/releases)
- [安装、激活与回退说明](docs/INSTALL.md)
- [当前验证范围与已知问题](docs/STATUS.md)

当前发布 `r321o`：aarch64 RPM `0.321.15-1`。已验证设备环境为 Pixel 3a XL / Sailfish OS 5.2.0.16，设备上的 glibc 为 2.41。RPM 的最低依赖包括 glibc 2.38、libstdc++ 13.2、Qt 5、Wayland、EGL/GLES、GStreamer 和 Python 3.9。系统版本号本身不足以确认兼容性；本包面向已具备项目 ART/Binder 基础环境的测试设备，尚未提供新设备的全量自动配置。

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

此前 r321n 在 2026-11-06 的四应用可见启动采集通过，QQ、微信、小红书、知乎各取得两张新帧，并验证前台进程和窗口焦点。微信、小红书处于未登录欢迎页；这不代表登录后功能已通过。

两轮后台返回测试在知乎启动准备阶段被进程身份审计拒绝，实际未发出切换手势。知乎间歇性窗口焦点问题、应用内完整功能、长时稳定性和完整 CTS 仍待完成。50% 性能目标暂缓，暂无达到该目标的声明。

当前 r321o 修复了未申请 `ACCESS_NETWORK_STATE` 的应用在公共启动阶段被代理查询错误拒绝的问题；安装程序、计算器不再需要凭空增加网络权限。离屏 ART 回归复现旧错误并验证修复，8 项网络状态/回调操作仍保留权限检查。修复包已安装、激活并完成普通重启。新会话中，安装程序和计算器均已创建真实窗口、呈现首帧并接收触摸；日志包含应用处理证据，且无原启动权限异常，`rpm -V` 无差异。本次从用户已打开的实例采证，没有将复用实例记作冷启动通过，也没有完成新的截图或完整计算功能测试。

## 源码

```text
native/                 原生宿主、兼容层、窗口、输入、媒体与 WebView
scripts/device/         Java 运行时与系统服务适配
scripts/api29/          API29 构建、兼容补丁与用例
scripts/packaging/      版本隔离 RPM、显式激活和回退工具
scripts/cts/            CTS 执行与统计工具
scripts/perf/           性能与窗口回归工具
third_party/            固定版本的上游 Git 子模块
patches/third-party/    上游依赖的本地改动
releases/r321o/         已编译版本的随包源码与来源记录
```

[构建与依赖说明](docs/BUILD.md)。工作源码包含本地尚未提交的开发修改；`releases/r321o/compiled-source` 单独保存已编译版本的源码来源。两者不能混称为同一个可复现构建结果。`SOURCE-SNAPSHOT.json` 逐项记录原始与公开源码哈希及认证默认值替换。

这是首次公开源码快照，尚未验证从空环境一键重建整个 r321o。历史开发脚本保留了 VM 路径和设备别名；执行前需配置自己的环境。

## 许可

项目原创代码采用 Apache-2.0。已有上游代码和衍生文件继续遵循各自的文件头、LICENSE 和 NOTICE，包括 Apache、BSD/MIT、GPL Classpath exception 及 LGPL 等许可。[第三方来源与许可说明](THIRD-PARTY.md)。根目录许可证不替代这些上游许可。
