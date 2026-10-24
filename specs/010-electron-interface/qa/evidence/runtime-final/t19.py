from l2t import *
import json, os, http.client, socket, threading
def J(x): return json.dumps(x,ensure_ascii=False)[:200]
d=R+"/fp2"
p,line=start(d,extra=("--allow-origin","l2t-app://app","--dev","--dev-port","5801")); wait_idle()
def req(method,path,headers=None,body=None,timeout=5):
    try:
        c=http.client.HTTPConnection("127.0.0.1",PORT,timeout=timeout); c.request(method,path,body=body,headers=headers or {}); r=c.getresponse(); b=r.read(300); return r.status,dict((k,v) for k,v in r.getheaders() if k.lower().startswith("access-control")),b[:50]
    except Exception as e: return "ERR",repr(e)[:50]
for o in ("null","file://","l2t-app://app","http://evil.example","http://127.0.0.1:5801","http://localhost:5801","http://127.0.0.1:5802"):
    print("Origin",o,"health",req("GET","/health",{"Origin":o})[:2],"preflight",req("OPTIONS","/rpc",{"Origin":o})[:2])
# SEC-R1: 110 trickling connections
socks=[]
for i in range(110):
    s=socket.create_connection(("127.0.0.1",PORT)); s.sendall(b"POST /rpc HTTP/1.1\r\nHost: 127.0.0.1\r\nX-a: "); socks.append(s)
t0=time.time(); res=[]
stop=False
def trickle():
    while not stop:
        for s in socks:
            try: s.send(b"a")
            except Exception: pass
        time.sleep(3)
th=threading.Thread(target=trickle,daemon=True); th.start()
while time.time()-t0<40:
    st=req("GET","/health",timeout=4)[0]; rp=call("app.ping",timeout=4)
    res.append((round(time.time()-t0,1),st,"pong" if rp.get("result") else str(rp)[:40])); time.sleep(2)
stop=True
print("probes",res)
print("ok count",sum(1 for r in res if r[1]==200 and r[2]=="pong"),"of",len(res))
alive=0
for s in socks:
    try:
        s.settimeout(0.2); d_=s.recv(10); 
        if d_!=b"": alive+=1
    except socket.timeout: alive+=1
    except Exception: pass
print("trickle sockets still open:",alive)
[s.close() for s in socks]
# nested json
body=b'{"method":"app.ping","params":'+b'['*100000+b']'*100000+b'}'
print("nested",req("POST","/rpc",{"Authorization":"Bearer devtoken","Content-Type":"application/json"},body)[:3])
# legit sizes
print("3.9MB",req("POST","/rpc",{"Authorization":"Bearer devtoken","Content-Type":"application/json"},json.dumps({"method":"app.ping","params":{"x":"a"*3900000}}))[:1])
print("5MB",req("POST","/rpc",{"Authorization":"Bearer devtoken","Content-Type":"application/json"},json.dumps({"method":"app.ping","params":{"x":"a"*5100000}}))[:1])
print(call("app.ping"))
print(stop_runtime(p))
