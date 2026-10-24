from l2t import *
import json, hole
def J(x): return json.dumps(x,ensure_ascii=False)[:300]
hole.serve(18592)
d=R+"/cl3"; shutil.rmtree(d,ignore_errors=True)
env={"HF_HUB_OFFLINE":"","HF_ENDPOINT":"http://127.0.0.1:18592"}
for k in ("HTTPS_PROXY","HTTP_PROXY","https_proxy","http_proxy"): env[k]=""
p,line=start(d,env=env); print(line.strip())
wait_idle(); t0=time.time()
call("models.select",{"alias":"vosk-ru"}); time.sleep(2)
print(J(call("models.cancel_load"))[:100])
def st(): 
    s=call("models.state")["result"]; a=call("app.snapshot")["result"]; return (s.get("loading"),a["state"],a["engine"]["provider"])
for i in range(8): print(round(time.time()-t0,1),st()); time.sleep(5)
print("toggle during:",J(call("recording.toggle")))
print("now closing black hole connections")
for c in hole.CONN:
    try: c.close()
    except Exception: pass
for i in range(10): print(round(time.time()-t0,1),st()); time.sleep(4)
print("toggle after:",J(call("recording.toggle"))); call("recording.cancel")
print(stop_runtime(p))
