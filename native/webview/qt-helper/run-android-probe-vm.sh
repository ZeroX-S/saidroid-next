#!/bin/bash
set -euo pipefail
repo=/media/psf/Home/WorkSpace/saidroid-next
label=${1:?unique-run-label}
[[ $label =~ ^[a-z0-9-]+$ ]] || exit 2
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}" SD_PKG=org.example.saildroid.webviewprobe
ssh=(sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 root@bonito)
scp=(sshpass -e scp -q -o StrictHostKeyChecking=no -o ConnectTimeout=8)
cd "$repo"
out=$repo/build/evidence/$label
mkdir -p "$out"
bash scripts/devlock.sh acquire 0 codex-webview
base=$("${ssh[@]}" 'readlink -f /home/art/api29-root')
cleanup() {
  "${scp[@]}" "root@bonito:/home/art/test/$label-app.log" "$out/app.log" 2>/dev/null || true
  for frame in before after; do "${scp[@]}" "root@bonito:/home/defaultuser/Downloads/SailDroid-Screenshots/$label-$frame.png" "$out/$frame.png" 2>/dev/null || true; done
  bash scripts/sd.sh close > "$out/close.log" 2>&1 || true
  "${ssh[@]}" 'mcetool --blank-screen' || true
  python3 scripts/perf/close-owned-vm.py >> "$out/close.log" 2>&1 || true
  "${ssh[@]}" "ln -s '$base' /home/art/.api29-root-codex-restore && mv -Tf /home/art/.api29-root-codex-restore /home/art/api29-root"
  bash scripts/devlock.sh release codex-webview
}
trap cleanup EXIT
python3 scripts/perf/close-owned-vm.py
python3 scripts/runtime/deploy-component.py /var/tmp/saidroid-next-api29-component-perf-${SAILDROID_TEST_BUILD:-r84-webview} "$label"
python3 native/webview/qt-helper/install-probe-apk-vm.py ${SAILDROID_TEST_APK_TAG:-r84}
bash scripts/sd.sh sync
# A separate bounded screen watchdog still blanks if the driver/test fails.
"${ssh[@]}" "python3 - '$label'" <<'PY'
import subprocess,sys,os,time,json,signal,re
from pathlib import Path
label=sys.argv[1];pkg='org.example.saildroid.webviewprobe';tool='/home/art/bin/sdtool.py'
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
lip=subprocess.check_output(['pidof','lipstick']).decode().strip()
subprocess.run(['mcetool','--unblank-screen','--set-tklock-mode=unlocked'],check=True)
watch=subprocess.Popen(['/bin/sh','-c','sleep 50; mcetool --blank-screen'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
try:
    subprocess.run(['python3',tool,'--package',pkg,'launch','--env','SAILDROID_DIAG_INPUT=1','--wait','20'],check=True,timeout=25)
    subprocess.run(['python3',tool,'--package',pkg,'wait','--marker','SDWEBPROBE=js|','--wait','20'],check=True,timeout=25)
    # A JS completion callback can precede the final exported/composited frame.
    time.sleep(2)
    subprocess.run(['python3',tool,'--package',pkg,'shot',label+'-before'],check=True,timeout=12)
    # The existing sdinput binary uses one device for this whole gesture.
    subprocess.run(['/home/art/bin/sdinput','swipe','540','1700','540','600','500','40'],check=True,timeout=10)
    time.sleep(3)
    subprocess.run(['python3',tool,'--package',pkg,'shot',label+'-after'],check=True,timeout=12)
    record=json.loads(Path('/run/user/100000/saildroid/'+pkg+'.json').read_text())
    Path('/home/art/test/'+label+'-app.log').write_bytes(Path(record['log']).read_bytes())
    text=Path(record['log']).read_text(errors='replace')
    assert 'SDWEBPROBE=js|' in text and 'answer' in text and '42' in text
    assert 'SDWEBVIEW=draw|renderer=qt-wpe' in text, 'webview draw callback missing'
    assert 'scrollY=' in text and 'SDINPUT=finished|' in text, 'scroll event delivery missing'
    taps=re.findall(r'SDWEBPROBE=input_state\|x=(\d+)\|y=(\d+)',text)
    assert taps and abs(int(taps[-1][0])-540/2.625)<3 and abs(int(taps[-1][1])-1700/2.625)<3, ('touch DPR mapping',taps)
    assert 'SDWEBHOST_LOG=SDWEBHOST=consumer_timeout' not in text
    assert boot==Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert lip==subprocess.check_output(['pidof','lipstick']).decode().strip()
    print('ANDROID_WEBVIEW_PROBE=ready|boot='+boot+'|lipstick='+lip)
finally:
    subprocess.run(['python3',tool,'--package',pkg,'close'],timeout=20)
    subprocess.run(['mcetool','--blank-screen'],check=True)
    try:os.killpg(watch.pid,signal.SIGTERM)
    except ProcessLookupError:pass
PY
"${scp[@]}" "root@bonito:/home/art/test/$label-app.log" "$out/app.log"
for frame in before after; do
  "${scp[@]}" "root@bonito:/home/defaultuser/Downloads/SailDroid-Screenshots/$label-$frame.png" "$out/$frame.png"
done
grep -aE 'SDWEBVIEW=(engine|frame|draw)|SDWEBPROBE=' "$out/app.log" | tail -40

python3 native/webview/qt-helper/check-frames.py "$out/before.png" "$out/after.png" --log "$out/app.log" | tee "$out/pixels.json"
echo "ANDROID_WEBVIEW_SUITE=ready|run=$label"
