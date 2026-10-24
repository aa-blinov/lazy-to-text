from l2t import *
import json, os
def J(x): return json.dumps(x,ensure_ascii=False)[:230]
d=R+"/fp"; shutil.rmtree(d,ignore_errors=True)
p,line=start(d); wait_idle(); start_sse(); time.sleep(.5)
out=R+"/outdir"; shutil.rmtree(out,ignore_errors=True); os.makedirs(out)
S=lambda path,**k: J(call("files.save_text",dict({"path":path,"text":"hello"},**k)))
print("new .txt",S(out+"/a.txt"))
print("exists no overwrite",S(out+"/a.txt"));
print("overwrite true",S(out+"/a.txt",overwrite=True), open(out+"/a.txt").read())
print("overwrite 'yes'",S(out+"/a.txt",overwrite="yes"))
print("overwrite 1",S(out+"/a.txt",overwrite=1))
open(out+"/victim.txt","w").write("ORIGINAL")
print("via ..",S(out+"/sub/../victim.txt")); os.makedirs(out+"/real"); os.symlink(out+"/real",out+"/linkdir"); open(out+"/real/v2.txt","w").write("ORIG2")
print("via linkdir",S(out+"/linkdir/v2.txt"), open(out+"/real/v2.txt").read())
print("case-different existing",S(out+"/VICTIM.TXT"), os.listdir(out))
print("relative",S("rel.txt"),S("../x.txt"),S("~/x.txt"))
for bad in ("/Applications/zz.txt","/Library/zz.txt","/System/zz.txt","/usr/local/zz.txt","/etc/zz.txt",WT+"/app/zz.txt",WT+"/.venv/bin/zz.txt", WT+"/.venv/lib/zz.txt", os.path.expanduser("~/Library/LaunchAgents/zz.txt"), os.path.expanduser("~/Library/Caches/LazyToText/zz.txt"), d+"/data/zz.txt", d+"/data/logs/zz.txt", d+"/data/config.yaml", "/Applications/Foo.app/Contents/Resources/zz.txt", d+"/Foo.app/x.txt"):
    r=S(bad); print("deny?",bad.replace(R,"R")[:80],r[:110]);
    try: os.remove(bad)
    except Exception: pass
print("exts",[ (e,S(out+"/e."+e)[:60]) for e in ("md","sh","plist","json","docx","TXT","txt.sh","")])
print("fifo/dir", S(out), S(out+"/")[:80])
# history.export
call("settings.set",{"key":"audio_feedback.enabled","value":False})
print("export new",J(call("history.export",{"path":out+"/h.txt"})))
print("export exists",J(call("history.export",{"path":out+"/h.txt"})))
print("export overwrite",J(call("history.export",{"path":out+"/h.txt","overwrite":True})))
print("export over config",J(call("history.export",{"path":d+"/data/config.yaml","overwrite":True})))
print("export over rc",J(call("history.export",{"path":os.path.expanduser("~/.zshrc.txt")})));
print("transcribe relative",J(call("files.transcribe",{"path":"rel.wav"})))
# restore junk
for e in ({"timestamp":1e300,"text":"x"},{"timestamp":float("nan"),"text":"x"},{"timestamp":1.0,"text":""},{"timestamp":1.0,"text":"x"*3000000},{"timestamp":1.7e9,"text":"ok","duration":-5},{"timestamp":"abc","text":"x"}):
    r=call("history.restore",{"entry":e}); print("restore",J(e)[:50],J(r)[:120])
print("list ok",J(call("history.list"))[:120])
print(stop_runtime(p))
