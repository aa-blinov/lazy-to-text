const urls = process.argv.slice(2);
const targets = await (await fetch('http://127.0.0.1:18365/json')).json();
const t = targets.find(x => x.url.startsWith('l2t-app://app/index.html')) ;
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener('open', r));
let id=0; const p=new Map(); ws.addEventListener('message', e=>{const m=JSON.parse(e.data); if(m.id&&p.has(m.id)){p.get(m.id)(m);p.delete(m.id)}});
const send=(method,params={})=>new Promise(r=>{const i=++id;p.set(i,r);ws.send(JSON.stringify({id:i,method,params}))});
await send('Page.enable');
for (const u of urls) {
  const nav = await send('Page.navigate',{url:'l2t-app://app'+u});
  await new Promise(r=>setTimeout(r,1200));
  const r = await send('Runtime.evaluate',{expression:"JSON.stringify({href:location.href,type:document.contentType,len:document.documentElement.outerHTML.length,body:(document.body&&document.body.innerText||'').slice(0,40)})",returnByValue:true});
  console.log(u.padEnd(52), nav.result.errorText||'', r.result.result?.value ?? JSON.stringify(r.result).slice(0,100));
}
await send('Page.navigate',{url:'l2t-app://app/index.html'});
ws.close(); process.exit(0);
