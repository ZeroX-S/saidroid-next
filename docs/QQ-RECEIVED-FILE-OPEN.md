# QQ 接收文件打开时停在启动头像

2026-11-11 用户在聊天中点击收到的文件，页面切到 QQ 头像后长时间不动。
这不同于此前发送文件的选择器绘制故障，也不同于相册返回聊天的数据丢失。

## 根因

两次实机日志都显示 `FileBrowserActivityV2` 已提交启动事务，但没有完成
Activity 创建。`doOnCreate()` 为准备文件预览内核，发送显式广播给
`com.tencent.mobileqq.webprocess.WebProcessReceiver`：

- action：`action_download_tbs`
- 接收权限：`com.tencent.msg.permission.pushnotify`

宿主的普通 `broadcastIntent(Object[])` 把这条显式广播交给仅支持动态注册
接收器的 `deliverBroadcast()`。后者抛出
`UnsupportedOperationException: Manifest receivers unavailable`，异常经
`ContextImpl.sendBroadcast()` 回到文件页的 `doOnCreate()`，中断页面启动。
头像不是文件下载进度；这条异常不能证明文件本身损坏。

部署的运行时已经有 `SdManifestReceivers`，PendingIntent 广播也已连接它，
但普通 Context 广播入口缺少同样的显式分发分支。已有 Java overlay 参考
源码包含该分支，实际部署的 DEX 与其不一致。

## 修复

`scripts/api29/explicit-broadcast-dispatch-compat/patch.py` 只恢复普通广播
入口到既有 manifest-receiver 实现的连接，不吞异常或伪造接收成功。
完整保留结果、附加数据、接收权限与用户，继续使用既有接收器声明、启用
状态、包身份、权限和进程校验。显式广播不误投动态接收器；隐式广播仍走
原先的本地和跨进程路径。登录、文件选择器、照片返回聊天补丁保持不变。

此补丁不修改 QQ APK，不读或发送接收文件，不替代 QQ 的预览内核，也不
保证所有扩展名或文件内容均可预览。预览内核下载等后续功能需要单独观察。

## 验证与部署

```sh
JAVA_HOME=/path/to/jdk python3 scripts/api29/tests/test-explicit-broadcast-dispatch.py
```

测试覆盖窄范围 smali 修改、重复应用及未知布局拒绝，以及实际 Java 参考
方法的 10 种分发/拒绝情形。Java 测试使用受控接收器桩，不能代替实机的
跨进程接收验收。此前的登录等待、选择器硬件加速、相册页面复用回归亦通过。

构建记录位于 `build/qq-file-open-20261111-v1/`。ART DEX 结构校验通过，
只修改 `SdActivityManagerService.smali` 中的 `broadcastIntent`，保留 2759
个已有成员的访问标记和 hidden API 限制，无新增成员。部署需要 JAR、42
个匹配 boot-image 文件与 manifest 一起替换；旧版本备份支持整体回滚。

补丁已部署，运行时 SHA256 为
`b7ef6d6620700be13fc3272c2f5f21a03eacc0c2a455a9aae901f1297f27ae65`。
重启后 QQ 已绘制 Android Activity；映射核验显示 QQ、Binder 和 MSF 三个
进程均使用新 boot-image inode。记录位于该构建目录的
`boot-image/loaded-image-validation.json`。用户重试后证实文件详情页能出现，
但很快又回到头像：第一段修复生效，接收文件打开功能仍未验收通过。

如需回滚，以下命令会关闭相关进程并一起还原旧 JAR、镜像和 manifest，
不修改聊天或文件数据：

```sh
sudo -n python3 build/qq-file-open-20261111-v1/install-boot-image.py --restore
```

实机重试应看到 `FileBrowserActivityV2` 完成启动，不再出现上述异常。若
只有页面启动成功、而实际文件仍打不开，不能宣称预览功能已经验收通过。

## 文件页出现后 QQ 又退出

第二次实机日志中，文件 Activity 已完成创建，但广播工作线程调用
`HostApi.startReceiverProcess(String,String,String)` 抛出 `NoSuchMethodError`。
QQ 的未捕获异常处理器随即结束文件页和聊天页，退出码为 10。部署的 Java
HostApi 和 `libsdhostapi.so` 均没有这一接口，native launcher 也没有 receiver
启动路径；仅添加 Java native 声明会变成另一次链接错误。

同时检查接收端发现 `SdServiceEndpoint` 只支持事务 1–8，广播发送端却发送
事务 9。若只补进程启动，这条显式广播仍然无法交给接收器。

第二段修复位于 `scripts/api29/receiver-process-compat/`：

- 验证 QQ 的 receiver 声明和进程，使用同 APK、同进程中已声明且启用的
 真实 Provider 启动该进程。QQ 的 FileProvider 在 `:tool`，正常 Application
 绑定初始化该进程的 Provider 并发布 Binder 端点，不打开新 Activity。
- 使用既有 native provider API 和真实 Provider 名称，不把 receiver 伪装
 成 Provider，不修改 native caller-family、APK 或权限检查。
- 工作线程使用共享的存活 Binder、120 秒有界等待，并恢复中断标记；删除
 旧 DEX 中错误的 `uptime * 32767` 截止时间计算。
