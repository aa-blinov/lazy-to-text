from l2t import *
import json, yaml
fk=subprocess.Popen([sys.executable,R+"/fakellm.py","18591",R+"/fake.log"])
srv={}
for m,port in (("garbage",18592),("chunk",18593),("drip",18594),("silent",18595)):
    srv[m]=subprocess.Popen([sys.executable,R+"/rawsrv.py",str(port),m])
time.sleep(1)
def run(name, llm, secret=None):
    d=R+"/"+name
    shutil.rmtree(d,ignore_errors=True)
    os.makedirs(d+"/data"); os.symlink(R+"/hub",d+"/hub")
    cfg={"storage":{"models_dir":d+"/hub/.."},"clipboard":{"auto_paste":False},"audio_feedback":{"enabled":False},"llm":dict({"enabled":True,"provider":"ollama","model":"x","api_key":"","mode":"clean","timeout_s":6,"reasoning_effort":"","max_tokens":0},**llm)}
    yaml.safe_dump(cfg,open(d+"/data/config.yaml","w"),allow_unicode=True)
    p,line=start(d,hub=False)
    wait_idle(); 
    if not EV or True: start_sse(); time.sleep(0.5)
    t0=time.time()
    res=dictate("b.wav",wait=40)
    deliv=[e for e in res["events"] if e[0]=="delivery"]
    applog=open(d+"/data/logs/app.log").read() if os.path.exists(d+"/data/logs/app.log") else ""
    sec=[]
    if secret: sec=[(s,applog.count(s),sum(1 for l in logs(500) if s in l)) for s in secret]
    print(name, "final",res["final"],"took",res["took"],"deliv",json.dumps(deliv,ensure_ascii=False)[:230],"secrets(applog,logs.list)",sec, "history", len(call("history.list")["result"]["entries"]) if "result" in call("history.list") else call("history.list"))
    EV.clear()
    stop_runtime(p)
    time.sleep(0.5)
try:
    run("v1",{"base_url":"myserver"})
    run("v2",{"base_url":"127.0.0.1"})
    run("v3",{"base_url":"http://127.0.0.1:18591/a b"})
    run("v4",{"base_url":"http://127.0.0.1:18591/ё"})
    run("v5",{"base_url":"http://[::1"})
    run("v6",{"provider":"openai","base_url":"http://127.0.0.1:18591","api_key":"abc\ndef"},["abc","def"])
    run("v7",{"provider":"openai","base_url":"http://127.0.0.1:18591","api_key":"ключSECRETKEY"},["ключSECRETKEY"])
    run("v8",{"base_url":"http://user:PLANTEDPW@127.0.0.1:18591"},["PLANTEDPW"])
    run("v9",{"base_url":"http://127.0.0.1:18592"})
    run("v10",{"base_url":"http://127.0.0.1:18593"})
    run("v11",{"base_url":"http://127.0.0.1:18594","timeout_s":3})
    run("v12",{"base_url":"http://127.0.0.1:18595","timeout_s":3})
finally:
    fk.kill(); [s.kill() for s in srv.values()]
