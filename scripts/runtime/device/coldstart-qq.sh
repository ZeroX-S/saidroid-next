#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH 'python3 - <<"PY"
from pathlib import Path
import os,pwd,json,subprocess,time
user=pwd.getpwnam("defaultuser");env=dict(os.environ,HOME=user.pw_dir,USER=user.pw_name,LOGNAME=user.pw_name,XDG_RUNTIME_DIR="/run/user/100000",DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/100000/dbus/user_bus_socket")
runtime=Path("/run/user/100000/saildroid");name="com.tencent.mobileqq"
def rec():return json.loads((runtime/(name+".json")).read_text())
def top():return subprocess.check_output(["gdbus","call","--session","--dest","org.nemomobile.lipstick","--object-path","/","--method","org.nemomobile.compositor.privateTopmostWindowProcessId"],env=env,text=True,timeout=3).strip()
def log():return Path(rec()["log"]).read_text(errors="replace")
print("STATE_BEFORE",rec().get("state"),rec().get("pid"))
assert top()=="(0,)","not home: "+top()
subprocess.run(["/home/art/test/delivery-touch-tool-r3/inject-touch","--swipe","540","2159","540","950","400"],check=True,timeout=6)
time.sleep(1.3)
subprocess.run(["/home/art/test/delivery-touch-tool-r3/inject-touch","965","1730"],check=True,timeout=6)
deadline=time.monotonic()+60;drawn="SDWINDOW_SESSION=drawn|title=com.tencent.mobileqq/com.tencent.mobileqq.activity.LoginActivity"
while time.monotonic()<deadline:
    try:
        r=rec()
        if r.get("state")=="running" and r.get("log") and drawn in log():
            if top()=="("+str(r["pid"])+",)":break
    except (OSError,ValueError):pass
    time.sleep(0.2)
else:raise SystemExit("TIMEOUT "+json.dumps(rec()))
r=rec();t=log()
print("COLD=PASS pid=%s launched=%d window_ready=%d scheduled=%d"%(r["pid"],t.count("SDACTIVITY=launched|class=com.tencent.mobileqq.activity.LoginActivity"),t.count("SDWINDOW=ready"),t.count("SDACTIVITY=transaction_scheduled")))
print("TOP",top())
PY'
