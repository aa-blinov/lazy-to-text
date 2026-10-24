import socket, time, urllib.request
socks=[socket.create_connection(("127.0.0.1",18305)) for _ in range(110)]
for s in socks: s.sendall(b"POST /rpc HTTP/1.1\r\nHost: 127.0.0.1\r\nX-a: ")
def health():
    t=time.time()
    try: urllib.request.urlopen("http://127.0.0.1:18305/health",timeout=5).read(); return "ok %.2fs"%(time.time()-t)
    except Exception as e: return type(e).__name__
t0=time.time()
for rnd in range(8):
    time.sleep(5)
    for s in socks:
        try: s.sendall(b"a")
        except Exception: pass
    print(f"t={int(time.time()-t0)}s health:",health())
for s in socks: s.close()
time.sleep(1); print("after close:",health())
