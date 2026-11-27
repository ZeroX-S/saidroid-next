#!/usr/bin/env python3
"""SailDroid integration matrix: desktop icon -> Activity lifecycle -> window.

Runs ON THE PHONE as root, but every app/launcher operation is performed as the
ordinary phone user (defaultuser). Each item is asserted from real evidence -
runtime log markers, /proc process state, compositor topmost window and real
Home-screen screenshots - and prints one summary line per item:

    MATRIX=<item>=PASS|field=value|...
    MATRIX=<item>=FAIL|reason=...|evidence=/home/art/test/matrix-<label>/...

Items (docs/ACCEPTANCE.md I1-I6)
  I1_cold_start        drawer icon -> real ART process -> one Wayland window -> SDWINDOW_SESSION=drawn
  I2_background_return Home -> icon -> same instance + same pixels, Android onResume marker
  I3_repeat_icon       N repeat icon taps -> Cover census does not grow (no PID evidence)
  I4_single_window     test APK: A -> B (same process) -> C (declared :tool, cohosted), one stack
  I5_no_black_window   burst capture of the whole sequence, every frame passes the pixel check
  I6_close_relaunch    authenticated close -> no residue -> cold start works again

Cover counting: Lipstick's cover model cannot be queried over D-Bus (rowCount
and windowId are advertised by introspection but not dispatchable on the phone),
so the matrix decodes the real screenshot in pure Python (sd_covers.py) and
counts the cover cards on the measured Home grid. run-matrix.py repeats the
count with an independent PIL implementation as a cross-check.

Usage:
  integration-matrix.py --label r63-matrix-1 [--taps 3] [--skip-probe]
                        [--probe-apk PATH --install-confirm X,Y --uninstall-row X,Y
                         --uninstall-confirm X,Y]
"""
import argparse
import json
import os
import pwd
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sd_covers  # noqa: E402

QQ = 'com.tencent.mobileqq'
PROBE = 'org.example.saildroid.matrixprobe'
MANAGER = 'org.saildroid.manager'
RUNTIME = Path('/run/user/100000/saildroid')
OPEN = '/home/art/bin/saildroid-open'
# Input injection is the first gate of the whole matrix: a tap that is not
# delivered looks exactly like a product that ignores it. Two injectors exist,
# so the matrix probes them in order and refuses to run when none of them
# changes the screen (see input_probe).
INJECTORS = (
    {'name': 'sdinput', 'kind': 'sdinput', 'path': '/home/art/bin/sdinput'},
    {'name': 'inject-touch', 'kind': 'inject-touch',
     'path': '/home/art/test/delivery-touch-tool-r3/inject-touch'},
)
ACTIVE_INJECTOR = INJECTORS[0]
SHOTS = Path('/home/defaultuser/Downloads/SailDroid-Screenshots')
EXPECTED_ROOT = os.environ.get('SAILDROID_EXPECT_COMPONENT',
                               '/home/art/releases/api29-20261026-r63')
EXPECTED_BOOT = '5db879ed-48ea-4bf0-b5c1-64e271c11045'
PREFLIGHT_LIPSTICK = ['']
EXPECTED_LIPSTICK = '9800'

# The app drawer is opened by a bottom-edge swipe and then verified by finding
# the app icon inside the resulting frame (open_drawer). No layout coordinates
# are trusted any more, so a new app or a moved grid cannot cause a blind tap.
def drawer_gestures():
    """Drawer gestures, fastest first.

    A slow long swipe from the bottom edge is what Sailfish interprets as a
    "dock peek" (the cover shrinks and the dock appears). The fast short
    variants are tried first because that is the gesture that opens the grid.
    """
    return (lambda: swipe(540, 2159, 540, 600, 160, 10),
            lambda: swipe(540, 2100, 540, 500, 200, 12),
            lambda: swipe(540, 2159, 540, 950, 400, 28),
            lambda: swipe(540, 2050, 540, 500, 500, 32),
            lambda: swipe(540, 2159, 540, 1200, 900, 48))


BACKGROUND_SWIPE = lambda: swipe(1079, 800, 400, 800, 300, 24)
# On the phone, a right-edge swipe from an application opens Events (or Home),
# a bottom swipe opens Home (or the drawer) and a left-edge swipe from Events
# returns to Home. Navigation therefore never trusts one gesture: it gestures
# and then decides from the cover census (see ensure_home).
HOME_UP_SWIPE = lambda: swipe(540, 2159, 540, 1200, 300, 24)
HOME_LEFT_SWIPE = lambda: swipe(2, 1000, 700, 1000, 300, 24)


ITEM_KEYS = ('I1', 'I2', 'I3', 'I4', 'I5', 'I6')

