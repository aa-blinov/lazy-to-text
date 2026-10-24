import http.server, socketserver, threading, json, time
class Q(socketserver.ThreadingMixIn, http.server.HTTPServer): daemon_threads=True; allow_reuse_address=True
def mk(port, fn):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version="HTTP/1.0"
        def log_message(self,*a): pass
        def do_POST(self):
            n=int(self.headers.get("Content-Length") or 0); self.rfile.read(n); fn(self)
    threading.Thread(target=Q(("127.0.0.1",port),H).serve_forever,daemon=True).start()
def big(h):
    h.send_response(200); h.send_header("Content-Type","application/json"); h.end_headers()
    try:
        h.wfile.write(b'{"choices":[{"message":{"content":"');
        for _ in range(200): h.wfile.write(b"a"*100000)
    except Exception: pass
def evil(h):
    b=b'HTTP 401 <img onerror=alert(1)> Authorization: Bearer sk-PLANTED-SECRET-AAA /Users/justcomex/secret'
    h.send_response(401); h.send_header("Content-Length",str(len(b))); h.end_headers(); h.wfile.write(b)
def notjson(h):
    b=b'SECRET-REPLY-BODY-12345 not json'
    h.send_response(200); h.send_header("Content-Length",str(len(b))); h.end_headers(); h.wfile.write(b)
def empty(h):
    b=json.dumps({"choices":[{"message":{"content":""}}]}).encode(); h.send_response(200); h.send_header("Content-Length",str(len(b))); h.end_headers(); h.wfile.write(b)
def hang(h): time.sleep(60)
for p,f in [(18356,big),(18357,evil),(18358,notjson),(18359,empty),(18360,hang)]: mk(p,f)
time.sleep(3600)
