import socket, time, subprocess, sys, urllib.request, resource
resource.setrlimit(resource.RLIMIT_NOFILE,(10240,10240))
pid=int(open("server.pid").read())
def rss(): return int(subprocess.run(["ps","-o","rss=","-p",str(pid)],capture_output=True,text=True).stdout)//1024
def cpu(): return float(subprocess.run(["ps","-o","%cpu=","-p",str(pid)],capture_output=True,text=True).stdout)
def health():
    t=time.time()
    try: urllib.request.urlopen("http://127.0.0.1:18305/health",timeout=15).read(); return round(time.time()-t,3)
    except Exception as e: return type(e).__name__+":"+str(e)[:40]
print("before rss MB",rss(),"health",health())
socks=[]
for i in range(3000):
    try:
        s=socket.create_connection(("127.0.0.1",18305),timeout=5); socks.append(s)
    except Exception as e: print("connect fail at",i,e); break
print("opened",len(socks),"rss",rss(),"health with idle conns:",health())
time.sleep(12)
alive=0
for s in socks:
    s.setblocking(False)
    try:
        d=s.recv(1)
        if d==b"": pass
        else: alive+=1
    except BlockingIOError: alive+=1
    except Exception: pass
print("still open after 12 s (server did not close):",alive,"of",len(socks),"rss",rss(),"health:",health())
for s in socks: s.close()
t=time.time(); peak=0
while time.time()-t<12:
    peak=max(peak,cpu()); time.sleep(1)
print("after close: peak %cpu over 12 s",peak,"rss",rss(),"health",health())