- 接收端在原 UID/interface-token 检查后处理事务 9，保留事务 8 的 Activity
 路由和编号。完整传递权限、用户和数据给既有 ManifestReceiver 校验及
 ActivityThread 分发，仅在调用成功后返回成功。

此方案是有条件的兼容路径：没有同进程启用 Provider 的 receiver 冷启动
仍明确拒绝，不声称新增了通用 native receiver 启动支持。

```sh
JAVA_HOME=/path/to/jdk python3 scripts/api29/tests/test-receiver-process.py
```

参考 Java 测试的 18 种情况及两个 smali 转换测试均通过；同时检查包、
进程、Provider 启用状态、UID、权限拒绝、Payload 保留与错误传播。测试用
受控桩，不替代 QQ 实机 receiver/预览内核验收。新 DEX 的 ART 结构校验
通过，保留全部 2759 个旧成员及限制，仅新增辅助类的 3 个成员。此前登录、
文件发送、照片发送及第一段广播路由补丁保持不变。

第二段构建、部署和备份目录为 `build/qq-file-open-20261111-v2/`，需与
42 个匹配镜像整体部署。对应回滚入口是该目录的
`install-boot-image.py --restore`，会恢复到第一段补丁版本，不修改聊天或
接收文件。最终还需观察 receiver 完成分发后 QQ 主进程继续存活、文件页
不再自动关闭；页面暂时出现不能算完整通过。

## 第二段部署与实机核验

第二段补丁部署时，`lib/runtime.jar` 的 SHA256 为
`be1f7e36df8b57a3cd59041af27e1bdded1fff59bbdce324c34a8dbfb8a3305e`。
JAR、42 个匹配 boot-image 文件及 manifest 已整体替换。全运行时引用的
15 个 HostApi 方法在 Java 声明和实际 native 导出中均存在；未替换 native
文件，未修改 QQ APK、聊天或接收文件数据。

2026-11-11 继续核验时，上一轮 QQ 与辅助进程已经退出，不能再把此前的
镜像映射记录当作当前存活证明。重新启动 QQ 后完成以下检查：

- QQ 已绘制 Android Activity，当前运行时 JAR 校验一致；随后再次核验
  QQ、Binder、MSF 与 `:tool` 四个进程映射的 boot-image inode。
- 使用 QQ 在 `:tool` 声明的真实 FileProvider 冷启动成功，发布进程 Binder
  后继续存活至少 10 秒，未启动 Activity、未打开接收文件。
- 独立 ART 客户端通过真实私有 Binder 调用事务 9，使用正确 interface
  token、故意错误的 caller package；接收端返回预期的
  `SecurityException: Receiver caller package differs`。探针没有发送 Intent
  或文件数据，只证明事务已接通且身份拒绝生效，不证明真实广播完成分发。
- 参考 Java 的 18 种场景和两个 smali 转换测试重新通过；补丁差异检查
  `git diff --check` 通过。

实机记录位于第二段构建目录的 `boot-image/loaded-image-validation.json`、
`boot-image/provider-bootstrap-validation.json` 和
`boot-image/receiver-endpoint-validation.json`。接收文件页面能否持续显示及
实际文件能否打开，仍需用户重新点击接收文件确认；这些检查不能替代文件
预览内核及真实接收器分发的最终验收。

## 已下载、打开应用与转发的后续反馈

2026-11-11 用户重试后反馈文件页显示“已下载”，但打开应用列表只有 QQ
浏览器，且不能转发。新日志中 `FileBrowserActivityV2` 已完成启动，`:tool`
的 `WebProcessReceiver` 已排队并完成广播，未出现先前两个致命错误。这
证明先前的页面启动及广播分发阻断已解除，不代表外部打开或转发已通过。

实机目录元数据确认下载文件位于：

```text
/home/art/data/shared/Android/data/com.tencent.mobileqq/Tencent/QQfile_recv/
```

这是宿主 `EXTERNAL_STORAGE=/home/art/data/shared` 下的 QQ 接收目录，不是
Sailfish 用户的 `~/Downloads`。该目录也存在 QQ 自建的缓存子目录；不要
为方便导出而递归复制全部内容或把缓存误当作收到的文件。本轮只检查目录
和文件元数据，没有读取、打开、复制或转发下载文件。

部署的 `SdApkPackage.resolveActivities` 对文件打开 Intent 只查询当前
APK 的 Activity 声明，没有把 Sailfish 原生文件处理程序接到这个列表。
因此可选应用过少是当前打开应用解析的兼容范围，不能据此判断文件没有
保存。未添加虚假的处理程序，也未调用外部程序打开用户文件。

转发方面，当前主进程日志只有文件页的启动记录，没有
`ForwardRecentActivity` 或其他新的联系人选择页启动记录，也没有能直接
定位转发失败的宿主异常。静态检查显示文件页有分享面板和后续转发路径，
仍需区分“点转发没有反应”“无法选择联系人”和“选择后发送失败”，不能
把没有异常或没有 Activity 启动误写为转发已经修复。

联系人选择后的后续排查发现宿主把非聚焦弹窗的触摸误投给下层 Activity。
窄范围修复、后续部署版本及验收限制记录在 `docs/QQ-FILE-FORWARD.md`；
新的弹窗补丁保留本文的两段接收文件修复。