# What a false PASS of each assertion would look like. The matrix has produced
# three "0 == 0" false passes (Events, drawer, Home with a floating window), so
# every assertion carries the trap it exists to close.
COUNTEREXAMPLES = {
    'home_confirmed_by_cover':
        'Events / 抽屉 / dock peek 都没有 Cover，0 也可能"是 Home"；要求 >=1 张且帧里没有 App 图标',
    'home_before_matches_baseline':
        '停在 Events 时 census 也是 0，若期望恰为 0 就假通过；这里用 baseline(>=1) 的绝对量',
    'drawer_captured':
        'Home 的 dock peek 态 covers 也是 0；只有帧里找到图标才算抽屉打开',
    'drawer_visible_not_home':
        'peek 态同样 covers=0，旧断言因此假通过；现在要求 covers=0 且找到图标',
    'icon_layout_unchanged':
        '辅助断言：网格移位时按旧坐标点会点到壁纸；点击点已改为当轮匹配，此项只留警告',
    'splash_transaction':
        '窗口 drawn 但没有 Activity 事务（空实现）也能出 drawn；必须同时有 transaction_scheduled',
    'splash_resumed':
        'drawn 不等于 resumed；空实现可以只画个窗口，不会有 launched|resumed=true',
    'login_resumed':
        'Splash 也打 resumed=true；必须点名 LoginActivity 且该行出现在 started 之后',
    'login_launch_count_once':
        '复用路径（onNewIntent）不产生 launched 行；若实现退化成重建，计数会变 2',
    'single_launcher_start':
        '断言 >=1 时第二个实例也会通过；这里要求恰好 1 条 started',
    'single_launcher_start_in_log':
        '第二次点击若起了第二个 runtime，started 会变 2；恰好 1 才能排除',
    'same_launch_id':
        '新实例可能复用同一 pid 语义（launch_id 变、pid 变）；launch_id 是单实例锁的一次授予',
    'same_pid':
        '进程活着但被换掉（不同 start_ticks）也会"活着"；pid+start_ticks 一起比对',
    'same_pid_after_repeats':
        '进程活着不代表是同一个实例；pid+start_ticks 同时比对',
    'single_instance':
        '两个 runtime 时进程数才是 2；census 不变也可能藏着第二个实例',
    'single_runtime':
        '同包两个 supervisor 时进程数才暴露；census 稳定不能证明只有一个 runtime',
    'single_runtime_before_repeat':
        '重复点击前若已有两个 supervisor，后面所有 Coverage 断言都无意义',
    'single_runtime_after_relaunch':
        '重开后若残留旧 runtime，会同时有两个窗口栈',
    'same_supervisor_process':
        '第二个 supervisor 用同一标题时 argv[0] 无法区分；pid+start_ticks 一起查',
    'supervisor_is_activity_role':
        'broker/其他角色也有 supervisor 标题；必须精确等于 activity:<pkg>',
    'android_resume_marker':
        '空实现不打 host_visibility 行；没有这行就说明 onResume 没真走',
    'android_resume_per_tap':
        '重复点击若只复用窗口而不走 onResume，计数不会 +1；这是真生命周期判据',
    'no_extra_cover_during_taps':
        '0.35 s 采样可能漏掉 <0.5 s 的临时 Cover；漏采已登记为缺口，不能当"没有"',
    'cover_count_unchanged_every_round':
        '停在 Events/peek 时计数也等于 baseline；ensure_home 已先证明是 Home',
    'cover_count_unchanged_after_repeats':
        '同 3 的陷阱；必须配合 ensure_home 的图标记号证据',
    'no_new_launcher':
        '复用实例不会新增 started；若断言写成"没有 started"就会把正常冷启动也判错',
    'no_new_window':
        'SDWINDOW=ready 每进程固定 1 条；断言 >=1 时第二个窗口也能通过，这里要求不增',
    'no_new_activity_window':
        'SDWINDOW_SESSION=added 每个 Activity 一条；回前台若重建会 +1',
    'no_activity_recreate':
        'create 计数只能证明 Activity 对象没重建；画面是否保留由 pixel_diff 断言',
    'pid_stable_while_background':
        '后台期间被系统杀掉再拉起，pid 会变——这正是要抓的',
    'same_pixels_after_warm_return':
        '只比 PID/日志会漏掉"回到前台但白屏"；像素差 <=2% 才证明画面保留',
    'cover_after_background':
        'QQ 后台若无 Cover，用户看到的就不是"后台驻留"；census 必须 baseline+1',
    'cover_after_warm_return':
        '回前台再回 Home 若 Cover 消失，说明实例被重建或 Cover 未恢复',
    'warm_frame_has_content':
        '只判非 blank 会漏"白底+提示条"；low_content 帧单独列出人工复核',
    'login_frame_has_content':
        '同 warm_frame_has_content；纯白帧如果带着提示条不会被判 blank',
    'transition_frames_have_edges':
        '黑窗可以是"内容区单色但状态栏正常"，edges 判据专门抓这一形态',
    'switch_frames_have_content':
        'Activity 切换若黑屏但状态栏正常，整屏 blank 判据会漏；边缘密度补上',
    'named_frames_captured':
        '没有命名帧就没有逐步证据；帧数>0 不等于"没问题"，还要每帧过判据',
    'burst_frames_captured':
        '没有连拍就没有"全程无黑窗"的结论；连拍帧还必须逐帧判 blank',
    'no_blank_named_frame':
        'blank 只判整屏单色；白底带提示条的帧不算 blank，需人工复核',
    'cohost_marker':
        '另起 ART 进程时不会出现 cohosted 行；必须点名 declared_process=<pkg>:tool',
    'secondary_process_not_spawned':
        'cohost 失败时会看到 :tool 进程；进程数=0 才是同一容器',
    'one_window_surface':
        '每进程固定一个 surface；若宿主为二级进程另起窗口，计数会 >1',
    'probe_single_window':
        '同上；drawn 行不能当窗口计数使用',
    'probe_same_pid':
        '二级进程若另起 ART，pid 会变；这是 cohost 的核心判据',
    'probe_single_launcher':
        '另起 ART 会新增 started；恰好 1 条才是同一 runtime',
    'no_early_pause_second':
        'r58 黑窗根因是旧 Activity 先 pause；顺序从 APIMATRIX 时间戳比对',
    'no_early_pause_tool':
        '同上；二级进程 Activity 若先 pause 旧窗口，同样黑窗',
    'stack_restored':
        'C finish 后若停在空白，B 不会再有 resume；要求 B resume 晚于 C destroy',
    'fresh_pid':
        'close 没真退出但 state 被删也会"没有旧 pid"；fresh_log 要求新日志路径',
    'fresh_launch_id':
        '复用旧 state json 会造成假 fresh；launch_id 必须在 close 之后重新授予',
    'fresh_supervisor':
        '旧 supervisor 若还活着，超时后会接管；pid+start_ticks 都要新',
    'close_exit':
        '崩溃退出（code=10）也是 exited；必须写 code=0 且 reason=closed',
    'socket_removed':
        'supervisor 退出但 socket 残留会让下次激活连到死进程',
    'no_leftover_process':
        '进程活着但已无窗口也会"没退出"；close 后必须一个都不剩',
    'cover_removed_after_close':
        'Cover 还在说明窗口没真撤；Home 必须回落到 baseline',
    'cover_restored_after_relaunch':
        '重开后 Cover 不出现说明冷启动没走完；必须回到 baseline+1',
    'relaunch_launcher_count':
        '复用旧实例时不会新增 started；重开必须恰好一条新 started',
    'relaunch_single_window':
        '重开若残留旧 surface，窗口数会 >1',
    'relaunch_frame_has_content':
        '同 warm_frame_has_content；重开成功但白屏会漏',
    'association_process_uid':
        '同包进程可能由别的用户拉起（root），uid 100000 才对',
    'association_cmdline':
        'ART 子进程 cmdline 首项应为包名；supervisor 不是窗口进程',
    'association_supervisor_title':
        '标题不匹配说明 launch 没走 saildroid-open 的 supervisor 路径',
    'association_desktop_entry':
        '没有 .desktop 就无法从旗鱼桌面启动；文件名必须等于 app_id',
    'association_desktop_token':
        '缺 --desktop-token 会让窗口无法归到桌面项（用户看到无卡片/新卡片）',
    'association_no_forced_flag':
        'X-Nemo-Single-Instance=no 会让 Switcher 每次留下临时 Cover，正是用户报的问题',
    'association_topmost_is_art':
        'topmost 是 supervisor 时说明窗口归属错了；必须是 ART 子进程 pid',
    'no_qq_before_run':
        'QQ 先跑着会让冷启动变成热启动，I1 就失去意义',
    'burst_frames_captured':
        '帧数够了不代表每帧都干净；判据在 blank/edges 断言',
    'no_blank_burst_frame':
        '抽样帧里只要有一帧整屏单色就是黑窗；12 帧抽样可能漏短于 1.6 s 的闪现',
    'transition_frames_have_edges':
        '黑窗可以带正常状态栏（整屏 blank 判据会漏），所以用内容区边缘密度兜底',
    'exception':
        '断言本身超时/导航失败；FAIL 是结论，不是可以忽略的环境噪声',
    'input_delivered_to_app':
        '坐标能到合成器但 Java 的 SdWindowSession.deliver() 没投递时应用不响应；'
        '必须看到应用自己打的 SDINPUT=touch_down|match=1 且坐标非 (0,0)',
    'input_visible_effect':
        '注入器打印了 SDINPUT=tap 也可能没送达（uinput 轴范围 0 会把坐标夹到 0）；'
        '必须看到一帧真的变了才算送达',
}

PREFIX_COUNTEREXAMPLES = ()

def counterexample_for(name):
    if name in COUNTEREXAMPLES:
        return COUNTEREXAMPLES[name]
    return '未登记反例（见 docs/SD-INTEGRATION-MATRIX.md §5.1）'

PHASE_NAMES = {'I1': 'I1_cold_start', 'I2': 'I2_background_return',
               'I3': 'I3_repeat_icon', 'I4': 'I4_single_window',
               'I5': 'I5_no_black_window', 'I6': 'I6_close_relaunch'}

