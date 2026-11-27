# 源码与构建

本仓库维护面向 Sailfish OS（aarch64）的 Android 9（API 28）独立 ART 兼容运行时源码、固定上游依赖与兼容性检查工具链。不再支持构建或打包 API 29 运行时目标。

## 获取源码

```sh
git clone --recurse-submodules https://github.com/ZeroX-S/saidroid-next.git
cd saidroid-next
python3 tools/apply-third-party-patches.py
```

依赖 URL、精确提交和补丁 SHA-256 见 `third-party-sources.json`。补丁应用工具先检查所有子模块都处于固定提交及干净状态，再应用已校验的补丁；重复运行会拒绝已改动的子模块。上游项目的许可文本位于子模块和 `LICENSES/`。

## API 28 构建与预检入口

完整产物编译与原生打包面向 aarch64 Linux 环境；源码级 Java / D8 / JNI / 服务分派预检也可在具备 JDK 21 与 `aidl` 的 x86_64 Linux 主机上直接执行。

主要入口：

- `scripts/runtime/fetch-inputs.py INPUTS [--skip-sysimg]`：下载并校验固定 Android API 28 系统镜像、Robolectric 框架 JAR、独立 ART 核心依赖参考 JAR 及 R8 编译器。
- `scripts/api28/build-framework-source.py` / `scripts/runtime/build-framework.py`：准备并编译 API 28 框架 DEX。
- `scripts/runtime/build-product.py INPUTS OUTPUT [--compat-only]`：构建 API 28 Java 运行时（含 SIP/RTP 引用层）、执行源码兼容性预检，并编译原生宿主组件。
- `scripts/compat/run-preflight.py`：汇总 API 28 公开 SDK 成员、JNI 字面量描述符、服务分派路由、ELF 依赖及打包 ART 契约检查（详见 `scripts/compat/README.md`）。
- `scripts/packaging/README.md` / `scripts/packaging/build-runtime-rpm-vm.py --help`：版本隔离、核心链接器核对、清单封签、RPM 打包与激活流程。

## macOS（Apple Silicon）原生 aarch64 Linux 容器编译环境

在 Apple Silicon Mac（macOS 26+，已安装 Apple `container` CLI；也自动兼容 Docker / Podman）上，可直接用内置脚本基于 [`tools/Containerfile.dev`](../tools/Containerfile.dev) 拉起原生 `linux/arm64`（`aarch64`）Ubuntu 24.04 编译测试环境：

```sh
bash tools/macos-container-env.sh setup          # 构建 arm64 镜像、初始化子模块/补丁并拉取 API 28 依赖
bash tools/macos-container-env.sh test           # 在原生 aarch64 Linux 容器内运行全套 38 项回归测试
bash tools/macos-container-env.sh build-native   # 编译 API 28 runtime.jar 与原生 aarch64 .so 产物至 build/out-aarch64
bash tools/macos-container-env.sh shell          # 进入容器交互式编译终端
```

商业 APK、设备数据、签名密钥和应用 AOT 缓存不在仓库中；签名相关脚本读取调用者自行准备的私有密钥目录。
