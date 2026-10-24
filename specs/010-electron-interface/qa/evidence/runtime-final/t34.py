from l2t import *
import json, signal
from t32h import desc
def J(x): return json.dumps(x,ensure_ascii=False)[:250]
d=R+"/kw3"; shutil.rmtree(d,ignore_errors=True); p,line=start(d); wait_idle(); start_sse(); time.sleep(.5)
for pid,c in desc(p.pid): os.kill(pid,signal.SIGKILL)
time.sleep(3)
s=call("app.snapshot")["result"]; print("after kill idle:",s["state"],s["engine"],J(call("models.state")["result"].get("ready")))
print("health?",J(call("settings.get")["result"].get("capabilities")))
r=dictate("b.wav",wait=30); print([e for e in r["events"] if e[0]=="delivery"])
print("select same",J(call("models.select",{"alias":"vosk-ru-small"})))
time.sleep(3); print(call("app.snapshot")["result"]["engine"])
r=dictate("b.wav",wait=30); print("after reselect",[e for e in r["events"] if e[0]=="delivery"][:1])
print([l[:160] for l in logs(40) if "worker" in l.lower() or "pipe" in l.lower()][-5:])
print(stop_runtime(p))