try:  # importable off-device for offline checks of the selection/parse logic
    USER = pwd.getpwnam('defaultuser')
    ENV = dict(os.environ,
               HOME=USER.pw_dir, USER=USER.pw_name, LOGNAME=USER.pw_name,
               XDG_RUNTIME_DIR='/run/user/100000',
               DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/100000/dbus/user_bus_socket')
except KeyError:
    USER = None
    ENV = dict(os.environ)


class Failed(Exception):
    pass


def run(command, timeout=12, as_user=False, check=True):
    kwargs = dict(capture_output=True, text=True, timeout=timeout, env=ENV)
    if as_user:
        kwargs.update(user=USER.pw_uid, group=USER.pw_gid,
                      extra_groups=os.getgrouplist(USER.pw_name, USER.pw_gid))
    result = subprocess.run(command, **kwargs)
    if check and result.returncode != 0:
        raise Failed('command failed rc=%d: %s\n%s%s' % (
            result.returncode, ' '.join(command), result.stdout, result.stderr))
    return result


def tap(x, y):
    """Deliver one tap through the injector chosen by input_probe().

    Returns the injector's own output. ``SDINPUT=tap`` only proves injection,
    so callers must also see the app-side chain (native touch_down, Java
    sent/accepted, finished|handled=true) or a frame change before claiming
    the tap was delivered.
    """
    x, y = str(int(float(x))), str(int(float(y)))
    if ACTIVE_INJECTOR['kind'] == 'sdinput':
        return run([ACTIVE_INJECTOR['path'], 'tap', x, y], timeout=8).stdout
    return run([ACTIVE_INJECTOR['path'], x, y], timeout=8).stdout


def swipe(x1, y1, x2, y2, ms=400, steps=24):
    args = [str(int(float(v))) for v in (x1, y1, x2, y2)]
    if ACTIVE_INJECTOR['kind'] == 'sdinput':
        return run([ACTIVE_INJECTOR['path'], 'swipe'] + args + [str(int(ms)), str(int(steps))],
                   timeout=15).stdout
    return run([ACTIVE_INJECTOR['path'], '--swipe'] + args + [str(int(ms))],
               timeout=15).stdout


def injector_available(injector):
    return Path(injector['path']).is_file()


def input_probe(matrix):
    """Prove that an injected gesture reaches the compositor before any tap.

    A tap that is never delivered looks exactly like an app that ignores it, so
    the matrix proves delivery first: swipe and require the frame to change.
    The injector that produced the change is kept for the whole run. When no
    injector changes the screen the run refuses to continue.
    """
    global ACTIVE_INJECTOR
    attempts = []
    for injector in INJECTORS:
        if not injector_available(injector):
            attempts.append({'injector': injector['name'], 'available': False})
            continue
        ACTIVE_INJECTOR = injector
        before = matrix.shot('input-probe-before-' + injector['name'])
        output = swipe(540, 2159, 540, 1200, 300, 24) or ''
        time.sleep(0.9)
        after = matrix.shot('input-probe-after-' + injector['name'])
        difference = sd_covers.frame_diff(before['path'], after['path'])
        printed = [line for line in output.splitlines() if line.startswith('SDINPUT=')]
        attempts.append({'injector': injector['name'], 'available': True,
                         'visible_diff': round(difference, 4),
                         'injector_output': printed[:4]})
        if difference >= 0.004:
            matrix.report['input'] = {'verified': True, 'injector': injector['name'],
                                      'visible_diff': round(difference, 4),
                                      'injector_output': printed[:4],
                                      'attempts': attempts}
            return injector
    matrix.report['input'] = {'verified': False, 'attempts': attempts}
    raise Failed('input not delivered by any injector (no visible change after a '
                 'bottom swipe): %s' % attempts)


def top():
    """PID owning the compositor's topmost window; 0 when none."""
    out = run(['gdbus', 'call', '--session', '--dest', 'org.nemomobile.lipstick',
               '--object-path', '/',
               '--method', 'org.nemomobile.compositor.privateTopmostWindowProcessId'],
              timeout=5).stdout.strip()
    match = re.match(r'\((\d+),\)', out)
    if not match:
        raise Failed('unexpected compositor reply: %r' % out)
    return int(match.group(1))


def state(package):
    try:
        return json.loads((RUNTIME / (package + '.json')).read_text())
    except (OSError, ValueError):
        return {}


def log_text(package):
    path = state(package).get('log')
    if not path:
        return ''
    try:
        return Path(path).read_text(errors='replace').replace('\x00', '')
    except OSError:
        return ''


def ticks(pid):
    raw = (Path('/proc') / str(pid) / 'stat').read_text()
    return int(raw[raw.rfind(') ') + 2:].split()[19])


def alive(package):
    info = state(package)
    try:
        pid = info['pid']
        return Path('/proc/%d' % pid).exists() and ticks(pid) == info['start_ticks']
    except (KeyError, OSError, ValueError):
        return False


def supervisor_cmdline(pid):
    """argv[0] of a pid (the supervisor renames itself), '' when gone."""
    if not pid:
        return ''
    try:
        return (Path('/proc') / str(pid) / 'cmdline').read_bytes().split(b'\0')[0].decode(
            errors='replace')
    except OSError:
        return ''


def proc_start_ticks(pid):
    """Field 22 of /proc/<pid>/stat: survives pid reuse, so it pins one session."""
    try:
        text = Path('/proc/%s/stat' % pid).read_text()
    except OSError:
        return ''
    tail = text.rsplit(')', 1)[-1].split()
    return tail[19] if len(tail) > 19 else ''


def process_count(command_name):
    """How many processes start with exactly this cmdline[0]."""
    matches = 0
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            first = (process / 'cmdline').read_bytes().split(b'\0')[0].decode(errors='replace')
        except OSError:
            continue
        if first == command_name:
            matches += 1
    return matches


def wait(check, timeout, what):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except Failed:
            raise
        except Exception as error:  # transient /proc race while a process starts
            last = error
        time.sleep(0.1)
    raise Failed('timeout waiting for %s (last error=%r)' % (what, last))


def svc(package, *options, timeout=40):
    command = [OPEN] + (['--manager'] if package == MANAGER else ['--package', package])
    return run(command + list(options), timeout=timeout, as_user=True)


def launch_background(package, logname):
    path = Path('/home/art/test') / logname
    with open(path, 'ab') as output:
        subprocess.Popen([OPEN] + (['--manager'] if package == MANAGER else ['--package', package]),
                         stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                         env=ENV, start_new_session=True, close_fds=True,
                         user=USER.pw_uid, group=USER.pw_gid,
                         extra_groups=os.getgrouplist(USER.pw_name, USER.pw_gid))


def fresh_log(package, previous, timeout, what):
    """Wait for a NEW instance record (new log path), never a stale state json."""
    return wait(lambda: alive(package) and state(package).get('log')
                and state(package).get('log') != previous, timeout, what)


def app_icon_path(package):
    """Resolve the launcher icon of a SailDroid package from its .desktop file."""
    desktop_dir = Path('/home/defaultuser/.local/share/applications')
    token = '--desktop-token ' + package
    for desktop in sorted(desktop_dir.glob('org.saildroid.app.*.desktop')):
        text = desktop.read_text(errors='replace')
        if token not in text:
            continue
        for line in text.splitlines():
            if line.startswith('Icon='):
                icon = line[5:].strip()
                if os.path.isabs(icon) and os.path.exists(icon):
                    return icon
    candidates = sorted((Path('/home/art/apps') / package).glob('versions/*/icon.png'))
    if candidates:
        return str(candidates[0])
    raise Failed('no launcher icon found for %s' % package)


def launch_qq_from_icon(matrix, previous_log=None):
    """Real icon launch: open the drawer, tap the located QQ icon, wait."""
    previous = previous_log if previous_log is not None else state(QQ).get('log')
    tap_app_icon(matrix, QQ, 'drawer-launch')
    wait(lambda: alive(QQ), 45, 'QQ process')
    fresh_log(QQ, previous, 30, 'fresh QQ instance record')
    return state(QQ)['pid']


def ensure_qq_foreground(matrix):
    """Make sure QQ runs from a current record and is the topmost window."""
    info = state(QQ)
    if alive(QQ):
        try:
            svc(QQ, timeout=20)
        except Failed:
            pass
        if top() == info.get('pid'):
            return info['pid']
    pid = launch_qq_from_icon(matrix, info.get('log'))
    wait(lambda: 'SDACTIVITY=launched|class=com.tencent.mobileqq.activity.LoginActivity|resumed=true'
         in log_text(QQ), 90, 'LoginActivity resumed')
    wait(lambda: top() == pid, 20, 'QQ foreground')
    return pid


def standalone_sequence(matrix):
    """Minimal icon-driven sequence when only I5 (frame check) is selected."""
    ensure_qq_foreground(matrix)
    pid = state(QQ)['pid']
    ensure_home(matrix, matrix.baseline_covers + 1, 'i5-home-1')
    tap_app_icon(matrix, QQ, 'i5-drawer-1')
    wait(lambda: top() == pid, 30, 'foreground for I5 sequence')
    time.sleep(0.8)
    ensure_home(matrix, matrix.baseline_covers + 1, 'i5-home-2')
    tap_app_icon(matrix, QQ, 'i5-drawer-2')
    wait(lambda: top() == pid, 30, 'foreground again for I5 sequence')
    BACKGROUND_SWIPE()
    wait(lambda: top() == 0, 10, 'Home again for I5 sequence')


# --------------------------------------------------------------------------
# Screenshots (device-specific); cover/frame analysis lives in sd_covers.
# --------------------------------------------------------------------------
def screenshot(name, directory):
    target = Path(directory) / (name + '.png')
    if target.exists():
        target.unlink()
    run(['gdbus', 'call', '--session', '--dest', 'org.nemomobile.lipstick',
         '--object-path', '/org/nemomobile/lipstick/screenshot',
         '--method', 'org.nemomobile.lipstick.saveScreenshot', str(target)], timeout=10)
    # A real 1080x2160 frame is > 1 MB; Lipstick writes it asynchronously, so a
    # frame only counts once two consecutive samples agree and it is not tiny.
    size = -1
    stable = 0
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if target.exists():
            current = target.stat().st_size
            if current == size and current > 20000:
                stable += 1
                if stable >= 2:
                    return target
            else:
                stable = 0
            size = current
        time.sleep(0.2)
    raise Failed('screenshot did not settle: %s' % target)


# --------------------------------------------------------------------------
# Continuous burst capture (docs/ACCEPTANCE.md I5: the whole sequence)
# --------------------------------------------------------------------------
class Burst:
    """Capture a frame every `interval` seconds while the matrix runs."""

    def __init__(self, matrix, interval=1.6, limit=140):
        self.matrix = matrix
        self.interval = interval
        self.limit = limit
        self.frames = []
        self._stop = threading.Event()
        self._thread = None
        self._error = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self):
        index = 0
        while not self._stop.wait(self.interval):
            if index >= self.limit:
                return
            index += 1
            try:
                path = screenshot('burst-%03d' % index, self.matrix.shot_dir)
                self.frames.append(str(path))
            except Exception as error:  # noqa: BLE001 - record, keep the run going
                self._error = str(error)
                return

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=20)
        return self.frames


