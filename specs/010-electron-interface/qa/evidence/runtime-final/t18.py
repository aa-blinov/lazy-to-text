from l2t import *
import json, os, http.client
def J(x): return json.dumps(x,ensure_ascii=False)[:200]
d=R+"/fp2"; shutil.rmtree(d,ignore_errors=True)
p,line=start(d); wait_idle()
out=R+"/outdir2"; shutil.rmtree(out,ignore_errors=True); os.makedirs(out)
print("restore ok",J(call("history.restore",{"entry":{"timestamp":1.7e9,"text":"hi there","duration":1.0}})))
open(out+"/h.txt","w").write("ORIG")
print("export exists",J(call("history.export",{"path":out+"/h.txt"})))
print("export .. trick",J(call("history.export",{"path":out+"/nodir/../h.txt"})), open(out+"/h.txt").read()[:30])
print("export overwrite",J(call("history.export",{"path":out+"/h.txt","overwrite":True})))
print("export over config",J(call("history.export",{"path":d+"/data/config.yaml","overwrite":True})))
# SEC-R3 / R6 / origins
def req(method,path,headers=None,body=None):
    c=http.client.HTTPConnection("127.0.0.1",PORT,timeout=5); c.request(method,path,body=body,headers=headers or {}); r=c.getresponse(); b=r.read(300); return r.status,dict((k,v) for k,v in r.getheaders() if k.lower().startswith("access-control")),b[:60]
for o in ("null","file://","l2t-app://app","http://evil.example","http://127.0.0.1:5801"):
    print("Origin",o,"health",req("GET","/health",{"Origin":o}),"rpc",req("POST","/rpc",{"Origin":o,"Authorization":"Bearer devtoken","Content-Type":"application/json"},json.dumps({"method":"app.ping"})), "preflight",req("OPTIONS","/rpc",{"Origin":o,"Access-Control-Request-Method":"POST"})[0])
print("events ?token=",req("GET","/events?token=devtoken")[0])
print("events header", end=" ")
c=http.client.HTTPConnection("127.0.0.1",PORT,timeout=3); c.request("GET","/events",headers={"Authorization":"Bearer devtoken"}); r=c.getresponse(); print(r.status); c.close()
t=call("app.events_ticket")["result"]["ticket"]
print("ticket once",req("GET","/events?ticket="+t)[0] if False else "")
c=http.client.HTTPConnection("127.0.0.1",PORT,timeout=3); c.request("GET","/events?ticket="+t); r=c.getresponse(); print("ticket first",r.status); c.close()
c=http.client.HTTPConnection("127.0.0.1",PORT,timeout=3); c.request("GET","/events?ticket="+t); r=c.getresponse(); print("ticket reuse",r.status); c.close()
print("rpc ?token=",req("POST","/rpc?token=devtoken",{"Content-Type":"application/json"},json.dumps({"method":"app.ping"}))[0])
print("ticket in rpc",req("POST","/rpc?ticket=%s"%call("app.events_ticket")["result"]["ticket"],{"Content-Type":"application/json"},json.dumps({"method":"app.ping"}))[0])
# stream cap
cs=[]
for i in range(16):
    tk=call("app.events_ticket")["result"]["ticket"]
    c=http.client.HTTPConnection("127.0.0.1",PORT,timeout=3); c.request("GET","/events?ticket="+tk); r=c.getresponse(); cs.append((i,r.status))
print("streams",cs[10:])
print(call("app.ping"))
print(stop_runtime(p))
