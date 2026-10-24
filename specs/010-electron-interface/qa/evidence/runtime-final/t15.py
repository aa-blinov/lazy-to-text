from l2t import *
import json, hole
def J(x): return json.dumps(x,ensure_ascii=False)[:260]
hole.serve(18592)
d=R+"/cl5"; shutil.rmtree(d,ignore_errors=True)
env={"HF_HUB_OFFLINE":"","HF_ENDPOINT":"http://127.0.0.1:18592"}
for k in ("HTTPS_PROXY","HTTP_PROXY","https_proxy","http_proxy"): env[k]=""
p,line=start(d,env=env); wait_idle()
call("models.select",{"alias":"vosk-ru"}); time.sleep(2)
print(J(call("models.cancel_load"))[:90]); time.sleep(25)
print("wedged?",call("models.state")["result"]["loading"],call("app.snapshot")["result"]["engine"])
print("select small:",J(call("models.select",{"alias":"vosk-ru-small"})))
time.sleep(4); print(call("models.state")["result"]["loading"],call("app.snapshot")["result"]["engine"])
print("cancel:",J(call("models.cancel_load"))[:140]); time.sleep(4)
print(call("models.state")["result"]["loading"],call("app.snapshot")["result"]["engine"])
print("select small again:",J(call("models.select",{"alias":"vosk-ru-small"}))); time.sleep(5)
print(call("models.state")["result"]["loading"],call("app.snapshot")["result"]["engine"])
print(stop_runtime(p))
