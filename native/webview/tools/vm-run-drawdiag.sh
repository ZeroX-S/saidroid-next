#!/bin/bash
# Whiteboard diagnosis run (needs the device lock, owner must be sd-webview).
# Deploys the draw-audit component as release "webview-diag", launches QQ, taps the
# login button, screenshots the white content area and pulls the SDWEBVIEW= diag lines.
# Ends by restoring whatever release api29-root pointed to before this run.
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
H=root@192.168.2.15
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 $H"
REPO=/media/psf/Home/WorkSpace/saidroid-next
RUN=${1:-whiteboard1}
COMP=/var/tmp/saidroid-next-api29-component-webview-diag
EVID=$REPO/build/codex-api29/webview-$RUN
mkdir -p "$EVID"
cd "$REPO" || exit 1

scripts/devlock.sh status | grep -q "sd-webview" || { echo "LOCK_NOT_MINE"; scripts/devlock.sh status; exit 2; }

restore_base() {
  $SSH "python3 -c \"import os,pathlib;link=pathlib.Path('/home/art/api29-root');tmp=pathlib.Path('/home/art/.api29-root-webview');tmp.unlink(missing_ok=True);tmp.symlink_to('$BASE');os.replace(tmp,link);print('ROOT_NOW='+os.readlink(link))\""
}
BASE=$($SSH 'readlink -f /home/art/api29-root')
echo "BASE_BEFORE=$BASE"
trap 'restore_base' EXIT

echo "=== 0. close all owned ==="
scripts/lead_close_all.sh 2>&1 | tail -2

echo "=== 1. deploy draw-audit component ==="
python3 scripts/runtime/deploy-component.py "$COMP" "$RUN" 2>&1 | tail -3 || { echo DEPLOY_FAILED; exit 3; }
$SSH 'readlink /home/art/api29-root'

echo "=== 2. launch QQ and wait for the login window ==="
scripts/sd.sh close 2>&1 | tail -1
scripts/sd.sh launch --wait 60 --env SAILDROID_DIAG_INPUT=1 --env SAILDROID_ANDROID_LOG_STDERR=1 2>&1 | tail -2
scripts/sd.sh wait --wait 60 --marker SDWINDOW_SESSION=drawn 2>&1 | tail -1
sleep 3
scripts/sd.sh shot "$RUN-login" 2>&1 | tail -1

echo "=== 3. tap login (791,1985) -> QQBrowserActivity ==="
scripts/sd.sh input tap 791 1985 60 2>&1 | tail -1
sleep 8
scripts/sd.sh shot "$RUN-after" 2>&1 | tail -1

echo "=== 4. pull log ==="
scripts/sd.sh log -n 6000 > "$EVID/app.log" 2>&1
echo "LOG_LINES=$(wc -l < "$EVID/app.log")"
for pat in 'SDWEBVIEW=diag|' 'SDWEBVIEW=draw|' 'SDWEBVIEW=set_frame|' 'SDWEBVIEW=placeholder|' 'SDWEBVIEW=attached' 'SDWEBVIEW=window_visibility' 'SDWEBVIEW=predispatch' 'SDWEBVIEW=unsupported|' 'SDRUNTIME=failed' 'MarginLayoutParams.leftMargin'; do
  echo "COUNT[$pat]=$(grep -ac "$pat" "$EVID/app.log")"
done
echo "--- diag lines ---"
grep -a 'SDWEBVIEW=diag|' "$EVID/app.log" | tr -d '\000' | head -40
echo "--- draw/set_frame/attached ---"
grep -a -E 'SDWEBVIEW=(draw|set_frame|attached|placeholder|window_visibility)' "$EVID/app.log" | tr -d '\000' | head -20

echo "=== 5. close ==="
scripts/sd.sh close 2>&1 | tail -1
echo "DONE run=$RUN evidence=$EVID"
