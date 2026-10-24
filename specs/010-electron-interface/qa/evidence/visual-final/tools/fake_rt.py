import http.server, json, queue, threading, urllib.request, urllib.parse, sys
REAL='http://127.0.0.1:18502/rpc'
CFG={'language':'en','theme':'dark','palette':'gruvbox'}
DL={'phase':0}
FR={'on':False}
ML={'on':False}
PERM={'mic':'denied','acc':'untrusted','micb':'denied','post':'untrusted'}
subs=[]; lock=threading.Lock()
def real(m,p=None):
    req=urllib.request.Request(REAL,json.dumps({'jsonrpc':'2.0','id':1,'method':m,'params':p or {}}).encode(),{'Authorization':'Bearer devtoken','Content-Type':'application/json'})
    return json.loads(urllib.request.urlopen(req,timeout=10).read())
def push(name,data):
    with lock:
        for q in subs: q.put((name,json.dumps(data,ensure_ascii=False)))
class H(http.server.BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*a): pass
    def cors(self):
        self.send_header('Access-Control-Allow-Origin',self.headers.get('Origin','*')); self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type'); self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS'); self.send_header('Vary','Origin')
    def reply(self,obj,code=200):
        b=json.dumps(obj,ensure_ascii=False).encode(); self.send_response(code); self.cors(); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_OPTIONS(self):
        self.send_response(204); self.cors(); self.send_header('Content-Length','0'); self.end_headers()
    def do_POST(self):
        n=int(self.headers.get('Content-Length',0)); body=json.loads(self.rfile.read(n) or b'{}'); m=body.get('method')
        if m=='app.snapshot':
            r=real('app.snapshot'); r['result']['config']['ui'].update(CFG); r['result']['first_run']=FR['on']; return self.reply(r)
        if m=='app.events_ticket': return self.reply({'result':{'ticket':'x'}})
        if ML['on'] and m in ('models.state','models.list'):
            r=real(m,body.get('params'))
            if 'result' in r:
                r['result']['loading']=True; r['result']['active']='gigaam-v3-ctc'; r['result'].setdefault('cached',{})['gigaam-v3-ctc']=False; r['result']['state']='model_loading'
            return self.reply(r)
        if ML['on'] and m=='app.snapshot':
            r=real('app.snapshot'); r['result']['config']['ui'].update(CFG); r['result']['state']='model_loading'; r['result']['first_run']=False; return self.reply(r)
        if FR['on']:
            if m=='app.snapshot':
                r=real('app.snapshot'); r['result']['config']['ui'].update(CFG); r['result']['first_run']=True; r['result']['state']='idle'; return self.reply(r)
            if m=='firstrun.status': return self.reply({'result':{'show':True,'deferred':False,'complete':False,'candidate':'gigaam-v3-ctc','hotkeys':{'start':'ctrl+f8','stop':'ctrl+f9'}}})
            if m in ('models.download','models.select'):
                DL['phase']=1; return self.reply({'result':{'alias':'gigaam-v3-ctc','downloading':True,'state':'model_loading'}})
            if m=='models.cancel_load':
                DL['phase']=0; return self.reply({'result':{'loading':False}})
            if m in ('models.state','models.list'):
                r=real(m,body.get('params'))
                if 'result' in r:
                    r['result']['loading']=(DL['phase']==1); r['result']['active']='gigaam-v3-ctc'
                    r['result'].setdefault('cached',{})['gigaam-v3-ctc']=(DL['phase']==2)
                return self.reply(r)
        if m in ('permissions.status','permissions.refresh'): return self.reply({'result':{'platform':'darwin','applicable':True,'listen':False,'post_event':False,'microphone':PERM['mic'],'banners':{'accessibility':PERM['acc'],'microphone':PERM['micb'],'post_event':PERM['post']}}})
        try:
            r=real(m,body.get('params')); return self.reply(r)
        except Exception as e:
            return self.reply({'error':{'code':'x','message':str(e)}})
    def do_GET(self):
        u=urllib.parse.urlparse(self.path); q=urllib.parse.parse_qs(u.query)
        if u.path=='/health': return self.reply({'ok':True})
        if u.path=='/cfg':
            for k in CFG:
                if k in q: CFG[k]=q[k][0]
            push('settings',{}); return self.reply(CFG)
        if u.path=='/ml':
            ML['on']=q['on'][0]=='1'; return self.reply(ML)
        if u.path=='/dl':
            DL['phase']=int(q['phase'][0]); return self.reply(DL)
        if u.path=='/fr':
            FR['on']=q['on'][0]=='1'; return self.reply(FR)
        if u.path=='/perm':
            for k in PERM:
                if k in q: PERM[k]=q[k][0]
            return self.reply(PERM)
        if u.path=='/push':
            push(q['name'][0],json.loads(q.get('data',['{}'])[0])); return self.reply({'ok':1})
        if u.path=='/events':
            self.send_response(200); self.cors(); self.send_header('Content-Type','text/event-stream'); self.send_header('Cache-Control','no-store'); self.send_header('Connection','keep-alive'); self.end_headers()
            qu=queue.Queue()
            with lock: subs.append(qu)
            try:
                self.wfile.write(b': hi\n\n'); self.wfile.flush()
                while True:
                    try: name,data=qu.get(timeout=10)
                    except queue.Empty: self.wfile.write(b': ka\n\n'); self.wfile.flush(); continue
                    self.wfile.write(('event: %s\ndata: %s\n\n'%(name,data)).encode()); self.wfile.flush()
            except Exception: pass
            finally:
                with lock:
                    if qu in subs: subs.remove(qu)
            return
        self.reply({'error':'nf'},404)
http.server.ThreadingHTTPServer(('127.0.0.1',int(sys.argv[1])),H).serve_forever()
