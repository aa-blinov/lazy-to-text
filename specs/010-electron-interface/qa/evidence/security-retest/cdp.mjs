const [,, match, expr] = process.argv;
const targets = await (await fetch('http://127.0.0.1:18365/json')).json();
const t = targets.find(x => x.url.includes(match));
if (!t) { console.log('NO TARGET', targets.map(x=>x.url)); process.exit(1); }
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener('open', r));
let id = 0; const pending = new Map();
ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id);} });
const send = (method, params={}) => new Promise(r => { const i=++id; pending.set(i, r); ws.send(JSON.stringify({id:i, method, params})); });
const r = await send('Runtime.evaluate', {expression: expr, awaitPromise: true, returnByValue: true});
console.log(JSON.stringify(r.result.result?.value ?? r.result, null, 1));
ws.close(); process.exit(0);
