import json, sys, urllib.request, urllib.error
def rpc(method, params=None, token="SECRETTOKEN123", port=18305, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/rpc", data=json.dumps({"method":method,"params":params or {}}).encode(), headers={"Authorization":"Bearer "+token,"Content-Type":"application/json",**(headers or {})})
    try:
        return json.load(urllib.request.urlopen(req, timeout=60))
    except urllib.error.HTTPError as e:
        return {"http":e.code,"body":e.read().decode()[:300]}
if __name__=="__main__":
    print(json.dumps(rpc(sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv)>2 else {}), ensure_ascii=False, indent=1)[:4000])
