const [,, from, url] = process.argv;
const targets = await (await fetch('http://127.0.0.1:18565/json')).json();
const t = targets.find(x => x.url.includes(from));
if(!t){console.log('NO TARGET',targets.map(x=>x.url));process.exit(1)}
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener('open', r));
let id=0; const p=new Map(); ws.addEventListener('message', e=>{const m=JSON.parse(e.data); if(m.id&&p.has(m.id)){p.get(m.id)(m);p.delete(m.id)}});
const send=(method,params={})=>new Promise(r=>{const i=++id;p.set(i,r);ws.send(JSON.stringify({id:i,method,params}))});
console.log(JSON.stringify((await send('Page.navigate',{url})).result)); ws.close(); process.exit(0);
