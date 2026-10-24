"""Driver for scripts/linux_container_check.sh: presses the hotkeys and reports."""

import json, os, subprocess, threading, time, urllib.request
env = dict(os.environ); env["DISPLAY"] = ":99"; os.environ["DISPLAY"] = ":99"
proc = subprocess.Popen(["python", "-m", "app.server", "--no-single-instance", "--no-stdin-watch", "--token", "t", "--port", "18970"],
    cwd="/work", env=env, stdout=subprocess.PIPE, stderr=open("/tmp/server.err", "w"), text=True)
print(proc.stdout.readline().strip())
def rpc(m, **kw):
    r = urllib.request.Request("http://127.0.0.1:18970/rpc", json.dumps({"method": m, "params": kw}).encode(), {"Authorization": "Bearer t"})
    return json.loads(urllib.request.urlopen(r, timeout=60).read())
events = []
def listen():
    r = urllib.request.urlopen("http://127.0.0.1:18970/events?token=t")
    name = None
    for raw in r:
        line = raw.decode().strip()
        if line.startswith("event: "): name = line[7:]
        elif line.startswith("data: "): events.append((name, json.loads(line[6:])))
threading.Thread(target=listen, daemon=True).start()
def last(n):
    xs = [e[1] for e in events if e[0] == n]
    return xs[-1] if xs else None
t0 = time.time()
while time.time() - t0 < 120 and not ((last("engine") or {}).get("provider") and (last("state") or {}).get("state") == "idle"):
    time.sleep(1)
print("engine:", last("engine"), "state:", last("state"))
print("devices:", rpc("devices.list"))
print("permissions:", rpc("permissions.status"))
subprocess.run(["xdotool", "key", "ctrl+F2"]); time.sleep(1.5)
print("state after Ctrl+F2:", last("state"))
subprocess.Popen(["paplay", "--device=nullsink", "/phrase.wav"]); time.sleep(3.5)
subprocess.run(["xdotool", "key", "ctrl+F3"])
t0 = time.time()
while time.time() - t0 < 40 and not [e for e in events if e[0] == "delivery"]:
    time.sleep(0.5)
levels = [e[1]["level"] for e in events if e[0] == "level"]
print("level events:", len(levels), "max: %.3f" % (max(levels) if levels else -1))
print("states:", [e[1]["state"] for e in events if e[0] == "state"])
print("delivery:", [e[1] for e in events if e[0] == "delivery"])
proc.terminate()
