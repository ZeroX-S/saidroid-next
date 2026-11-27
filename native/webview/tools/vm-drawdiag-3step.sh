#!/bin/bash
# Whiteboard diagnosis, correct 3-step path (Lead m01216):
#   tap 791,1900 (登录) -> 1005,152 (帮助/右上) -> 400,1803 (前往QQ安全中心)
# Only then does QQ land in QQBrowserActivity, which is where the white content area is.
# Hard rule: if the log never shows a QQBrowserActivity launch, report the run as INVALID
# and do NOT conclude anything about the draw audit.
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
H=root@192.168.2.15
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 $H"
REPO=/media/psf/Home/WorkSpace/saidroid-next
RUN=${1:-whiteboard3}
COMP=/var/tmp/saidroid-next-api29-component-webview-diag
REL=/home/art/releases/api29-$RUN
EVID=$REPO/build/codex-api29/webview-$RUN
mkdir -p "$EVID"; cd "$REPO" || exit 1
scripts/devlock.sh status | grep -q "sd-webview" || { echo LOCK_NOT_MINE; exit 2; }
BASE=$($SSH 'readlink -f /home/art/api29-root'); echo "BASE_BEFORE=$BASE"
cleanup() {
  $SSH "python3 -c \"import os,pathlib;link=pathlib.Path('/home/art/api29-root');tmp=pathlib.Path('/home/art/.api29-root-webview');tmp.unlink(missing_ok=True);tmp.symlink_to('$BASE');os.replace(tmp,link);print('ROOT_NOW='+os.readlink(link))\""
  $SSH "rm -rf $REL /home/art/test/api29-deploy-$RUN; echo RELEASE_REMOVED; ls -1 /home/art/releases | wc -l"
}
trap cleanup EXIT
scripts/lead_close_all.sh 2>&1 | tail -2
echo "=== deploy ==="
python3 scripts/runtime/deploy-component.py "$COMP" "$RUN" 2>&1 | tail -1
scripts/sd.sh launch --wait 60 --env SAILDROID_DIAG_INPUT=1 --env SAILDROID_ANDROID_LOG_STDERR=1 2>&1 | tail -2
scripts/sd.sh wait --wait 60 --marker SDWINDOW_SESSION=drawn 2>&1 | tail -1
sleep 3
step() { echo "=== tap $1,$2 ($3) ==="; scripts/sd.sh input tap "$1" "$2" 60 2>&1 | tail -1; sleep 3; scripts/sd.sh shot "$RUN-$3" 2>&1 | tail -1; }
step 791 1900 t1-login
step 1005 152 t2-help
step 400 1803 t3-safety
sleep 6
scripts/sd.sh shot "$RUN-t4-final" 2>&1 | tail -1
scripts/sd.sh log -n 8000 > "$EVID/app.log" 2>&1
echo "LOG_LINES=$(wc -l < "$EVID/app.log")"
REACHED=$(grep -ac 'SDACTIVITY=launched|class=com.tencent.mobileqq.*QQBrowser' "$EVID/app.log" || true)
echo "REACHED_QQBROWSER=$REACHED"
for pat in 'SDWEBVIEW=diag|' 'SDWEBVIEW=draw|' 'SDWEBVIEW=set_frame|' 'SDWEBVIEW=attached' 'SDWEBVIEW=predispatch' 'SDWEBVIEW=window_visibility' 'SDWEBVIEW=placeholder|' 'unsupported|' 'SDRUNTIME=failed'; do
  echo "COUNT[$pat]=$(grep -ac "$pat" "$EVID/app.log")"
done
if [ "$REACHED" = "0" ]; then echo "RUN_INVALID=no_qqbrowser_activity"; fi
grep -a 'SDACTIVITY=launched' "$EVID/app.log" | tr -d '\000' | tail -4
grep -a 'SDINPUT=finished' "$EVID/app.log" | tr -d '\000' | tail -3
echo "--- diag ---"; grep -a 'SDWEBVIEW=diag|' "$EVID/app.log" | tr -d '\000' | head -60
echo "--- draw/state ---"; grep -a -E 'SDWEBVIEW=(draw|set_frame|attached|placeholder|state|callback)' "$EVID/app.log" | tr -d '\000' | head -30
scripts/sd.sh close 2>&1 | tail -1
echo "DONE run=$RUN"
