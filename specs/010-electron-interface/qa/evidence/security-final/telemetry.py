import subprocess, time, sys, re, json
ROOT=int(sys.argv[1]); DUR=int(sys.argv[2])
def tree(root):
    out=subprocess.check_output(["ps","-axo","pid=,ppid="],text=True)
    kids={}
    for l in out.splitlines():
        p,pp=map(int,l.split()); kids.setdefault(pp,[]).append(p)
    seen=[root]; i=0
    while i<len(seen):
        seen+=kids.get(seen[i],[]); i+=1
    return seen
seen={}; allpids=set()
t0=time.time()
while time.time()-t0<DUR:
    pids=tree(ROOT); allpids|=set(pids)
    r=subprocess.run(["lsof","-nP","-i","-a","-p",",".join(map(str,pids))],capture_output=True,text=True)
    for l in r.stdout.splitlines()[1:]:
        parts=l.split(); name=" ".join(parts[8:]); cmd=parts[0]; pid=parts[1]
        m=re.search(r"->\[?([^\]\s]+?)\]?:(\d+)",name)
        if m:
            host=m.group(1)
            loop=host.startswith("127.") or host in ("::1","localhost")
        else:
            loop=None  # listening/unconnected
        key=(cmd,name.replace("(ESTABLISHED)","").strip())
        if loop is False: seen[(cmd,pid,name)]=seen.get((cmd,pid,name),0)+1
    time.sleep(0.5)
print("pids observed:",len(allpids)); print("non-loopback sockets:",json.dumps([list(k)+[v] for k,v in seen.items()]) if seen else "none")