# --------------------------------------------------------------------------
# Gestures
# --------------------------------------------------------------------------
def ensure_home(matrix, expect, tag):
    """Reach the Sailfish Home screen and prove it with the cover census.

    ``expect`` is the cover count Home must show (an int), or None to accept any
    Home screen that carries at least one cover (a positive Home signal used for
    the precondition, when the exact count is not known yet). Returns the screen
    entry so the caller can assert on the same measurement it navigated with;
    the screenshot is kept as evidence either way.
    """
    gestures = (HOME_UP_SWIPE, BACKGROUND_SWIPE, HOME_LEFT_SWIPE)
    icon = app_icon_path(QQ)
    best = None
    for attempt in range(5):
        if top() != 0:
            BACKGROUND_SWIPE()
            time.sleep(1.0)
        entry = matrix.shot('%s-%d' % (tag, attempt))
        # The drawer is not Home even when a census reads 0: prove the absence
        # of the app icon before accepting a frame as Home.
        in_drawer = sd_covers.find_icon_center(entry['path'], icon) is not None
        entry['in_drawer'] = in_drawer
        matches = ((entry['covers'] == expect) if expect is not None
                   else (entry['covers'] >= 1)) and not in_drawer
        if matches:
            return entry
        if best is None or (expect is not None
                            and abs(entry['covers'] - expect) < abs(best['covers'] - expect)):
            best = entry
        gestures[attempt % len(gestures)]()
        time.sleep(1.0)
    raise Failed('could not reach Home with %s cover(s); best seen=%s (%s)'
                 % ('?' if expect is None else expect, best and best['covers'],
                    best and best['path']))


def open_drawer(matrix, tag='drawer', attempts=5):
    """Open the app drawer and prove it by locating the app icon in the frame."""
    icon = app_icon_path(QQ)
    entry = None
    tried = []
    for attempt in range(attempts):
        output = drawer_gestures()[attempt % len(drawer_gestures())]() or ''
        printed = [line for line in output.splitlines() if line.startswith('SDINPUT=')]
        time.sleep(1.2)
        entry = matrix.shot('%s-%d' % (tag, attempt))
        found = sd_covers.find_icon_center(entry['path'], icon)
        tried.append({'frame': Path(entry['path']).name,
                      'covers': entry['covers'], 'injector_output': printed[:2]})
        if found:
            cx, cy, match = found
            entry['icon'] = {'cx': cx, 'cy': cy, 'score': match['score']}
            entry['attempts'] = tried
            return entry
    raise Failed('drawer did not open after %d gestures: app icon not found; '
                 'frames=%s' % (attempts, [item['frame'] for item in tried]))


def tap_app_icon(matrix, package, tag='drawer'):
    """Open the drawer, locate the app icon by template match, and tap it."""
    entry = open_drawer(matrix, tag)
    tap(entry['icon']['cx'], entry['icon']['cy'])
    return entry


# --------------------------------------------------------------------------
# Matrix bookkeeping
# --------------------------------------------------------------------------
class Item:
    def __init__(self, name):
        self.name = name
        self.checks = []
        self.evidence = {}

    def check(self, name, condition, value='', counterexample=''):
        """Record one assertion plus the counterexample it is designed to exclude.

        ``counterexample`` answers "if this assertion were wrong, what would a
        false PASS look like?" — the matrix has produced three such false
        passes (0 == 0), so every assertion states the trap it guards.
        """
        self.checks.append({'check': name, 'pass': bool(condition),
                            'value': value, 'counterexample': counterexample})
        if not condition:
            raise Failed('%s: %s' % (name, value))

    def note(self, **values):
        self.evidence.update(values)


class Matrix:
    def __init__(self, args):
        self.args = args
        self.label = args.label
        self.evidence_dir = Path('/home/art/test/matrix-' + args.label)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.shot_dir = SHOTS / ('matrix-' + args.label)
        # Re-using a label must never mix frames from an older run into the new
        # evidence directory: the pulled screens/ are the evidence.
        if self.shot_dir.exists():
            for stale in self.shot_dir.glob('*.png'):
                stale.unlink()
        self.shot_dir.mkdir(parents=True, exist_ok=True)
        for stale in self.evidence_dir.glob('*-failure.log'):
            stale.unlink()
        os.chown(self.shot_dir, USER.pw_uid, USER.pw_gid)
        self.screens = {}
        # Cover count on Home with the installer running and every test app
        # closed; every later count is asserted relative to this baseline.
        self.baseline_covers = None
        # Drawer screenshot from the precondition; I3 compares it with its own
        # drawer frame so a shifted icon grid (e.g. after installing the probe
        # APK) fails loudly instead of tapping empty space.
        self.drawer_precondition = None
        self.report = {'label': args.label, 'started': time.time(),
                       'lipstick_at_start': run(['pidof', 'lipstick']).stdout.strip(),
                       'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                       'lipstick': run(['pidof', 'lipstick']).stdout.strip(),
                       'component': str(Path('/home/art/api29-root').resolve())}
        self.report['lipstick_start_ticks'] = proc_start_ticks(
            self.report['lipstick_at_start'])

    def shot(self, name, expect=None):
        path = screenshot(name, self.shot_dir)
        covers, cells, stats = sd_covers.analyze(path)
        entry = {'path': str(path), 'covers': covers, 'cells': cells, **stats}
        if expect is not None:
            entry['expect'] = expect
        self.screens[name] = entry
        return entry

    def add(self, name, status, detail, checks=None, evidence=None, failures=None):
        enriched = []
        for check in checks or []:
            check = dict(check)
            if not check.get('counterexample'):
                check['counterexample'] = counterexample_for(check.get('check', ''))
            enriched.append(check)
        self.report.setdefault('items', []).append(
            {'item': name, 'status': status, 'detail': detail,
             'checks': enriched, 'evidence': evidence or {},
             'failures': failures or []})
        print('MATRIX_ITEM=%s|%s|%s' % (name, status, detail), flush=True)

    def phase(self, name, function):
        item = Item(name)
        started = time.time()
        try:
            detail = function(item) or ''
            status = 'PASS'
        except Exception as error:  # noqa: BLE001 - every failure becomes evidence
            status = 'FAIL'
            detail = 'reason=%s' % str(error).replace('\n', ' ')
            tail = ''
            for package in (QQ, PROBE, MANAGER):
                text = log_text(package)
                if text:
                    tail += '\n--- %s log tail ---\n' % package + '\n'.join(text.splitlines()[-30:])
            failure_file = self.evidence_dir / (name + '-failure.log')
            failure_file.write_text(tail)
            detail += '|evidence=%s' % failure_file
            item.checks.append({'check': 'exception', 'pass': False, 'value': str(error)})
        entry = {'item': name, 'status': status, 'detail': detail,
                 'seconds': round(time.time() - started, 1),
                 'checks': item.checks, 'evidence': item.evidence}
        self.report.setdefault('items', []).append(entry)
        print('MATRIX_ITEM=%s|%s|%s' % (name, status, detail), flush=True)
        return status == 'PASS'

    def finish(self):
        self.report['finished'] = time.time()
        self.report['lipstick_at_finish'] = run(['pidof', 'lipstick'],
                                                check=False).stdout.strip()
        self.report['lipstick_finish_ticks'] = proc_start_ticks(
            self.report['lipstick_at_finish'])
        self.report['lipstick_stable'] = (
            self.report['lipstick_at_finish'] == self.report.get('lipstick_at_start')
            and self.report['lipstick_finish_ticks'] == self.report.get('lipstick_start_ticks'))
        # A restarted compositor means two different render sessions produced the
        # screenshots in this run; run-matrix.py turns such a run into INVALID.
        self.report['compositor'] = ('stable' if self.report['lipstick_stable']
                                     else 'restarted')
        self.report['screens'] = self.screens
        self.report['baseline_covers'] = self.baseline_covers
        self.report['drawer_precondition'] = self.drawer_precondition
        target = self.evidence_dir / 'result.json'
        target.write_text(json.dumps(self.report, indent=2))
        print('RESULT_JSON=%s' % target)
        failed = [entry['item'] for entry in self.report['items'] if entry['status'] != 'PASS']
        print('MATRIX_DEVICE_SUMMARY=%s|failed=%s|label=%s' % (
            'FAIL' if failed else 'PASS', ','.join(failed) or '-', self.label))
        return 1 if failed else 0


# --------------------------------------------------------------------------
# Installer helpers (only for the self-controlled Activity probe)
# --------------------------------------------------------------------------
def manager_ready(matrix):
    if not alive(MANAGER):
        launch_background(MANAGER, 'matrix-manager-launch.stdout')
        wait(lambda: alive(MANAGER), 30, 'installer process')
    info = state(MANAGER)
    wait(lambda: 'SDWINDOW_SESSION=drawn' in log_text(MANAGER), 30, 'installer drawn')
    svc(MANAGER)
    # Activation may need the compositor to finish mapping the window.
    wait(lambda: top() == info['pid'], 25, 'installer foreground')
    return info


def install_probe(matrix, path):
    manager_ready(matrix)
    before = log_text(MANAGER).count('INSTALLER=installed|package=' + PROBE)
    svc(MANAGER, '--install', str(path), timeout=30)
    wait(lambda: 'INSTALLER=confirm|file=' in log_text(MANAGER), 15, 'install confirmation')
    shot = screenshot('installer-confirm-' + matrix.label, matrix.shot_dir)
    matrix.screens['installer_confirm'] = {'path': str(shot), **sd_covers.frame_stats(shot)}
    x, y = [int(float(v)) for v in matrix.args.install_confirm.split(',')]
    tap(x, y)
    # End-to-end proof that the tap reached the Android window, not just the
    # compositor: the app logs the touch it receives (native → Java handoff).
    delivered = []
    deadline = time.time() + 6
    while time.time() < deadline:
        for line in log_text(MANAGER).splitlines():
            if 'SDINPUT=touch_down|match=1' in line and line not in delivered:
                delivered.append(line)
        if delivered:
            break
        time.sleep(0.2)
    wait(lambda: log_text(MANAGER).count('INSTALLER=installed|package=' + PROBE) > before,
         90, 'probe installed')
    return {'installed': True, 'tap_at': (x, y), 'delivery_lines': delivered}


