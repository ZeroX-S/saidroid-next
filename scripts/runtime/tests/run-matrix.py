#!/usr/bin/env python3
"""Run the SailDroid integration matrix on the phone from the build VM.

Produces the docs/ACCEPTANCE.md I1-I6 evidence for one run label:

  build/evidence/<run-label>/
      result.json        raw device report (per-item checks + every screenshot)
      summary.json       merged verdicts (device + independent PIL analysis)
      pil-census.json    independent cover/frame analysis of every screenshot
      device-run.log     full device output
      screens/*.png      all evidence screenshots (named steps + I5 burst)
      report.md          human-readable matrix table with evidence paths

Steps
  1. take the shared device lock (scripts/devlock.sh; released on exit)
  2. stage sd_covers.py + integration-matrix.py under /home/art/test/matrix-tools
  3. run the matrix on the phone as root (it acts as the phone user for apps)
  4. pull result.json and every screenshot
  5. re-analyse every screenshot with the independent PIL implementation and
     fail I5 if any frame of the whole-sequence burst is blank
  6. print MATRIX=<run-label>|I1|PASS|<evidence> per item and a final verdict

Usage (inside the "MeeGo Build" VM):
  python3 /media/psf/Home/WorkSpace/saidroid-next/scripts/runtime/tests/run-matrix.py \
      --label r63-matrix-1 --taps 3 --install-confirm 730,1250 \
      --uninstall-row 700,600 --uninstall-confirm 760,1250

Single items only (one item is minutes, not the whole matrix):
  ... --label cal-1 --only I1
  ... --label cal-3 --only I3 --skip-probe

Re-analyse an existing evidence directory without touching the phone:
  ... --label r63-matrix-1 --analyse-only
"""
import argparse
import importlib.util
import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TESTS = REPO / 'scripts/runtime/tests'
EVIDENCE = REPO / 'build/evidence'
PHONE = 'root@bonito'
TOOLS = '/home/art/test/matrix-tools'
SHOT_DIR = '/home/defaultuser/Downloads/SailDroid-Screenshots'
APK_DIR = '/home/defaultuser/Downloads/SailDroid-APKs'
ITEMS = ('I1_cold_start', 'I2_background_return', 'I3_repeat_icon',
         'I4_single_window', 'I5_no_black_window', 'I6_close_relaunch')


def ssh(*command, timeout=120, check=True):
    return subprocess.run(['sshpass', '-e', 'ssh', '-o', 'StrictHostKeyChecking=no',
                           '-o', 'ConnectTimeout=8', PHONE] + list(command),
                          capture_output=True, text=True, timeout=timeout, check=check)


def scp(source, target, timeout=180):
    return subprocess.run(['sshpass', '-e', 'scp', '-O', '-r',
                           '-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=8',
                           source, target],
                          capture_output=True, text=True, timeout=timeout, check=True)


def selection(args):
    chosen = set(ITEMS)
    if args.only:
        keys = {part.strip().upper() for part in args.only.split(',') if part.strip()}
        keys = {key if key.startswith('I') else 'I' + key for key in keys}
        chosen = {name for name in ITEMS if name[:2] in keys}
    if args.skip_items:
        keys = {part.strip().upper() for part in args.skip_items.split(',') if part.strip()}
        keys = {key if key.startswith('I') else 'I' + key for key in keys}
        chosen = {name for name in chosen if name[:2] not in keys}
    return chosen


