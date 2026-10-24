import http.server, socketserver, json, time, threading
LOG="/private/tmp/claude-501/sec-final/out/fake.log"
class H(http.server.BaseHTTPRequestHandler):
    protocol_version="HTTP/1.0"
    def log_message(self,*a): pass
    def do_POST(self):
        n=int(self.headers.get("Content-Length") or 0); b=self.rfile.read(n)
        open(LOG,"a").write(json.dumps({"line":self.requestline,"auth":self.headers.get("Authorization"),"body":b.decode()[:300]})+"\n")
        body=json.dumps({"choices":[{"message":{"content":"Обработанный текст: "+json.loads(b)["messages"][-1]["content"]}}]}).encode()
        self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    do_GET=do_POST
class S(socketserver.ThreadingMixIn,http.server.HTTPServer): daemon_threads=True; allow_reuse_address=True
S(("127.0.0.1",18562),H).serve_forever()