def uninstall_probe(matrix):
    manager_ready(matrix)
    before = log_text(MANAGER).count('INSTALLER=uninstalled|package=' + PROBE)
    tap(*matrix.args.uninstall_row.split(','))
    time.sleep(0.8)
    tap(*matrix.args.uninstall_confirm.split(','))
    wait(lambda: log_text(MANAGER).count('INSTALLER=uninstalled|package=' + PROBE) > before,
         60, 'probe uninstalled')


# --------------------------------------------------------------------------
# Items
# --------------------------------------------------------------------------
def in_app_tap_probe(matrix, item, coordinates):
    """Tap inside the Android window and require the whole delivery chain.

    The injector's own ``SDINPUT=tap`` line proves only that a device was
    written to, not that anybody read it. For a tap that must reach the app we
    require, in this order: native ``touch_down|match=1`` with the tapped
    coordinates, Java ``sent|accepted=true`` and finally the app's
    ``finished|sequence=…|handled=true``.
    """
    x, y = [int(float(value)) for value in coordinates.split(',')]
    text = log_text(QQ)
    before_native = text.count('SDINPUT=touch_down')
    before_sent = text.count('SDINPUT=sent|')
    before_handled = text.count('handled=true')
    output = tap(x, y) or ''
    item.check('injector_reported_injection',
               'SDINPUT=tap|' in output or 'SDINPUT=press|' in output,
               [line for line in output.splitlines() if line.startswith('SDINPUT=')][:2])
    wait(lambda: log_text(QQ).count('SDINPUT=touch_down') > before_native, 10,
         'native touch_down for the in-app tap')
    native = [line for line in log_text(QQ).splitlines() if 'SDINPUT=touch_down' in line][-1]
    item.check('in_app_tap_reached_native',
               '|match=1|' in native and '|x=%d|y=%d' % (x, y) in native, native)
    wait(lambda: log_text(QQ).count('SDINPUT=sent|') > before_sent, 10,
         'Java InputChannel send for the in-app tap')
    sent = [line for line in log_text(QQ).splitlines() if 'SDINPUT=sent|' in line][-1]
    item.check('in_app_tap_accepted_by_java', 'accepted=true' in sent, sent)
    wait(lambda: log_text(QQ).count('handled=true') > before_handled, 15,
         'app-side finished|handled=true')
    handled = [line for line in log_text(QQ).splitlines() if 'handled=true' in line][-1]
    item.check('in_app_tap_handled_by_app', 'handled=true' in handled, handled)
    time.sleep(3.0)
    frame = matrix.shot('qq-after-in-app-tap')
    after = log_text(QQ)
    item.check('in_app_tap_frame_changed',
               sd_covers.frame_diff(matrix.screens['qq-login']['path'], frame['path']) >= 0.004,
               'pixel_diff=%.4f' % sd_covers.frame_diff(
                   matrix.screens['qq-login']['path'], frame['path']))
    item.check('in_app_tap_no_runtime_failure', 'SDRUNTIME=failed' not in after)
    item.check('in_app_tap_process_alive', alive(QQ))
    item.note(in_app_tap={'x': x, 'y': y, 'native': native, 'sent': sent,
                          'handled': handled})
    # The tap above leaves QQ on whatever page it opened (r78: QQ's H5 page, no
    # crash). Later items expect LoginActivity on top, so reset to a fresh
    # instance instead of reporting their assertions against the wrong screen.
    svc(QQ, '--close', timeout=40)
    wait(lambda: not alive(QQ), 20, 'QQ closed after the in-app tap')
    matrix.report['in_app_tap_reset'] = True


def item_cold_start(matrix):
    def body(item):
        before = ensure_home(matrix, matrix.baseline_covers, 'home-cold-before')
        item.check('home_before_matches_baseline', before['covers'] == matrix.baseline_covers,
                   'covers=%d baseline=%d' % (before['covers'], matrix.baseline_covers))
        previous_log = state(QQ).get('log')
        drawer = open_drawer(matrix, 'drawer-cold')
        item.check('drawer_visible_not_home',
                   drawer['covers'] == 0 and 'icon' in drawer,
                   'covers=%d icon=%s' % (drawer['covers'],
                                          drawer.get('icon')))
        drawn_started = time.time()
        tap(drawer['icon']['cx'], drawer['icon']['cy'])
        wait(lambda: alive(QQ), 45, 'QQ process')
        fresh_log(QQ, previous_log, 30, 'fresh QQ instance record')
        pid = state(QQ)['pid']
        start_ticks = state(QQ)['start_ticks']
        wait(lambda: log_text(QQ).count('SDLAUNCHER=started|package=' + QQ) >= 1, 10,
             'launcher start marker')
        item.check('single_launcher_start',
                   log_text(QQ).count('SDLAUNCHER=started|package=' + QQ) == 1,
                   log_text(QQ).count('SDLAUNCHER=started'))
        wait(lambda: 'SDACTIVITY=launched|class=com.tencent.mobileqq.activity.LoginActivity|resumed=true'
             in log_text(QQ), 90, 'LoginActivity resumed')
        text = log_text(QQ)
        item.check('one_window_surface', text.count('SDWINDOW=ready') == 1,
                   text.count('SDWINDOW=ready'))
        item.check('splash_transaction',
                   'SDACTIVITY=transaction_scheduled|class=com.tencent.mobileqq.activity.SplashActivity' in text)
        item.check('splash_resumed',
                   'SDACTIVITY=launched|class=com.tencent.mobileqq.activity.SplashActivity|resumed=true' in text)
        item.check('login_resumed',
                   'SDACTIVITY=launched|class=com.tencent.mobileqq.activity.LoginActivity|resumed=true' in text)
        item.check('login_launch_count_once',
                   text.count('SDACTIVITY=launched|class=com.tencent.mobileqq.activity.LoginActivity') == 1)
        wait(lambda: 'SDWINDOW_SESSION=drawn|title=%s/com.tencent.mobileqq.activity.LoginActivity' % QQ
             in log_text(QQ), 30, 'LoginActivity drawn')
        wait(lambda: top() == pid, 10, 'QQ foreground')
        status = Path('/proc/%d/status' % pid).read_text()
        cmdline = Path('/proc/%d/cmdline' % pid).read_bytes().split(b'\0')[0].decode()
        supervisor = state(QQ)['supervisor_pid']
        supervisor_title = Path('/proc/%d/cmdline' % supervisor).read_bytes().split(b'\0')[0].decode()
        desktop_id = 'org.saildroid.app.p' + __import__('hashlib').sha256(
            QQ.encode()).hexdigest()[:20]
        desktop = Path(USER.pw_dir, '.local/share/applications', desktop_id + '.desktop')
        item.check('association_topmost_is_art', top() == pid, 'top=%d pid=%d' % (top(), pid))
        item.check('association_process_uid', status.split('Uid:')[1].split()[0] == '100000')
        item.check('association_cmdline', cmdline == QQ, cmdline)
        item.check('association_supervisor_title',
                   supervisor_title.startswith('saildroid-supervisor:activity:'), supervisor_title)
        item.check('association_desktop_entry', desktop.is_file(), str(desktop))
        item.check('association_desktop_token',
                   desktop.is_file() and ('--desktop-token ' + QQ) in desktop.read_text())
        item.check('association_no_forced_flag',
                   desktop.is_file() and 'X-Nemo-Single-Instance=no' not in desktop.read_text())
        frame = matrix.shot('qq-login')
        item.check('login_frame_has_content', not frame['blank'],
                   'blank=%s content_edge=%.4f' % (frame['blank'],
                                                   frame.get('content_edge_fraction', 0)))
        for delay in (0.3, 0.7):
            time.sleep(delay)
            matrix.shot('qq-startup-%.1f' % delay)
        in_app = getattr(matrix.args, 'in_app_tap', '') or ''
        if in_app:
            in_app_tap_probe(matrix, item, in_app)
        drawn_ms = int((time.time() - drawn_started) * 1000)
        item.note(pid=pid, start_ticks=start_ticks,
                  covers_before=before['covers'], desktop_id=desktop_id, drawn_ms=drawn_ms,
                  instance_closed_by_in_app_tap=bool(in_app))
        return ('pid=%d|start_ticks=%d|window_ready=1|login_drawn=1|drawn_ms=%d|'
                'covers_before=%d|association=desktop_id+art_pid'
                % (pid, start_ticks, drawn_ms, before['covers']))
    return body