def collect(args, out, shots):
    """Device phase: lock, stage, run, pull. Returns the device exit code.

    The lock is released only after the device process has been killed and
    reaped: releasing first would hand the phone to another agent while this
    round is still driving the UI.
    """
    env = dict(os.environ, SSHPASS=os.environ['SSHPASS'])
    lock = REPO / 'scripts/devlock.sh'
    acquired = False
    device_rc = 1
    child = None
    timed_out = []

    def watchdog():
        timed_out.append(True)
        print('ROUND_BUDGET=exceeded|killing device run', flush=True)
        if child is not None:
            try:
                child.kill()
            except OSError:
                pass
    timer = threading.Timer(args.budget, watchdog)
    timer.daemon = True
    timer.start()
    try:
        result = subprocess.run(['/bin/bash', str(lock), 'acquire', str(args.budget + 120),
                                 'sd-integration'],
                                capture_output=True, text=True, env=env,
                                timeout=args.budget + 180)
        print(result.stdout.strip(), flush=True)
        if 'LOCK_ACQUIRED' not in result.stdout:
            raise SystemExit('device lock unavailable: %s %s'
                             % (result.stdout.strip(), result.stderr.strip()))
        acquired = True

        ssh('mkdir', '-p', TOOLS)
        # preflight.py runs from the same staged directory, so it must be
        # staged every round: a leftover copy on the phone is not evidence
        # that the current one is there.
        for name in ('sd_covers.py', 'integration-matrix.py', 'preflight.py'):
            scp(str(TESTS / name), '%s:%s/%s' % (PHONE, TOOLS, name))

        if args.preflight:
            check = ['python3', '%s/preflight.py' % TOOLS]
            if args.expect_component:
                check += ['--expect-component', args.expect_component]
            result = ssh(*check, check=False)
            sys.stdout.write(result.stdout)
            sys.stdout.write(result.stderr)
            for line in result.stdout.splitlines():
                if line.startswith('PREFLIGHT='):
                    print(line, flush=True)
            if result.returncode != 0:
                raise SystemExit('preflight failed; release the device without running '
                                 'the matrix (see PREFLIGHT= lines above)')

        needs_probe = 'I4' in selection(args)
        if needs_probe:
            apk = Path(args.probe_apk)
            assert apk.is_file(), apk
            ssh('mkdir', '-p', APK_DIR)
            scp(str(apk), '%s:%s/MatrixProbe.apk' % (PHONE, APK_DIR))
            ssh('chown', 'defaultuser:defaultuser', '%s/MatrixProbe.apk' % APK_DIR)
            ssh('chmod', '600', '%s/MatrixProbe.apk' % APK_DIR)

        command = ['python3', '%s/integration-matrix.py' % TOOLS, '--label', args.label,
                   '--taps', str(args.taps)]
        if args.expect_component:
            env['SAILDROID_EXPECT_COMPONENT'] = args.expect_component
            command += ['--expect-component', args.expect_component]
        if args.in_app_tap:
            command += ['--in-app-tap', args.in_app_tap]
        if args.only:
            command += ['--only', args.only]
        if args.skip_items:
            command += ['--skip-items', args.skip_items]
        if args.skip_probe or not needs_probe:
            command.append('--skip-probe')
        else:
            command += ['--probe-apk', '%s/MatrixProbe.apk' % APK_DIR,
                        '--install-confirm', args.install_confirm,
                        '--uninstall-row', args.uninstall_row or '',
                        '--uninstall-confirm', args.uninstall_confirm or '']
        if args.keep_qq:
            command.append('--keep-qq')

        log_path = out / 'device-run.log'
        with open(log_path, 'w') as log:
            child = subprocess.Popen(['sshpass', '-e', 'ssh',
                                      '-o', 'StrictHostKeyChecking=no',
                                      '-o', 'ConnectTimeout=8', PHONE] + command,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, env=env, start_new_session=True)
            for line in child.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                log.write(line)
            device_rc = child.wait()
        child = None
        if timed_out:
            device_rc = 124
        print('DEVICE_RC=%d' % device_rc, flush=True)

        scp('%s:/home/art/test/matrix-%s/result.json' % (PHONE, args.label),
            str(out / 'result.json'))
        listing = ssh('ls', '-1', '%s/matrix-%s' % (SHOT_DIR, args.label), check=False)
        if listing.returncode == 0:
            for name in listing.stdout.split():
                scp('%s:%s/matrix-%s/%s' % (PHONE, SHOT_DIR, args.label, name),
                    str(shots / name))
        print('EVIDENCE=%s' % out, flush=True)
    finally:
        timer.cancel()
        if child is not None:
            try:
                child.kill()
                child.wait(timeout=30)
            except (OSError, subprocess.SubprocessError):
                pass
        if acquired:
            released = subprocess.run(['/bin/bash', str(lock), 'release', 'sd-integration'],
                                      capture_output=True, text=True, env=env, timeout=60)
            print(released.stdout.strip(), flush=True)
    return device_rc


