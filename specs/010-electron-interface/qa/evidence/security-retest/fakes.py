import http.server, socketserver, threading, json, time, sys
LOG="/private/tmp/claude-501/sec-retest/fakes.log"
def log(tag, h, body=b""):
    with open(LOG,"a") as f:
        f.write(json.dumps({"t":time.time(),"srv":tag,"line":h.requestline,"auth":h.headers.get("Authorization"),"host":h.headers.get("Host"),"body":body.decode("utf-8","replace")[:300]})+"\n")
class Q(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads=True; allow_reuse_address=True
def mk(tag, handler_fn, port):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version="HTTP/1.0"
        def log_message(self,*a): pass
        def _do(self):
            n=int(self.headers.get("Content-Length") or 0); b=self.rfile.read(n) if n else b""
            log(tag,self,b); handler_fn(self)
        do_GET=do_POST=_do
    s=Q(("127.0.0.1",port),H); threading.Thread(target=s.serve_forever,daemon=True).start()
OK=json.dumps({"choices":[{"message":{"content":"CLEANED"}}]}).encode()
def llm(h):
    h.send_response(200); h.send_header("Content-Type","application/json"); h.send_header("Content-Length",str(len(OK))); h.end_headers(); h.wfile.write(OK)
def redirect(h):
    h.send_response(302); h.send_header("Location","http://localhost:18353/stolen"); h.send_header("Content-Length","0"); h.end_headers()
def proxy(h):
    h.send_response(502); h.send_header("Content-Length","0"); h.end_headers()
def drip(h):
    h.send_response(200); h.send_header("Content-Type","application/json"); h.end_headers()
    for ch in OK.decode()+" "*100:
        try: h.wfile.write(ch.encode()); h.wfile.flush()
        except Exception: return
        time.sleep(1)
mk("llm",llm,18351); mk("redir",redirect,18352); mk("stolen",llm,18353); mk("proxy",proxy,18354); mk("drip",drip,18355)
time.sleep(3600)