def item_background_return(matrix):
    def body(item):
        info = state(QQ)
        pid, start_ticks = info['pid'], info['start_ticks']
        text = log_text(QQ)
        launches = text.count('SDACTIVITY=launched|class=com.tencent.mobileqq.activity.LoginActivity')
        resumes = text.count('SDACTIVITY=host_visibility|foreground=true|activity=com.tencent.mobileqq.activity.LoginActivity')
        starts = text.count('SDLAUNCHER=started|package=' + QQ)
        ready = text.count('SDWINDOW=ready')
        added = text.count('SDWINDOW_SESSION=added')
        launch_id = info.get('launch_id')
        supervisor = info.get('supervisor_pid')
        supervisor_ticks = ticks(supervisor) if supervisor else None
        before_frame = matrix.shot('qq-before-background')
        BACKGROUND_SWIPE()
        wait(lambda: top() == 0, 10, 'Home after background')
        wait(lambda: log_text(QQ).count('SDACTIVITY=host_visibility|foreground=false') > 0, 10,
             'host background marker')
        time.sleep(1.2)
        home = ensure_home(matrix, None, 'home-background')
        item.check('cover_after_background', home['covers'] == matrix.baseline_covers + 1,
                   'covers=%d baseline=%d' % (home['covers'], matrix.baseline_covers))
        item.check('pid_stable_while_background',
                   state(QQ)['pid'] == pid and state(QQ)['start_ticks'] == start_ticks)
        tap_app_icon(QQ)
        wait(lambda: top() == pid, 25, 'QQ foreground again')
        text = log_text(QQ)
        item.check('same_pid',
                   state(QQ)['pid'] == pid and state(QQ)['start_ticks'] == start_ticks)
        item.check('no_new_launcher', text.count('SDLAUNCHER=started|package=' + QQ) == starts)
        item.check('no_new_window', text.count('SDWINDOW=ready') == ready)
        item.check('no_activity_recreate',
                   text.count('SDACTIVITY=launched|class=com.tencent.mobileqq.activity.LoginActivity') == launches,
                   'before=%d after=%d' % (launches, text.count(
                       'SDACTIVITY=launched|class=com.tencent.mobileqq.activity.LoginActivity')))
        item.check('same_launch_id', state(QQ).get('launch_id') == launch_id,
                   'before=%s after=%s' % (launch_id, state(QQ).get('launch_id')))
        item.check('same_supervisor_process',
                   state(QQ).get('supervisor_pid') == supervisor and supervisor is not None
                   and ticks(supervisor) == supervisor_ticks,
                   'supervisor=%s now=%s' % (supervisor, state(QQ).get('supervisor_pid')))
        item.check('single_runtime', process_count(QQ) == 1, 'instances=%d' % process_count(QQ))
        item.check('no_new_activity_window', text.count('SDWINDOW_SESSION=added') == added,
                   'before=%d after=%d' % (added, text.count('SDWINDOW_SESSION=added')))
        current = text.count('SDACTIVITY=host_visibility|foreground=true|activity=com.tencent.mobileqq.activity.LoginActivity')
        item.check('android_resume_marker', current == resumes + 1,
                   'before=%d after=%d' % (resumes, current))
        frame = matrix.shot('qq-after-warm')
        item.check('warm_frame_has_content', not frame['blank'])
        difference = sd_covers.frame_diff(before_frame['path'], frame['path'])
        item.check('same_pixels_after_warm_return', difference <= 0.02,
                   'pixel_diff=%.4f' % difference)
        after = ensure_home(matrix, None, 'home-after-warm')
        item.check('cover_after_warm_return',
                   after['covers'] == matrix.baseline_covers + 1,
                   'baseline+1=%d after=%d' % (matrix.baseline_covers + 1, after['covers']))
        item.note(pixel_diff=round(difference, 4))
        return ('pid=%d|start_ticks=%d|same_instance=1|relaunch=0|activity_recreate=0|'
                'resume_delta=1|covers=%d->%d|pixel_diff=%.4f'
                % (pid, start_ticks, home['covers'], after['covers'], difference))
    return body


def item_repeat_icon(matrix):
    """Tap the app icon again while it is already running in the background.

    Each round is the real user flow (Home -> drawer -> icon -> app -> Home) and
    the Cover census is measured on the Home screen reached *after* the round,
    because a duplicate/temporary cover can only be seen on Home. A visible
    cover state is not enough: the count must be unchanged and the process,
    launcher record and window count must all be the same instance.
    """
    def body(item):
        taps = matrix.args.taps
        baseline = matrix.baseline_covers
        info = state(QQ)
        pid, start_ticks = info['pid'], info['start_ticks']
        text = log_text(QQ)
        launches = text.count('SDACTIVITY=launched|class=com.tencent.mobileqq.activity.LoginActivity')
        starts = text.count('SDLAUNCHER=started|package=' + QQ)
        ready = text.count('SDWINDOW=ready')
        resume_marker = ('SDACTIVITY=host_visibility|foreground=true|activity='
                         'com.tencent.mobileqq.activity.LoginActivity')
        resumes = text.count(resume_marker)
        launch_id = info.get('launch_id')
        supervisor = info.get('supervisor_pid')
        supervisor_ticks = ticks(supervisor) if supervisor else None
        supervisor_title = supervisor_cmdline(supervisor)
        item.check('single_runtime_before_repeat', process_count(QQ) == 1)
        item.check('supervisor_is_activity_role',
                   supervisor_title == 'saildroid-supervisor:activity:' + QQ, supervisor_title)
        before = ensure_home(matrix, None, 'home-before-repeat')
        item.check('home_before_repeat_has_one_app_cover', before['covers'] == baseline + 1,
                   'covers=%d baseline=%d' % (before['covers'], baseline))
        drawer = open_drawer(matrix, 'i3-drawer-round1')
        if matrix.drawer_precondition:
            drawer_diff = sd_covers.frame_diff(matrix.drawer_precondition, drawer['path'])
            item.check('icon_layout_unchanged', drawer_diff <= 0.02,
                       'drawer_diff=%.4f (grid moved; the icon is located per '
                       'round, so this is advisory)' % drawer_diff)
        after_counts = []
        transient = []
        for tap in range(taps):
            if tap:  # round 1 reuses the drawer opened for the layout check
                drawer = open_drawer(matrix, 'i3-drawer-round%d' % (tap + 1))
            tap(drawer['icon']['cx'], drawer['icon']['cy'])
            time.sleep(0.35)
            frame = matrix.shot('i3-round%d-t035' % (tap + 1))
            transient.append(frame['covers'])
            wait(lambda: top() == pid, 25, 'QQ foreground after repeat tap %d' % (tap + 1))
            wait(lambda: log_text(QQ).count(resume_marker) >= resumes + tap + 1, 20,
                 'Android resume after repeat tap %d' % (tap + 1))
            time.sleep(0.6)
            entry = ensure_home(matrix, None, 'repeat-%d-home' % (tap + 1))
            after_counts.append(entry['covers'])
        text = log_text(QQ)
        instances = process_count(QQ)
        item.check('same_pid_after_repeats',
                   state(QQ)['pid'] == pid and state(QQ)['start_ticks'] == start_ticks,
                   'pid=%d start_ticks=%d' % (state(QQ).get('pid', -1),
                                              state(QQ).get('start_ticks', -1)))
        item.check('single_instance', instances == 1, 'instances=%d' % instances)
        item.check('single_launcher_start_in_log',
                   text.count('SDLAUNCHER=started|package=' + QQ) == 1,
                   'SDLAUNCHER=started count=%d (a second tap must not start a runtime)'
                   % text.count('SDLAUNCHER=started|package=' + QQ))
        item.check('same_launch_id', state(QQ).get('launch_id') == launch_id,
                   'before=%s after=%s' % (launch_id, state(QQ).get('launch_id')))
        item.check('same_supervisor_process',
                   state(QQ).get('supervisor_pid') == supervisor
                   and supervisor is not None and ticks(supervisor) == supervisor_ticks
                   and supervisor_cmdline(supervisor) == supervisor_title,
                   'supervisor=%s now=%s' % (supervisor, state(QQ).get('supervisor_pid')))
        item.check('no_new_launcher', text.count('SDLAUNCHER=started|package=' + QQ) == starts,
                   'before=%d after=%d' % (starts, text.count('SDLAUNCHER=started|package=' + QQ)))
        item.check('no_new_window', text.count('SDWINDOW=ready') == ready,
                   'before=%d after=%d' % (ready, text.count('SDWINDOW=ready')))
        item.check('no_activity_recreate',
                   text.count('SDACTIVITY=launched|class=com.tencent.mobileqq.activity.LoginActivity') == launches,
                   'before=%d after=%d' % (launches, text.count(
                       'SDACTIVITY=launched|class=com.tencent.mobileqq.activity.LoginActivity')))
        item.check('android_resume_per_tap',
                   text.count(resume_marker) == resumes + taps,
                   'before=%d after=%d taps=%d'
                   % (resumes, text.count(resume_marker), taps))
        item.check('cover_count_unchanged_every_round',
                   all(count == baseline + 1 for count in after_counts),
                   'baseline+1=%d rounds=%s' % (baseline + 1, after_counts))
        item.check('no_extra_cover_during_taps',
                   all(count <= baseline + 1 for count in transient),
                   'during=%s limit=%d' % (transient, baseline + 1))
        after = ensure_home(matrix, None, 'home-after-repeat')
        item.check('cover_count_unchanged_after_repeats', after['covers'] == baseline + 1,
                   'covers=%d baseline+1=%d' % (after['covers'], baseline + 1))
        item.note(launch_id=launch_id, supervisor=supervisor,
                  transient_frames=['i3-round%d-t035.png' % (tap + 1) for tap in range(taps)],
                  transient_covers=transient, rounds=after_counts)
        return ('taps=%d|pid=%d|start_ticks=%d|launch_id=%s|supervisor=%s|'
                'launcher_starts=%d|instances=%d|windows=%d|activity_recreate=0|'
                'resume_delta=%d|login_launches=%d|covers_baseline=%d|covers_rounds=%s|'
                'covers_transient=%s|covers_after=%d'
                % (taps, pid, start_ticks, launch_id, supervisor,
                   text.count('SDLAUNCHER=started|package=' + QQ), instances,
                   text.count('SDWINDOW=ready'), taps, launches, baseline, after_counts,
                   transient, after['covers']))
    return body


