import urllib.request, json, sys, time
sys.path.insert(0,"."); from r import rpc
port=int(sys.argv[1]) if len(sys.argv)>1 else 18305
out=open("events.log","a")
while True:
    try:
        t=rpc("app.events_ticket",port=port)["result"]["ticket"]
        resp=urllib.request.urlopen(f"http://127.0.0.1:{port}/events?ticket={t}",timeout=60)
        for line in resp:
            out.write(line.decode("utf-8","replace")); out.flush()
    except Exception as e:
        out.write(f"# reconnect {e}\n"); out.flush(); time.sleep(1)
