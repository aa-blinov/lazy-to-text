from l2t import *
import json
def J(x): return json.dumps(x,ensure_ascii=False)[:300]
d=R+"/nm"; 
p,line=start(d,hub=False); print(line.strip())
time.sleep(1); start_sse(); time.sleep(0.5)
def trace(alias):
    n0=len(EV); t0=time.time()
    r=call("models.select",{"alias":alias}); print("select",J(r)[:120])
    last=None
    while time.time()-t0<6:
        s=call("models.state")["result"]; a=call("app.snapshot")["result"]["state"]
        k=(s.get("loading"),s.get("state"),a,(s.get("last_load") or {}).get("outcome"),(s.get("last_load") or {}).get("at"))
        if k!=last: print(round(time.time()-t0,2),k); last=k
        time.sleep(0.03)
    print([(n,round(t-t0,2)) for (t,n,_) in EV[n0:] if n in("model_load","state","engine")])
trace("gigaam-v3-ctc"); trace("gigaam-v3-ctc")
call("models.select",{"alias":"vosk-ru-small"}) ; 
time.sleep(3)
print(stop_runtime(p))
