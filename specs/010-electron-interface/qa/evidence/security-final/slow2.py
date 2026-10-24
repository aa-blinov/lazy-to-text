import socket, time, sys, json, urllib.request, threading
PORT=int(sys.argv[1]); MODE=sys.argv[2]; N=int(sys.argv[3]); DUR=int(sys.argv[4]); PERIOD=float(sys.argv[5])
def mk():
    s=socket.create_connection(("127.0.0.1",PORT))
    if MODE=="hdr": s.sendall(b"POST /rpc HTTP/1.1\r\nHost: 127.0.0.1\r\nX-a: ")
    elif MODE=="body": s.sendall(b"POST /rpc HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer devtoken\r\nContent-Length: 5000\r\n\r\n{")
    elif MODE=="get": s.sendall(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nX-a: ")
    return s
socks=[mk() for _ in range(N)]
stop=False
def tick():
    global socks
    while not stop:
        time.sleep(PERIOD)
        for i,s in enumerate(socks):
            try: s.sendall(b"a")
            except Exception:
                try: socks[i]=mk()   # reconnect when cut
                except Exception: pass
threading.Thread(target=tick,daemon=True).start()
def health():
    t=time.time()
    try: urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health",timeout=5).read(); return "ok %.2f"%(time.time()-t)
    except Exception as e: return type(e).__name__
def rpc():
    t=time.time()
    try:
        r=urllib.request.Request(f"http://127.0.0.1:{PORT}/rpc",data=b'{"method":"app.snapshot"}',headers={"Authorization":"Bearer devtoken"})
        urllib.request.urlopen(r,timeout=5).read(); return "ok %.2f"%(time.time()-t)
    except Exception as e: return type(e).__name__
t0=time.time(); res=[]
while time.time()-t0<DUR:
    time.sleep(2.5); h=health(); r=rpc(); res.append((h,r)); print(f"t={int(time.time()-t0)}s health={h} rpc={r}",flush=True)
stop=True
for s in socks:
    try: s.close()
    except Exception: pass
time.sleep(1); print("after close:",health(),rpc())
print("ok health %d/%d, ok rpc %d/%d"%(sum(a.startswith('ok') for a,_ in res),len(res),sum(b.startswith('ok') for _,b in res),len(res)))
