# Android compatibility checks

## 构建与 ARM64 Linux 预检

`run-preflight.py` 将 JNI 签名、服务分派、APK 引用和打包 ART 契约测试汇总到一次检查中。
`run-remote.py` 从 Windows 上传当前源码快照和已打包运行时，在 ARM64 Linux 上执行检查，下载报告与日志。
源码快照包含工作区中的修改，输入文件和执行使用的 JAR 都记录 SHA-256。

| 检查 | 产出 | 构建判定 |
| --- | --- | --- |
| API28 公开 SDK | 官方 revision 6 的 65,961 个公开或受保护成员、缺失类与成员、访问权限 | 缺失成员或访问权限不符导致失败 |
| JNI 字面量类、字段、方法和注册表 | 完整描述符、继承解析、静态与实例标识、native 声明 | 确定的缺失或签名错误导致失败 |
| 服务接口与分派路径 | 每个接口签名及分派来源、未覆盖项、委托路由错误 | 已声明操作与实际分派脱节导致失败 |
| APK Java 与 DEX 引用 | 类型及成员缺口、重复类、输入哈希 | 生成待执行验证的候选清单 |
| ARM64 ELF 依赖 | DT_NEEDED、符号候选缺口、弱符号、实际扫描的提供库 | 生成静态候选清单 |
| 打包 ART | 86 个固定 AOSP libcore 用例、六组平台契约及 API28 的三组公开 API 契约、JDK 结果对照 | 用例、启动、输入完整性或清理失败导致失败 |

JNI 动态名称、宏展开和 SDK 条件分支进入明确的待解析列表。C 函数原型 ABI、ELF 符号版本、
命名空间可见性与动态加载由编译和运行时验证补充。服务分派存在性与行为测试分别记录。

### 测试环境

已验证的服务器为 `192.168.3.205`，测试工作区为 `/home/ubuntu/saildroid-compat`。
需要 ARM64 Linux、Python 3.12 以上、JDK、bubblewrap、Weston、aapt、readelf、sudo 和 Binder 内核模块。
Windows 远程入口需要 Python 与 Paramiko，SSH 密码从 `SAILDROID_TEST_PASSWORD` 环境变量读取。

服务器依赖可由有 sudo 权限的用户安装。

```sh
sudo apt-get install openjdk-17-jdk bubblewrap weston aapt binutils gcc g++
```

运行器使用 UID 65534，在私有 PID、网络和挂载环境中映射运行时原安装路径、字体和资源。
每次执行创建独立 BinderFS 和 headless Weston，结束时卸载 BinderFS、停止 compositor 并删除带标记的夹具目录。
原始运行时文件在执行前后逐项比对哈希，结果包含清理状态。

### 从 Windows 执行

在仓库根目录运行以下命令。SSH 密码环境变量准备好后，命令会完成上传、执行和结果下载。
主机指纹处理由 `--ignore-host-key` 控制，此选项适用于本次指定的测试连接。

```powershell
python scripts/compat/run-remote.py `
  --host 192.168.3.205 --user ubuntu --ignore-host-key `
  --payload ../artifacts/compat-install-20261115/sdk-package/saildroid-runtime-api28-r323m-dev-20261114/rpm/payload.tar `
  --framework "$env:TEMP/saildroid-api28-20261107/inputs/android-all-9-robolectric-4913185-2.jar" `
  --r8 "$env:TEMP/saildroid-api28-20261107/inputs/r8-8.3.37.jar" `
  --label compatibility-new-run `
  --output ../artifacts/compatibility-new-run
```

追加 `--apk` 可扫描一个或多个 APK。回归对照使用完整的历史 `payload.tar`，让 runtime.jar 与对应的
ART boot image 链一起执行。运行记录包含 boot ART/OAT/VDEX 文件的哈希，结束时再次校验。
`--prepare-only` 准备并校验输入，生成 `remote-inputs.json`。
重复执行时使用新的运行标签和输出目录，经过哈希校验的输入缓存会复用，损坏的上传缓存会重新传输。

