from l2t import *
import json
def J(x): return json.dumps(x,ensure_ascii=False)[:300]
d=R+"/nm"; shutil.rmtree(d,ignore_errors=True); os.makedirs(d+"/hub/hub"); os.makedirs(d+"/data")
open(d+"/data/config.yaml","w").write(f"storage:\n  models_dir: {d}/hub\n")
p,line=start(d,hub=False); print(line.strip())
time.sleep(1); start_sse(); time.sleep(0.5)
print("state",J(call("models.state")))
def attempt(alias,label):
    n0=len(EV)
    r=call("models.select",{"alias":alias}); t=time.time()
    while time.time()-t<60:
        s=call("models.state")["result"]
        if not s.get("loading") and time.time()-t>0.3: break
        time.sleep(0.2)
    ev=[(n,d_) for (_,n,d_) in EV[n0:] if n=="model_load"]
    print(label,"sel",J(r)[:100],"took",round(time.time()-t,1),"loading",s.get("loading"),"last_load",J(s.get("last_load")),"ev",J(ev)[:250])
for i in range(1,6): attempt("gigaam-v3-ctc",f"giga#{i}")
attempt("vosk-ru","vosk-ru#1")
attempt("gigaam-v3-ctc","giga#6")
# immediate retry: select again at once while first failure just reported
r1=call("models.select",{"alias":"gigaam-v3-ctc"}); r2=call("models.select",{"alias":"gigaam-v3-ctc"}); print("double",J(r1)[:80],J(r2)[:80]); time.sleep(5); print(J(call("models.state")["result"].get("last_load")), call("models.state")["result"].get("loading"))
# now copy model in and select
shutil.copytree(R+"/hub/models--alphacep--vosk-model-small-ru", d+"/hub/hub/models--alphacep--vosk-model-small-ru")
attempt("vosk-ru-small","vosk-small after fails")
print("ready",call("app.snapshot")["result"]["engine"])
print(stop_runtime(p))
