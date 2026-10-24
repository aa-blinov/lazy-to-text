from l2t import *
import json
p,line=start(R+"/run1",wipe=True); print(line)
wait_idle(); start_sse(); time.sleep(0.5)
fk=subprocess.Popen([sys.executable,R+"/fakellm.py","18591",R+"/fake.log"])
call("settings.set",{"key":"clipboard.auto_paste","value":False}); call("settings.set",{"key":"audio_feedback.enabled","value":False})
st=call("presets.get"); print(json.dumps(st)[:500])
def upd(**f):
    prof={"id":"default","name":"Default","provider":"ollama","base_url":"http://127.0.0.1:18591","model":"fake-model","api_key":"","timeout_s":10}
    prof.update(f); return call("presets.update",{"profile":prof})
# 1. refused values
for f in [dict(base_url="myserver"),dict(base_url="127.0.0.1"),dict(base_url="http://127.0.0.1:18591/a b"),dict(base_url="http://127.0.0.1:18591/ё"),dict(base_url="http://[::1"),dict(base_url="http://user:PLANTEDPW@127.0.0.1:18591"),dict(provider="openai",api_key="abc\ndef"),dict(provider="openai",api_key="ключ")]:
    r=upd(**f); print("UPD",f,"->",json.dumps(r,ensure_ascii=False)[:200])
print(call("llm.set_enabled",{"enabled":True}))
r=upd(); print("valid ->",json.dumps(r)[:150])
print(call("llm.set_enabled",{"enabled":True}))
print(dictate("b.wav"))
fk.kill()
print("LOGSEC", [l for l in logs(300) if "PLANTEDPW" in l or "abc" in l])
print(stop_runtime(p))