### 服务器上的直接入口

`remote-inputs.json` 记录可直接复用的运行时、framework 和 R8 路径。

```sh
python3 scripts/compat/run-preflight.py \
  --runtime-root "$runtime" --framework "$framework" --r8 "$r8" \
  --output "$output" --headless --elf --apk "$apk"
```

参数变量使用记录中的实际路径。framework 固定为 API28 或 API29 对应的已校验输入，
执行侧使用选定包中的 ART、boot JAR 和 native 库。参考侧使用主机 JDK 执行相同的未修改 AOSP libcore 测试，
结果对照范围为这 86 个用例。

平台契约覆盖 Activity 任务 ID、注册与销毁、并发查询、任务后台请求路由、窗口 JNI、应用 Parcelable 交付、Bitmap 构造签名和接收器 JNI。
Intent 用例在隔离进程中预置 Activity 和 ActivityThread，调用实际 `SdActivityHost.launch` 复用分支，
并验证错误类加载器触发异常、正确交付保留应用对象。任务后台路由用例验证无效 token 到达实现后的异常行为。
接收器用例验证 Binder 调用者包名、JNI 导出入口、已声明进程的选择及未声明进程拒绝行为。
Sailfish 窗口呈现、触摸、键盘和硬件交互在真机验证阶段完成。

### 构建入口

`scripts/api29/build-product.py` 在 Java 和 D8 完成后自动调用源码 JNI 与服务路由检查，检查失败会阻断后续构建。
`--api 28` 选择当前 API28 分支的编译基线，默认选择 API29。
源码目录清单集中在 `product_sources.py`，编译与审计共用设备代码、广播、PendingIntent、媒体与摄像头目录。
`java-sources.json` 记录显式及依赖发现的实际 Java 输入。

快速检查 Java、D8 和源码接口时使用以下形式。

```sh
python3 scripts/api29/build-product.py "$inputs" "$output" \
  --api 28 --framework "$framework" --r8 "$r8" --compat-only \
  --compat-core "$core_oj" --compat-core "$core_libart"
```

`--compat-core` 接受实际 standalone core 的 JAR 或 class 目录。省略 core 提供库时，源码模式会将缺少的
core 类标记为 `provider-not-supplied`，打包模式会校验完整 boot classpath。
源码编译失败的信息保存在 `javac.log`，此阶段也能提前暴露跨模块接口不一致。

同一个构建入口也可直接检查已经打包的运行时。

```sh
python3 scripts/api29/build-product.py "$inputs" "$output" \
  --framework "$framework" --r8 "$r8" \
  --compat-only --compat-runtime-root "$runtime"
```

### 补齐 API28 的 185 个 SDK 成员

`scripts/api28/build-public-api.py` 针对缺少 185 个成员的 API28 基线执行受限合并。
`public-api-compat/sources.json` 锁定 Android 9 r61 的 SIP/RTP Java 与 AIDL 源码、两个操作码常量，
以及 Google API28 arm64 r02 镜像中的 `librtp_jni.so` 和 `libstagefright_amrnb_common.so`。
构建输入包含已打包运行时、固定 framework/R8 和两份本地库，需要 JDK、aidl 与 dexlib2/baksmali。

```sh
sudo apt-get install aidl libsmali-java
python3 scripts/api28/build-public-api.py \
  --runtime-root "$runtime" --framework "$framework" --r8 "$r8" \
  --android-libs "$native_inputs" --output "$public_api_output" \
  --dexlib-classpath '/usr/share/java/*'
```

输出包含合并后的 `core-libart.jar`、`framework28-classes4.jar`、两份本地库、私有 linker 映射和 `build-result.json`。
构建逐项比对原有成员限制和反汇编内容，在现有 `Opcodes` 类中追加两个字段，并检查全部 65,961 个 SDK 成员。
将输出合入 staging 后，需要重建相同 boot classpath 的 42 份 ART/OAT/VDEX 文件，更新 boot/hidden-API 构建记录并重新封装激活清单。
运行时的 `api28_public_api.native_libraries` 记录新增本地库的相对路径与哈希，供执行前后完整性检查使用。

