import json, urllib.request, os, subprocess, time, sys, shutil, socket, threading
WT="/Users/justcomex/Documents/Проекты/pet/lazy-to-text/.claude/worktrees/llm-reasoning-tokens-config-624055"
R="/private/tmp/claude-501/-Users-justcomex-Documents---------pet-lazy-to-text--claude-worktrees-llm-reasoning-tokens-config-624055/36839e4b-2af5-4aaf-8ca3-57be3ba743eb/scratchpad/rt3"
NOPROXY={'HTTPS_PROXY':'http://127.0.0.1:9','HTTP_PROXY':'http://127.0.0.1:9','https_proxy':'http://127.0.0.1:9','http_proxy':'http://127.0.0.1:9','NO_PROXY':'127.0.0.1,localhost','no_proxy':'127.0.0.1,localhost','HF_HUB_DISABLE_TELEMETRY':'1','HF_HUB_OFFLINE':'1'}
PORT=18501; TOKEN="devtoken"
def raw(method, params=None, port=PORT, token=TOKEN, timeout=30, body=None, headers=None, path="/rpc"):
    data = body if body is not None else json.dumps({"method":method,"params":params if params is not None else {}}).encode()
    h={"Authorization":"Bearer "+token,"Content-Type":"application/json"}
    if headers: h.update(headers)
    req=urllib.request.Request(f"http://127.0.0.1:{port}{path}",data=data,headers=h,method="POST")
    try:
        r=urllib.request.urlopen(req,timeout=timeout); return r.status, r.read().decode()
    except urllib.error.HTTPError as e: return e.code, e.read().decode()
    except Exception as e: return -1, repr(e)
def call(method, params=None, **kw):
    s,b=raw(method,params,**kw)
    try: return json.loads(b)
    except Exception: return {"http":s,"body":b}
def start(d, extra=(), env=None, wipe=False, model=True, hub=True):
    if wipe and os.path.exists(d): shutil.rmtree(d)
    os.makedirs(d+"/data", exist_ok=True)
    if hub and not os.path.exists(d+"/mroot/hub"):
        os.makedirs(d+"/mroot",exist_ok=True); os.symlink(R+"/hub", d+"/mroot/hub")
    cfg=d+"/data/config.yaml"
    if hub and not os.path.exists(cfg):
        open(cfg,"w").write(f"storage:\n  models_dir: {d}/mroot\nclipboard:\n  auto_paste: false\naudio_feedback:\n  enabled: false\n")
    e=dict(os.environ); e.update(NOPROXY); e.update(env or {})
    p=subprocess.Popen([WT+"/.venv/bin/python","-m","app.server","--no-single-instance","--no-stdin-watch","--token",TOKEN,"--port",str(PORT),"--data-dir",d+"/data",*extra],cwd=WT,stdout=subprocess.PIPE,stderr=open(d+"/stderr.log","a"),env=e)
    line=p.stdout.readline().decode(); return p,line
def wait_idle(timeout=90):
    t=time.time()
    while time.time()-t<timeout:
        r=call("app.snapshot")
        if "result" in r and r["result"]["state"]=="idle" and r["result"]["engine"]["provider"]: return r["result"]
        time.sleep(0.5)
def stop_runtime(p=None):
    call("app.quit",timeout=5)
    t=time.time()
    while time.time()-t<20:
        if p is not None and p.poll() is not None: return p.returncode
        s,_=raw("app.ping",timeout=2)
        if s==-1 and p is None: return None
        time.sleep(0.3)
    return "STILL RUNNING"
EV=[]
def ticket():
    return call("app.events_ticket")["result"]
def sse():
    while True:
        try:
            t=ticket(); tk=t.get("ticket") if isinstance(t,dict) else t
            s=socket.create_connection(("127.0.0.1",PORT))
            s.sendall(f"GET /events?ticket={tk} HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\n\r\n".encode())
            buf=b""
            while True:
                d=s.recv(65536)
                if not d: break
                buf+=d
                while b"\n\n" in buf:
                    blk,_,buf=buf.partition(b"\n\n")
                    n=dt=None
                    for l in blk.decode(errors="replace").split("\n"):
                        if l.startswith("event: "): n=l[7:]
                        if l.startswith("data: "): dt=l[6:]
                    if n: EV.append((time.time(),n,dt))
        except Exception: time.sleep(0.5)
def start_sse(): threading.Thread(target=sse,daemon=True).start()
def dictate(wav="b.wav", pre=0.6, speak=3.5, wait=90, play=True):
    n0=len(EV)
    r=call("recording.toggle"); time.sleep(pre)
    if play: subprocess.Popen(["afplay",R+"/wav/"+wav])
    time.sleep(speak)
    r2=call("recording.stop")
    t=time.time(); st=None
    while time.time()-t<wait:
        st=call("app.snapshot")["result"]["state"]
        if st=="idle" and time.time()-t>0.5: break
        time.sleep(0.2)
    time.sleep(0.5)
    ev=[(n,d) for (_,n,d) in EV[n0:] if n in("delivery","history","state")]
    return {"toggle":r,"stop":r2,"final":st,"took":round(time.time()-t,1),"events":ev}
def logs(n=10): return [x["message"] for x in call("logs.list")["result"]["records"][-n:]]
