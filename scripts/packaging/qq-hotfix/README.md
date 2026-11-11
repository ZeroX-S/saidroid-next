# SailDroid QQ 修复 RPM（2026-11-11）

适用于 `saildroid-runtime-api28-r323k-dev-20261110-0.321.62-69.aarch64` 的
未修改运行时。其他版本或未知热补丁会被拒绝，不能强制覆盖。当前已修复
运行时可重复执行 `check`、`apply` 和 `verify`，不会重复备份。

包括登录等待、文件选择器、照片返回聊天、显式广播、接收文件进程启动及
非聚焦弹窗触摸修复；本机用户已确认文件转发及撤回成功。RPM 包含 runtime
JAR、42 个匹配 `.art/.oat/.vdex`、镜像清单及安全安装工具，不含 QQ APK、
聊天数据、下载文件或调试日志。

## 安装与启用

安装 RPM **只暂存补丁，不自动启用**，避免安装时突然关闭正在运行的应用。
从终端执行：

```sh
devel-su rpm -Uvh saildroid-qq-hotfix-api28-r323k-20261111-1.aarch64.rpm
/usr/sbin/saildroid-qq-hotfix check
devel-su /usr/sbin/saildroid-qq-hotfix apply
/usr/sbin/saildroid-qq-hotfix verify
```

安装工具校验平台、JNI、编译器和启动输入的 101 项校验和、基线 JAR、完整
镜像闭包和逻辑路径。它通过宿主接口关闭 QQ、管理界面及 Binder；其他
应用若仍使用该组件会拒绝启用。请勿在启用过程中重新打开 Android 应用。
相关文件全部备份到 `/var/lib/saildroid/qq-hotfix-20261111/backup/`，再一起
替换；失败自动恢复，突然断电的中间状态可用 `rollback` 恢复。

`runtime.json` 只合并六项补丁元数据与镜像清单引用，保留目标设备其他
配置。不会修改组件别名、原生库、应用数据、权限或 QQ 登录状态。
启用后自行打开 QQ，重试登录、图片、文件接收、转发和撤回；脚本校验
不能替代这些设备上的用户验收。Sailfish 原生文件打开与下载目录映射
不属于此补丁，文件仍在 Android 共享目录而不是系统 Downloads。

## 回滚与卸载

```sh
devel-su /usr/sbin/saildroid-qq-hotfix rollback
devel-su rpm -e saildroid-qq-hotfix-api28-r323k
```

先回滚再卸载。卸载仅删除暂存包和工具，不会自动恢复正在使用的镜像，
也不删除备份。不覆盖启用后被其他补丁修改的文件；遇到这种情况会拒绝
回滚，避免丢失后续改动。回滚后的旧快照保留，若要再次启用，应先核查
并另行归档整个状态目录，不直接删除备份。

## 构建

```sh
python3 scripts/packaging/qq-hotfix/build.py \
  --artifact build/qq-popup-touch-20261111-v1 \
  --component /opt/saildroid/releases/api28-r323k-dev-20261110 \
  --baseline /path/to/extracted/original/component \
  --output build/qq-hotfix-rpm/package
python3 scripts/api29/tests/test-qq-hotfix-deployment.py
```
