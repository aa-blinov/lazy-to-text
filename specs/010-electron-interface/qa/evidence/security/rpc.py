import json, sys, urllib.request
def rpc(method, params=None, token="SECRETTOKEN123", port=18105, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/rpc", data=json.dumps({"method":method,"params":params or {}}).encode(), headers={"Authorization":"Bearer "+token,"Content-Type":"application/json",**(headers or {})})
    return json.load(urllib.request.urlopen(req, timeout=60))
if __name__=="__main__":
    print(json.dumps(rpc(sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv)>2 else {}), ensure_ascii=False, indent=1)[:3000])