def run_calibration(timeout=180):
    """Re-run the historical-screenshot calibration; return its summary line."""
    try:
        result = subprocess.run([sys.executable, str(TESTS / 'calibrate-census.py')],
                                capture_output=True, text=True, timeout=timeout)
        for line in result.stdout.splitlines():
            if line.startswith('CALIBRATION='):
                return line
    except (OSError, subprocess.SubprocessError) as error:
        return 'CALIBRATION=error|%s' % error
    return 'CALIBRATION=unavailable'


_MATRIX_MODULE = []


def counterexample_lookup():
    """Reuse the device-side counterexample table when rendering the report."""
    if not _MATRIX_MODULE:
        sys.path.insert(0, str(TESTS))
        spec = importlib.util.spec_from_file_location(
            'integration_matrix', TESTS / 'integration-matrix.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _MATRIX_MODULE.append(module)
    return _MATRIX_MODULE[0].counterexample_for


def reproduce_command(args):
    parts = ['python3 scripts/runtime/tests/run-matrix.py',
             '--label %s' % args.label, '--taps %d' % args.taps]
    for flag, value in (('--only', args.only), ('--skip-items', args.skip_items),
                        ('--expect-component', args.expect_component),
                        ('--install-confirm', args.install_confirm),
                        ('--uninstall-row', args.uninstall_row),
                        ('--uninstall-confirm', args.uninstall_confirm)):
        if value:
            parts.append('%s %s' % (flag, value))
    if args.skip_probe:
        parts.append('--skip-probe')
    return ' '.join(parts)


def analyse(args, out, shots, device_rc):
    """Merge the device report with independent PIL analysis; write summary/report."""
    report = json.loads((out / 'result.json').read_text())
    frames = {}
    if not args.no_analysis:
        images = sorted(shots.glob('*.png'))
        census = subprocess.run([sys.executable, str(TESTS / 'cover_census.py')]
                                + [str(path) for path in images]
                                + ['--json', str(out / 'pil-census.json')],
                                capture_output=True, text=True)
        if census.returncode != 0:
            print('CENSUS_ERROR\n%s%s' % (census.stdout, census.stderr), flush=True)
        if (out / 'pil-census.json').exists():
            frames = {Path(item['image']).name: item
                      for item in json.loads((out / 'pil-census.json').read_text())}

    screens = report.get('screens', {})
    disagreements = []
    for name, screen in screens.items():
        reference = frames.get(Path(screen['path']).name)
        if reference is None:
            continue
        screen['pil_covers'] = reference['cover_count']
        screen['pil_blank'] = reference['blank']
        if reference['cover_count'] != screen['covers'] or reference['blank'] != screen['blank']:
            disagreements.append({'image': Path(screen['path']).name,
                                  'device_covers': screen['covers'],
                                  'pil_covers': reference['cover_count'],
                                  'device_blank': screen['blank'],
                                  'pil_blank': reference['blank']})
    burst = [Path(path).name for path in report.get('burst', [])]
    burst_missing = [name for name in burst if frames and name not in frames]
    blank_frames = [name for name, item in frames.items() if item['blank']]
    blank_burst = [name for name in burst if name in blank_frames]
    blank_named = [name for name in blank_frames if name not in burst]
    crosscheck = {'analyzed': len(frames), 'disagreements': disagreements,
                  'burst_frames': len(burst), 'burst_missing': burst_missing,
                  'blank_frames': blank_frames, 'blank_named': blank_named,
                  'blank_burst': blank_burst,
                  'status': 'ok' if not disagreements and not burst_missing else 'mismatch'}

    items = report.get('items', [])
    lookup = counterexample_lookup()
    for item in items:
        for check in item.get('checks') or []:
            if not check.get('counterexample'):
                check['counterexample'] = lookup(check.get('check', ''))
    by_name = {item['item']: item for item in items}
    if blank_burst:
        item = by_name.get('I5_no_black_window')
        if item is not None:
            item['status'] = 'FAIL'
            item['detail'] += '|blank_burst=%s' % ','.join(blank_burst[:5])
            item['failures'] = item.get('failures', []) + [
                'burst frame(s) blank: ' + ','.join(blank_burst[:5])]
    if blank_named:
        item = by_name.get('I5_no_black_window')
        if item is not None:
            item['status'] = 'FAIL'
            item['detail'] += '|blank_named=%s' % ','.join(blank_named[:5])

    input_state = report.get('input') or {}
    input_verified = input_state.get('verified') is True
    lipstick_stable = report.get('lipstick_stable')
    compositor = report.get('compositor') or ('stable' if lipstick_stable else 'restarted')
    if lipstick_stable is False:
        print('LIPSTICK=UNSTABLE|start=%s|finish=%s|start_ticks=%s'
              % (report.get('lipstick_at_start'), report.get('lipstick_at_finish'),
                 report.get('lipstick_start_ticks')),
              flush=True)
    else:
        print('LIPSTICK=STABLE|pid=%s|start_ticks=%s'
              % (report.get('lipstick_at_start'), report.get('lipstick_start_ticks')),
              flush=True)
    print('COMPOSITOR=%s|lipstick_start=%s|lipstick_finish=%s|start_ticks=%s'
          % (compositor, report.get('lipstick_at_start'),
             report.get('lipstick_at_finish'), report.get('lipstick_start_ticks')),
          flush=True)
    selected = report.get('selected') or [name[:2] for name in ITEMS]
    verdicts = []
    for name in ITEMS:
        entry = by_name.get(name)
        if entry is None:
            status = 'SKIP' if name[:2] not in selected else 'MISSING'
            verdicts.append((name, status, 'not selected for this run' if status == 'SKIP'
                             else 'item did not run'))
        else:
            verdicts.append((name, entry['status'], entry['detail']))

    if not input_verified:
        # An undelivered gesture is indistinguishable from a product that
        # ignores it, so no PASS/FAIL is allowed out of this run.
        verdicts = [(name,
                     'INVALID' if status not in ('SKIP', 'MISSING') else status,
                     ('input not verified: ' + detail)
                     if status not in ('SKIP', 'MISSING') else detail)
                    for name, status, detail in verdicts]
        for item in items:
            if item['status'] != 'SKIP':
                item['status'] = 'INVALID'

    summary = {'label': args.label, 'device_exit': device_rc,
               'input': input_state,
               'items': items, 'verdicts': verdicts, 'crosscheck': crosscheck,
               'screens': screens, 'burst': burst,
               'boot': report.get('boot'), 'component': report.get('component'),
               'compositor': compositor,
               'lipstick_at_start': report.get('lipstick_at_start'),
               'lipstick_at_finish': report.get('lipstick_at_finish'),
               'lipstick_start_ticks': report.get('lipstick_start_ticks'),
               'lipstick_finish_ticks': report.get('lipstick_finish_ticks'),
               'started': report.get('started'), 'finished': report.get('finished')}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2))

    calibration = run_calibration()
    lines = ['# SailDroid 系统接入矩阵报告：%s' % args.label, '',
             '本文件由 `scripts/runtime/tests/run-matrix.py` 生成；**所有数字都从 '
             '`result.json` / `pil-census.json` 抄出，不手打**。', '',
             '- 组件：`%s`' % report.get('component'),
             '- boot id：`%s`' % report.get('boot'),
             '- 合成器：`compositor=%s`（lipstick %s → %s，start_ticks %s → %s）'
             % (compositor, report.get('lipstick_at_start') or '?',
                report.get('lipstick_at_finish') or '?',
                report.get('lipstick_start_ticks') or '?',
                report.get('lipstick_finish_ticks') or '?'),
             '- 设备侧退出码：%d' % device_rc,
             '- 独立帧复核：%d 张，Cover 计数分歧 %d 处，blank 帧 %d 张'
             % (len(frames), len(disagreements), len(blank_frames)),
             '- 输入链路：%s' % (
                 ('verified（injector=`%s`，可见变化 %.4f）'
                  % (input_state.get('injector'), input_state.get('visible_diff', 0.0)))
                 if input_verified else
                 '**UNVERIFIED — 本轮所有依赖注入事件的断言作废（INVALID）**'),
             '- I3 的判定只用 Cover census（PID 稳定只作辅助证据）', '',
             '## 1. 六项判定表', '',
             '| 项 | 判定 | 依据 |', '|---|---|---|']
    for name, status, detail in verdicts:
        lines.append('| %s | **%s** | %s |' % (name, status, detail.replace('|', ' / ')))
    lines += ['', '## 2. 每项判定依据（一行证据 + 每条断言的反例）', '',
              '每条断言都写明「如果它写错了，会看到什么假 PASS」，来自三次 0==0 假通过'
              '（Events / 抽屉 / Home+浮动窗口）的教训。', '']
    for name, status, detail in verdicts:
        lines.append('- **%s**：`%s`' % (name, detail if detail else status))
    lines += ['']
    for item in items:
        checks = item.get('checks') or []
        if not checks:
            continue
        lines += ['### %s 断言明细（%s）' % (item['item'], item['status']), '',
                  '| 断言 | 结果 | 实测值 | 反例（写错会怎样） |', '|---|---|---|---|']
        for check in checks:
            lines.append('| `%s` | %s | %s | %s |'
                         % (check.get('check'), 'PASS' if check.get('pass') else '**FAIL**',
                            str(check.get('value', '')).replace('|', ' / ')[:160] or '-',
                            str(check.get('counterexample', '')).replace('|', ' / ')))
        lines += ['']
    lines += ['', '## 3. 导航与 census 标定结果', '',
              '- Home 到达判据：`ensure_home(expect)` 手势后重新截图数 Cover，'
              '数量等于期望值才算到达（不再假设「右边缘滑 = Home」）',
              '- 计数锚点：precondition 实测 `baseline=%s`（只有安装器在跑），'
              '之后所有计数相对它断言' % report.get('baseline_covers', '?'),
              '- 交叉核对：`CENSUS_CROSSCHECK=%s`（设备侧纯 stdlib vs VM 侧 PIL）'
              % crosscheck['status'],
              '- 历史截图标定：`%s`' % calibration, '',
              '| 图片 | 设备侧 covers | PIL covers | 设备侧 blank | PIL blank |',
              '|---|---|---|---|---|']
    for name, screen in sorted(screens.items()):
        if 'pil_covers' not in screen:
            continue
        lines.append('| %s | %s | %s | %s | %s |'
                     % (Path(screen['path']).name, screen['covers'], screen['pil_covers'],
                        screen['blank'], screen['pil_blank']))
    lines += ['', '## 4. 已知缺口', '',
              '- Cover census 只能数卡片数量：同一张卡片内部「内容闪成图标加载态」'
              '（数量不变）检测不到，需要卡片内像素差，见 docs/SD-INTEGRATION-MATRIX.md §2.2',
              '- I4 只在可自控测试 APK 上验证；QQ 进 `QQBrowserActivity` 后的 WebView NPE '
              '属 sd-webview，不计入本矩阵',
              '- 一次矩阵只跑一趟；跨趟稳定性需要多次运行同一 label 前缀并对比 summary.json', '',
              '## 5. 复现命令', '', '```sh', reproduce_command(args), '```',
              '', '证据目录：`%s`' % out, '']
    (out / 'report.md').write_text('\n'.join(lines) + '\n')
    for path in [out] + sorted(out.rglob('*')):
        try:
            os.chmod(path, 0o755 if path.is_dir() else 0o644)
        except OSError:
            pass

    print('CENSUS_CROSSCHECK=%s|images=%d|disagreements=%d|burst=%d|blank=%d'
          % (crosscheck['status'], len(frames), len(disagreements), len(burst),
             len(blank_frames)), flush=True)
    for name, status, detail in verdicts:
        print('MATRIX=%s|%s|%s|%s' % (args.label, name, status, detail), flush=True)
    print('MATRIX=%s|%s' % (args.label,
                            '|'.join('%s=%s' % (name, status)
                                     for name, status, _ in verdicts)), flush=True)
    failed = [name for name, status, _ in verdicts if status not in ('PASS', 'SKIP')]
    if not input_verified:
        print('MATRIX=%s|INVALID|input_not_verified' % args.label, flush=True)
        return 1
    if lipstick_stable is False:
        # A compositor restart mid-run makes every earlier frame come from a
        # different session; the counts are still real, the comparison is not.
        print('MATRIX=%s|INVALID|lipstick_restarted_during_run' % args.label, flush=True)
        return 1
    print('MATRIX=%s|%s' % (args.label, 'FAIL' if failed else 'PASS'), flush=True)
    return 0 if not failed and device_rc == 0 else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--taps', type=int, default=3)
    parser.add_argument('--only', default='',
                        help='run only these items, e.g. I1,I3,I6 (or 1,3,6)')
    parser.add_argument('--skip-items', default='', help='skip these items, e.g. I4')
    parser.add_argument('--skip-probe', action='store_true')
    parser.add_argument('--keep-qq', action='store_true')
    parser.add_argument('--no-analysis', action='store_true')
    parser.add_argument('--analyse-only', action='store_true',
                        help='only re-analyse an existing build/evidence/<label> directory')
    parser.add_argument('--probe-apk',
                        default='/var/tmp/saidroid-next-matrix-probe-20261026-r1/matrix-probe.apk')
    parser.add_argument('--no-preflight', dest='preflight', action='store_false',
                        help='skip the in-lock preflight (not recommended)')
    parser.add_argument('--budget', type=int, default=900,
                        help='hard wall-clock cap for the device phase, seconds')
    parser.add_argument('--expect-component', default='',
                        help='release directory the run is allowed to test '
                             '(default: /home/art/releases/api29-20261026-r63)')
    parser.add_argument('--in-app-tap', default='',
                        help='X,Y inside the Android window to tap after LoginActivity '
                             'is drawn (e.g. 791,1900); asserts the full delivery chain '
                             'and then resets QQ to a fresh instance')
    parser.add_argument('--install-confirm', default='')
    parser.add_argument('--uninstall-row', default='')
    parser.add_argument('--uninstall-confirm', default='')
    args = parser.parse_args()

    out = EVIDENCE / args.label
    shots = out / 'screens'
    out.mkdir(parents=True, exist_ok=True)
    shots.mkdir(parents=True, exist_ok=True)

    if args.analyse_only:
        if not (out / 'result.json').exists():
            raise SystemExit('no result.json in %s' % out)
        return analyse(args, out, shots, device_rc=0)
    device_rc = collect(args, out, shots)
    if not (out / 'result.json').exists():
        print('MATRIX=%s|FAIL|reason=no result.json|evidence=%s' % (args.label, out))
        return 1
    return analyse(args, out, shots, device_rc)


if __name__ == '__main__':
    sys.exit(main())
