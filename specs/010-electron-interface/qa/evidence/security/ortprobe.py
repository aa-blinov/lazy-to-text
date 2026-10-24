import sys, os, time, subprocess, sqlite3, glob
import onnxruntime as ort
s = ort.InferenceSession(sys.argv[1], providers=["CPUExecutableProvider"] if False else ["CPUExecutionProvider"])
time.sleep(float(sys.argv[2]))
home=os.environ["HOME"]
d=home+"/Library/Application Support/Microsoft/DeveloperTools/.onnxruntime"
print("deviceid exists:", os.path.exists(d+"/deviceid"))
try:
    c=sqlite3.connect(d+"/onnxruntime.db"); print("queued events:", c.execute("select count(*), max(retry_count) from events").fetchall())
except Exception as e: print("db err",e)
out=subprocess.run(f"lsof -nP -p {os.getpid()} -a -i",shell=True,capture_output=True,text=True).stdout
print("sockets:", [l.split()[-2:] for l in out.splitlines()[1:]] or "none")
