import sys,time,urllib.request,json; sys.path.insert(0,"/private/tmp/claude-501/sec-final/t")
from lib import *
P,T=open("/private/tmp/claude-501/sec-final/out/conn.env").read().split()
out=open("/private/tmp/claude-501/sec-final/out/events.log","a")
while True:
    try:
        t=rpc("app.events_ticket",port=int(P),tok=T)["result"]["ticket"]
        for line in urllib.request.urlopen(f"http://127.0.0.1:{P}/events?ticket={t}",timeout=90):
            out.write(line.decode("utf-8","replace")); out.flush()
    except Exception as e:
        out.write(f"# reconnect {e}\n"); out.flush(); time.sleep(1)