API28 的 `api28-public-members`、`sip-profile` 和 `rtp-jni` 契约分别检查全部 185 项的应用侧反射访问，
SIP 配置、Parcelable、参数验证和来电 Intent，以及实际 RTP UDP 端口绑定、释放与编码格式选择。
SIP 注册、通话服务和 RTP 音频交换需要端到端运行验证。

### 报告与扩展

远程入口的 `results/report.md` 给出检查摘要，`results/result.json` 给出机器可读判定。
`sdk-coverage.json`、`jni-contracts.json`、`service-coverage.json`、`application-linkage.json` 和 `native-linkage.json` 保存完整清单。
`headless/` 保存各组 ART 日志、JDK 日志、执行输入、夹具 APK 和清理结果。
检查失败时远程入口仍会收集结果，`remote-run.json` 记录退出状态及下载问题。

运行以下命令验证扫描器和快照回归用例。

```sh
python3 -m unittest discover -s scripts/compat/tests -v
```

扩展 ART 契约时，在 `headless/RuntimeContracts.java` 添加对实际实现的测试，并在 `headless_art.py` 注册测试组。
应用代码保留在应用 classloader 中，boot 侧测试桥只暴露一个编码后的入口。
AOSP 测试以规范 LF 字节校验官方哈希，并在临时目录编译规范副本。

## API29 device regression

This is a focused device regression for the independent ART implementation. It
is not the Android CTS/VTS runner and does not establish Android certification.

The signed temporary APK runs four **unmodified** AOSP libcore test classes with
JUnit 3: CRC32, Adler32, reflection Array, and Integer (86 tests). The vendored
files retain their Apache headers; `upstream/manifest.json` pins Android
10 r47's commit, original paths, and SHA-256 hashes. The builder verifies these
hashes before compiling. `upstream/LICENSE` contains Apache License 2.0.

Another 23 public-API contract groups exercise Parcel, Bundle, Intent, Uri,
Base64, JSON, resources/density, app identity/classloading, private files,
SharedPreferences, SQLite bind/rollback/blob/null behavior, main/worker Handlers,
monotonic time, executor error propagation, SHA-256, ZIP and CookieManager.
The tests run inside the real signed APK process, not Robolectric or host Java.
`android-all` is the compile/framework input; device execution uses independent ART.

The serial suite also checks physical input and real page pixels for the
WebView Java bridge/navigation flow, native WebKit headers/cookies/redirects/
popups/POST, HWUI click/dialog and two Cover cycles, resumed static pixels,
background CPU, and a controlled scrolling workload. Each device transaction
holds `scripts/devlock.sh`, checks Wayland responsiveness and returns the screen
to brightness 0. Pure API and native WebView tests never wake it.

Build inside `MeeGo Build` using the repository's existing toolchain and signing
key. The staged component must already contain the matching product build.

```sh
python3 scripts/compat/build-apk-vm.py unique-apk-tag
# The WebView flow uses its own signed VerificationProbeActivity APK.
python3 native/webview/qt-helper/build-probe-apk-vm.py r86-verification2 VerificationProbeActivity
# Existing HWUI/scroll probes are prerequisites (see native/hwui/README.md).
bash scripts/compat/run-suite-vm.sh unique-run api29-staged-release unique-apk-tag
```

Set `SD_WEBVIEW_APK_TAG` to a different built WebView APK tag when rerunning.
Evidence is saved beneath `build/compat/`, `build/hwui/` and
`build/qq-startup-webview/`. Temporary app records have no desktop entries. The
runners restore the previous component; selecting a new default is a separate
verified deployment transaction. The one-page result and known unsupported APIs
are recorded in `docs/ANDROID-COMPATIBILITY-2026-10-29.md`.