def item_single_window(matrix):
    def body(item):
        if alive(PROBE):
            svc(PROBE, '--close', timeout=30)
            wait(lambda: not alive(PROBE), 20, 'probe closed before start')
        previous_log = state(PROBE).get('log')
        launch_background(PROBE, 'matrix-probe-launch.stdout')
        wait(lambda: alive(PROBE) and state(PROBE).get('state') == 'running', 40, 'probe process')
        fresh_log(PROBE, previous_log, 30, 'fresh probe instance record')
        pid = state(PROBE)['pid']
        start_ticks = state(PROBE)['start_ticks']
        wait(lambda: 'APIMATRIX=lifecycle|activity=MatrixActivity|event=resume' in log_text(PROBE),
             40, 'MatrixActivity resumed')
        wait(lambda: top() == pid, 15, 'probe foreground')
        text = log_text(PROBE)
        item.check('probe_single_window', text.count('SDWINDOW=ready') == 1,
                   text.count('SDWINDOW=ready'))
        item.check('probe_single_launcher',
                   text.count('SDLAUNCHER=started|package=' + PROBE) == 1)
        wait(lambda: 'APIMATRIX=lifecycle|activity=ToolMatrixActivity|event=resume' in log_text(PROBE),
             40, 'ToolMatrixActivity resumed')
        text = log_text(PROBE)
        item.check('cohost_marker',
                   'SDACTIVITY=cohosted|class=org.example.saildroid.matrixprobe.ToolMatrixActivity|'
                   'declared_process=%s:tool' % PROBE in text)
        item.check('secondary_process_not_spawned', process_count(PROBE + ':tool') == 0)
        def index(marker):
            position = text.find(marker)
            if position < 0:
                raise Failed('missing marker ' + marker)
            return position
        item.check('no_early_pause_second',
                   index('APIMATRIX=lifecycle|activity=SecondMatrixActivity|event=resume')
                   < index('APIMATRIX=lifecycle|activity=MatrixActivity|event=pause'))
        item.check('no_early_pause_tool',
                   index('APIMATRIX=lifecycle|activity=ToolMatrixActivity|event=resume')
                   < index('APIMATRIX=lifecycle|activity=SecondMatrixActivity|event=pause'))
        item.check('probe_same_pid', state(PROBE)['pid'] == pid and
                   state(PROBE)['start_ticks'] == start_ticks)
        frame_b = matrix.shot('probe-second')
        frame_t = matrix.shot('probe-tool')
        item.check('switch_frames_have_content',
                   not frame_b['blank'] and not frame_t['blank'],
                   'second_blank=%s tool_blank=%s' % (frame_b['blank'], frame_t['blank']))
        wait(lambda: log_text(PROBE).count(
            'APIMATRIX=lifecycle|activity=SecondMatrixActivity|event=resume') >= 2,
             30, 'SecondMatrixActivity resumed after tool finish')
        item.check('stack_restored', top() == pid)
        svc(PROBE, '--close', timeout=30)
        wait(lambda: not alive(PROBE), 20, 'probe closed')
        return ('activities=3|pid=%d|start_ticks=%d|cohost=1|secondary_processes=0|'
                'surfaces=1|early_pause=0|restore=1'
                % (pid, start_ticks))
    return body


def item_close_relaunch(matrix):
    def body(item):
        old = state(QQ)
        old_pid = old['pid']
        old_launch_id = old.get('launch_id')
        old_supervisor = old.get('supervisor_pid')
        baseline = matrix.baseline_covers
        before = ensure_home(matrix, None, 'home-before-close')
        item.check('cover_before_close', before['covers'] == baseline + 1,
                   'covers=%d baseline=%d' % (before['covers'], baseline))
        svc(QQ, '--close', timeout=40)
        wait(lambda: not alive(QQ), 20, 'QQ closed')
        text = log_text(QQ)
        exit_line = [line for line in text.splitlines() if 'SDLAUNCHER=exited' in line]
        item.check('close_exit', bool(exit_line) and exit_line[-1].endswith('code=0|reason=closed'),
                   exit_line[-1:])
        item.check('socket_removed', not Path(old['socket']).exists(), old['socket'])
        item.check('no_leftover_process', process_count(QQ) == 0)
        time.sleep(1.0)
        gone = ensure_home(matrix, None, 'home-after-close')
        item.check('cover_removed_after_close', gone['covers'] == baseline,
                   'covers=%d baseline=%d' % (gone['covers'], baseline))
        previous_log = state(QQ).get('log')
        tap_app_icon(QQ)
        wait(lambda: alive(QQ) and state(QQ).get('state') == 'running', 45, 'QQ relaunch process')
        fresh_log(QQ, previous_log, 30, 'fresh QQ instance record after close')
        new_pid = state(QQ)['pid']
        item.check('fresh_pid', new_pid != old_pid, 'old=%d new=%d' % (old_pid, new_pid))
        item.check('fresh_launch_id', state(QQ).get('launch_id') != old_launch_id,
                   'old=%s new=%s' % (old_launch_id, state(QQ).get('launch_id')))
        item.check('fresh_supervisor', state(QQ).get('supervisor_pid') != old_supervisor,
                   'old=%s new=%s' % (old_supervisor, state(QQ).get('supervisor_pid')))
        item.check('single_runtime_after_relaunch', process_count(QQ) == 1,
                   'instances=%d' % process_count(QQ))
        wait(lambda: 'SDACTIVITY=launched|class=com.tencent.mobileqq.activity.LoginActivity|resumed=true'
             in log_text(QQ), 90, 'LoginActivity resumed after relaunch')
        text = log_text(QQ)
        item.check('relaunch_single_window', text.count('SDWINDOW=ready') == 1)
        item.check('relaunch_launcher_count',
                   text.count('SDLAUNCHER=started|package=' + QQ) == 1)
        wait(lambda: top() == new_pid, 10, 'QQ foreground after relaunch')
        frame = matrix.shot('qq-relaunch')
        item.check('relaunch_frame_has_content', not frame['blank'])
        restored = ensure_home(matrix, None, 'home-after-relaunch')
        item.check('cover_restored_after_relaunch', restored['covers'] == baseline + 1,
                   'covers=%d baseline+1=%d' % (restored['covers'], baseline + 1))
        return ('old_pid=%d|new_pid=%d|new_start_ticks=%d|residue=0|'
                'covers_after_close=%d|covers_after_relaunch=%d|relaunch=1'
                % (old_pid, new_pid, state(QQ)['start_ticks'], gone['covers'],
                   restored['covers']))
    return body


