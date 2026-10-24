import http.server, sys, os
CSP="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src http://127.0.0.1:*; img-src 'self' data:; font-src 'self'; object-src 'none'"
class H(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Content-Security-Policy',CSP); self.send_header('Cache-Control','no-store'); super().end_headers()
    def log_message(self,*a): pass
os.chdir(sys.argv[1]); http.server.ThreadingHTTPServer(('127.0.0.1',int(sys.argv[2])),H).serve_forever()
