import json, urllib.request, urllib.error
PORT=18505; TOK="devtoken"
def rpc(method, params=None, port=None, tok=None, headers=None):
    req=urllib.request.Request(f"http://127.0.0.1:{port or PORT}/rpc", data=json.dumps({"method":method,"params":params or {}}).encode(),
        headers={"Authorization":"Bearer "+(tok or TOK),"Content-Type":"application/json",**(headers or {})})
    try:
        with urllib.request.urlopen(req,timeout=20) as r: return json.loads(r.read())
    except urllib.error.HTTPError as e: return {"http":e.code,"body":e.read().decode()[:200]}
def get(path, port=None, headers=None, tok=None):
    h=dict(headers or {})
    if tok: h["Authorization"]="Bearer "+tok
    req=urllib.request.Request(f"http://127.0.0.1:{port or PORT}{path}",headers=h)
    try:
        with urllib.request.urlopen(req,timeout=10) as r: return r.status, dict(r.headers), r.read(200)
    except urllib.error.HTTPError as e: return e.code, dict(e.headers), e.read(200)