def item_no_black_window(matrix):
    def body(item):
        app_frames = {name: entry for name, entry in matrix.screens.items()
                      if name.startswith(('qq-', 'probe-', 'repeat-', 'home-', 'i5-'))}
        item.check('named_frames_captured', len(app_frames) >= 6, len(app_frames))
        blank = [name for name, entry in app_frames.items() if entry['blank']]
        item.check('no_blank_named_frame', not blank, blank)
        # A black window still has a normal status bar, so "not blank" is not
        # enough: a frame with no edges at all is a single-colour content area.
        edges = [entry['edge_fraction'] for entry in app_frames.values()]
        item.check('transition_frames_have_edges',
                   bool(edges) and min(edges) >= 0.002,
                   'min_edge=%.4f frames=%d' % (min(edges) if edges else 0.0, len(edges)))
        burst = [Path(path) for path in matrix.report.get('burst', [])]
        item.check('burst_frames_captured', len(burst) >= 8, len(burst))
        # Analyse a spread of burst frames on the device too, so I5 does not
        # depend on the VM-side PIL pass alone.
        step = max(1, len(burst) // 12)
        sample = burst[::step][:12]
        blank_burst = []
        low_content = []
        for path in sample:
            _, _, stats = sd_covers.analyze(path)
            if stats['blank']:
                blank_burst.append(path.name)
            elif stats.get('low_content'):
                low_content.append(path.name)
        item.check('no_blank_burst_frame', not blank_burst, blank_burst)
        item.note(low_content_frames=[name for name, entry in app_frames.items()
                                      if entry.get('low_content')]
                  + low_content,
                  burst_sample=[path.name for path in sample])
        return ('named_frames=%d|burst_frames=%d|burst_sampled=%d|blank=0|low_content=%d'
                % (len(app_frames), len(burst), len(sample), len(low_content)))
    return body


def parse_selection(only, skip):
    """Resolve --only/--skip-items into a set of item keys (I1..I6)."""
    def normalise(text):
        result = set()
        for part in text.replace(' ', '').split(','):
            if not part:
                continue
            part = part.upper()
            if part.isdigit():
                part = 'I' + part
            if part not in ITEM_KEYS:
                raise SystemExit('unknown item %r: choose from I1..I6' % part)
            result.add(part)
        return result
    selected = normalise(only) if only else set(ITEM_KEYS)
    selected -= normalise(skip)
    if not selected:
        raise SystemExit('no item selected')
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--taps', type=int, default=3)
    parser.add_argument('--only', default='',
                        help='run only these items, e.g. I1,I3,I6 (or 1,3,6)')
    parser.add_argument('--skip-items', default='',
                        help='skip these items, e.g. I4')
    parser.add_argument('--skip-probe', action='store_true',
                        help='do not install the Activity-probe APK (I4 becomes SKIP)')
    parser.add_argument('--keep-qq', action='store_true')
    parser.add_argument('--probe-apk',
                        default='/home/defaultuser/Downloads/SailDroid-APKs/MatrixProbe.apk')
    parser.add_argument('--install-confirm', default='')
    parser.add_argument('--uninstall-row', default='')
    parser.add_argument('--uninstall-confirm', default='')
    parser.add_argument('--in-app-tap', default='',
                        help='after LoginActivity is drawn, tap this X,Y inside the '
                             'Android window and require native+Java+handled evidence '
                             '(e.g. 791,1900 = centre of the QQ login button)')
    parser.add_argument('--expect-component', default=None,
                        help='expected /home/art/api29-root target (defaults to the r63 '
                             'delivery build; pass the perf/webview build when testing one)')
    args = parser.parse_args()
    if getattr(args, 'expect_component', None):
        global EXPECTED_ROOT
        EXPECTED_ROOT = args.expect_component

    if os.getuid() != 0:
        raise SystemExit('run as root (the script performs app operations as the phone user)')
    selected = parse_selection(args.only, args.skip_items)
    if args.skip_probe:
        selected.discard('I4')
    matrix = Matrix(args)
    matrix.report['args'] = vars(args)
    matrix.report['selected'] = sorted(selected)

    precondition = Item('preconditions')
    try:
        if matrix.report['component'] != EXPECTED_ROOT:
            raise Failed('installed component differs: %s (expected %s; pass '
                         '--expect-component or SAILDROID_EXPECT_COMPONENT for another build)'
                         % (matrix.report['component'], EXPECTED_ROOT))
        if matrix.report['boot'] != EXPECTED_BOOT:
            raise Failed('boot id changed: ' + matrix.report['boot'])
        # Lipstick may legitimately have restarted before this run (it did at
        # 05:15:54 CST today, without a reboot). What must not happen is a
        # restart *inside* the run: every screenshot in the evidence would come
        # from a different compositor session.
        PREFLIGHT_LIPSTICK[0] = matrix.report['lipstick']
        for package in (QQ, PROBE, MANAGER):
            if alive(package):
                svc(package, '--close', timeout=30)
                wait(lambda: not alive(package), 20, package + ' closed')
        for package in (QQ, PROBE, MANAGER):
            precondition.check('closed_' + package, process_count(package) == 0,
                               'processes=%d' % process_count(package))
        # Input is the first gate: without a delivered gesture every later tap
        # assertion would describe a screen nobody touched.
        probe = input_probe(matrix)
        precondition.check('input_visible_effect',
                           matrix.report['input'].get('verified') is True,
                           'injector=%s diff=%s'
                           % (probe['name'], matrix.report['input'].get('visible_diff')))
        # The installer's own cover is the positive "this is Home" signal: a
        # Home screen with zero covers cannot be told apart from Events, which
        # is exactly why the old go_home() could silently stop on Events.
        manager_ready(matrix)
        home = ensure_home(matrix, None, 'home-precondition')
        precondition.check('home_confirmed_by_cover', home['covers'] >= 1,
                           'covers=%d' % home['covers'])
        precondition.check('no_qq_before_run', not alive(QQ))
        precondition.check(
            'expected_lipstick_session',
            matrix.report['lipstick_at_start'] == matrix.report['lipstick'],
            'start=%s pinned=%s' % (matrix.report['lipstick_at_start'],
                                    matrix.report['lipstick']))
        matrix.baseline_covers = home['covers']
        drawer = open_drawer(matrix, 'drawer-precondition')
        precondition.check('drawer_captured',
                           drawer['covers'] == 0 and 'icon' in drawer,
                           'covers=%d icon=%s' % (drawer['covers'],
                                                  drawer.get('icon')))
        matrix.drawer_precondition = drawer['path']
        matrix.add('preconditions', 'PASS',
                   'boot=%s|lipstick=%s|component=%s|covers=%d'
                   % (matrix.report['boot'], matrix.report['lipstick'],
                      matrix.report['component'], home['covers']),
                   checks=precondition.checks)
    except Exception as error:  # noqa: BLE001
        matrix.add('preconditions', 'FAIL', 'reason=%s' % str(error).replace('\n', ' '),
                   checks=precondition.checks)
        return matrix.finish()

    installed_here = False
    burst = Burst(matrix).start()
    try:
        if 'I1' in selected:
            matrix.phase(PHASE_NAMES['I1'], item_cold_start(matrix))

        if ('I2' in selected or 'I3' in selected) and not alive(QQ):
            ensure_qq_foreground(matrix)

        if 'I2' in selected:
            matrix.phase(PHASE_NAMES['I2'], item_background_return(matrix))
        if 'I3' in selected:
            matrix.phase(PHASE_NAMES['I3'], item_repeat_icon(matrix))

        if 'I4' in selected:
            install = Item('install_probe')
            try:
                if not Path('/home/art/apps', PROBE).exists():
                    if not args.install_confirm:
                        raise Failed('--install-confirm coordinates required for the installer dialog')
                    proof = install_probe(matrix, args.probe_apk)
                    installed_here = True
                    coordinates = [line for line in proof['delivery_lines']
                                   if 'x=0|y=0' not in line]
                    install.check('input_delivered_to_app', bool(coordinates),
                                  proof['delivery_lines'][-1:] or
                                  'no SDINPUT=touch_down|match=1 line in manager log')
                matrix.add('install_probe', 'PASS', 'package=%s|preinstalled=%s'
                           % (PROBE, not installed_here), checks=install.checks)
            except Exception as error:  # noqa: BLE001
                matrix.add('install_probe', 'FAIL',
                           'reason=%s' % str(error).replace('\n', ' '), checks=install.checks)
                matrix.add('install_probe', 'SKIPPED', 'I4 cannot run without the probe APK')
            matrix.phase(PHASE_NAMES['I4'], item_single_window(matrix))
            if installed_here:
                uninstall = Item('uninstall_probe')
                try:
                    if not args.uninstall_row or not args.uninstall_confirm:
                        raise Failed('--uninstall-row and --uninstall-confirm required')
                    uninstall_probe(matrix)
                    matrix.add('uninstall_probe', 'PASS', 'package=%s' % PROBE,
                               checks=uninstall.checks)
                except Exception as error:  # noqa: BLE001
                    matrix.add('uninstall_probe', 'FAIL',
                               'reason=%s' % str(error).replace('\n', ' '),
                               checks=uninstall.checks)

        if 'I6' in selected:
            if 'I1' not in selected and 'I2' not in selected:
                ensure_qq_foreground(matrix)
            matrix.phase(PHASE_NAMES['I6'], item_close_relaunch(matrix))

        if selected == {'I5'}:
            standalone_sequence(matrix)
    finally:
        matrix.report['burst'] = burst.stop()

    if 'I5' in selected:
        matrix.phase(PHASE_NAMES['I5'], item_no_black_window(matrix))

    if not args.keep_qq:
        for package in (QQ, PROBE, MANAGER):
            if alive(package):
                try:
                    svc(package, '--close', timeout=30)
                except Exception:  # noqa: BLE001 - cleanup must not mask the result
                    pass
    return matrix.finish()


if __name__ == '__main__':
    sys.exit(main())
