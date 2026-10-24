from l2t import *
import json, signal, subprocess
def J(x): return json.dumps(x,ensure_ascii=False)[:300]
def desc(pid):
    out=subprocess.run(["ps","-eo","pid,ppid,command"],capture_output=True,text=True).stdout.split("\n")[1:]
    ch=[l.split(None,2) for l in out if l.strip()]
    res=[];st=[pid]
    while st:
        x=st.pop()
        for a in ch:
            if int(a[1])==x: res.append((int(a[0]),a[2][:60])); st.append(int(a[0]))
    return res
d=R+"/kw2"; shutil.rmtree(d,ignore_errors=True); p,line=start(d); wait_idle(); start_sse(); time.sleep(.5)
print("children",desc(p.pid))
call("recording.toggle"); time.sleep(0.5); subprocess.Popen(["afplay",R+"/wav/dict30.wav"]); time.sleep(6)
for pid,c in desc(p.pid):
    os.kill(pid,signal.SIGKILL)
time.sleep(0.5)
print(J(call("recording.stop")))
t=time.time()
while time.time()-t<20 and call("app.snapshot")["result"]["state"]!="idle": time.sleep(0.2)
time.sleep(1)
print([ (n,x[:300]) for (_,n,x) in EV if n=="delivery"])
kr=d+"/data/logs/unprocessed-recordings"; print("kept:",os.listdir(kr) if os.path.exists(kr) else None, [oct(os.stat(kr+"/"+f).st_mode&0o777) for f in os.listdir(kr)] if os.path.exists(kr) else "")
print("state",call("app.snapshot")["result"]["state"],call("app.snapshot")["result"]["engine"])
# try again after worker death
time.sleep(3)
print("children now",desc(p.pid))
r=dictate("b.wav",wait=40); print("after crash dictation",r["final"],[e for e in r["events"] if e[0]=="delivery"])
print("clear history",J(call("history.clear"))); print("kept after clear",os.listdir(kr) if os.path.exists(kr) else None)
print(stop_runtime(p))
