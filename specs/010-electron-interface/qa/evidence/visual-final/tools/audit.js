window.__audit = function (opts) {
  opts = opts || {};
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  function rgba(c) {
    cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c; cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255];
  }
  function lum(r) { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r[0]) + 0.7152 * f(r[1]) + 0.0722 * f(r[2]); }
  function ratio(a, b) { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
  function over(top, bot) { const a = top[3]; return [top[0] * a + bot[0] * (1 - a), top[1] * a + bot[1] * (1 - a), top[2] * a + bot[2] * (1 - a), 1]; }
  function bgOf(el) {
    const chain = []; for (let e = el; e; e = e.parentElement) chain.push(e);
    let bg = rgba(getComputedStyle(document.documentElement).backgroundColor); if (bg[3] < 1) bg = [255, 255, 255, 1];
    for (const e of chain.reverse()) { const c = rgba(getComputedStyle(e).backgroundColor); if (c[3] > 0) bg = over(c, bg); }
    return bg;
  }
  function opac(el) { let o = 1; for (let e = el; e; e = e.parentElement) o *= Number(getComputedStyle(e).opacity); return o; }
  function visible(el) { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; }
  const out = { w: innerWidth, h: innerHeight, mode: document.documentElement.dataset.mode, theme: document.documentElement.dataset.theme, fs: getComputedStyle(document.documentElement).fontSize, overflow: [], offscreen: [], truncated: [], lowContrast: [], disabledContrast: [], tinyTargets: [] };
  const de = document.documentElement;
  if (de.scrollWidth > innerWidth + 1) out.overflow.push({ el: 'html', sw: de.scrollWidth, cw: innerWidth });
  const all = [...document.querySelectorAll('body *')];
  for (const el of all) {
    if (!visible(el) || el.matches('.sr-only')) continue;
    const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
    if ((cs.overflowX === 'auto' || cs.overflowX === 'scroll' || el.tagName === 'MAIN') && el.scrollWidth > el.clientWidth + 1) out.overflow.push({ el: el.tagName + '.' + String(el.className).slice(0, 50), sw: el.scrollWidth, cw: el.clientWidth });
    if (r.right > innerWidth + 1 && !el.closest('[aria-hidden=true]') && cs.position !== 'fixed') out.offscreen.push(el.tagName + '.' + String(el.className).slice(0, 40) + ' r=' + Math.round(r.right) + ' "' + (el.textContent || '').trim().slice(0, 30) + '"');
    const ell = cs.textOverflow === 'ellipsis' || cs.webkitLineClamp !== 'none' && cs.webkitLineClamp;
    if ((ell || cs.overflow === 'hidden') && (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1) && (el.textContent || '').trim()) {
      const titled = el.closest('[title]') || el.getAttribute('aria-label') || el.querySelector('[title]');
      if (ell) out.truncated.push({ el: el.tagName + '.' + String(el.className).slice(0, 40), text: el.textContent.trim().slice(0, 40), sw: el.scrollWidth, cw: el.clientWidth, sh: el.scrollHeight, ch: el.clientHeight, titled: !!titled });
      else if (!titled && el.scrollWidth > el.clientWidth + 1) out.truncated.push({ el: el.tagName + '.' + String(el.className).slice(0, 40), text: el.textContent.trim().slice(0, 40), sw: el.scrollWidth, cw: el.clientWidth, hidden: true, titled: false });
    }
    // direct text
    const direct = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (direct) {
      const fg = rgba(cs.color); const bg = bgOf(el); const o = opac(el);
      const eff = over([fg[0], fg[1], fg[2], fg[3] * o], bg);
      const cr = ratio(eff, bg); const size = parseFloat(cs.fontSize); const bold = Number(cs.fontWeight) >= 700;
      const need = size >= 24 || (size >= 18.66 && bold) ? 3 : 4.5;
      const dis = el.closest('[disabled],[aria-disabled=true]');
      const rec = { text: el.textContent.trim().slice(0, 30), cr: Math.round(cr * 100) / 100, need, size, el: el.tagName + '.' + String(el.className).slice(0, 30) };
      (out.samples = out.samples || []).push(rec.cr + ' ' + rec.text.slice(0,12));
      if (dis) out.disabledContrast.push(rec); else if (cr < need) out.lowContrast.push(rec);
    }
    if (['BUTTON', 'A', 'INPUT', 'SELECT', '[role=button]'].includes(el.tagName) && (r.height < 24 || r.width < 24) && !el.closest('[aria-hidden=true]') && el.type !== 'hidden') out.tinyTargets.push(el.tagName + ' ' + Math.round(r.width) + 'x' + Math.round(r.height) + ' "' + (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 20) + '"');
  }
  out.rawKeys = (document.body.innerText.match(/\b[a-z]+\.[a-z_]+\.[a-z_]+\b|\{[a-z]+\}|undefined|\[object/g) || []).slice(0, 5);
  out.main = (() => { const m = document.querySelector('main'); return m ? { sw: m.scrollWidth, cw: m.clientWidth, sh: m.scrollHeight, ch: m.clientHeight } : null; })();
  return out;
};
window.__set = function (o) {
  const r = document.documentElement;
  if (o.theme) r.dataset.theme = o.theme; if (o.mode) r.dataset.mode = o.mode;
  if (o.scale !== undefined) r.style.fontSize = o.scale === 1 ? '' : o.scale * 100 + '%';
  return 'ok';
};
window.__rpc = async function (m, p) { const r = await fetch('http://127.0.0.1:18502/rpc', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer devtoken' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: m, params: p || {} }) }); return await r.json(); };
'installed'
window.__matrix = async function (opts) {
  opts = opts || {};
  const palettes = opts.palettes || ['gruvbox', 'github', 'dracula', 'nord', 'solarized', 'catppuccin'];
  const modes = opts.modes || ['light', 'dark'];
  const scales = opts.scales || [1];
  if (!document.getElementById('__nt')) { const s = document.createElement('style'); s.id = '__nt'; s.textContent = '*,*::before,*::after{transition:none!important;animation:none!important}'; document.head.appendChild(s); }
  const agg = { combos: 0, overflow: {}, offscreen: {}, truncatedNoTitle: {}, low: {}, disabledLow: {}, tiny: {}, raw: {} };
  for (const sc of scales) for (const p of palettes) for (const m of modes) {
    window.__set({ theme: p, mode: m, scale: sc });
    await new Promise((r) => setTimeout(r, opts.wait || 120));
    const a = window.__audit(); agg.combos++;
    const tag = p + '/' + m + '/' + sc;
    const add = (bag, k) => { (bag[k] = bag[k] || []).push(tag); };
    a.overflow.forEach((o) => add(agg.overflow, JSON.stringify(o)));
    a.offscreen.forEach((o) => add(agg.offscreen, o));
    a.truncated.filter((t) => !t.titled && !/line-clamp/.test(t.el)).forEach((t) => add(agg.truncatedNoTitle, t.el + ' "' + t.text + '" ' + t.sw + '/' + t.cw));
    a.lowContrast.forEach((t) => add(agg.low, '"' + t.text + '" ' + t.el + ' ' + t.size + 'px need ' + t.need));
    a.disabledContrast.forEach((t) => { if (t.cr < 3) add(agg.disabledLow, '"' + t.text + '" ' + t.cr); });
    a.tinyTargets.filter((t) => !/^A /.test(t)).forEach((t) => add(agg.tiny, t.replace(/\d+x\d+/, (m)=>m)));
    a.rawKeys.forEach((t) => add(agg.raw, t));
    (agg.minCr = agg.minCr || {});
    a.lowContrast.forEach((t) => { const k = '"' + t.text + '" ' + t.el + ' ' + t.size + 'px need ' + t.need; agg.minCr[k] = Math.min(agg.minCr[k] || 99, t.cr); });
  }
  const sum = (bag) => Object.entries(bag).slice(0, 8).map(([k, v]) => k + '  [' + v.length + ': ' + (v.length > 6 ? v.slice(0, 3).join(',') + '...' : v.join(',')) + ']');
  return { combos: agg.combos, overflow: sum(agg.overflow), offscreen: sum(agg.offscreen), truncatedNoTitle: sum(agg.truncatedNoTitle), lowContrast: sum(agg.low).map((s) => s + ' min=' + agg.minCr[s.split('  [')[0]]), disabledUnder3: sum(agg.disabledLow), tiny: sum(agg.tiny), raw: sum(agg.raw) };
};
window.__go = async function (name) {
  const names = { en: ['Transcribe', 'Models', 'History', 'Post-processing', 'Settings', 'Logs'], ru: null };
  const items = [...document.querySelectorAll('nav a, nav button, aside a, aside button')];
  const i = typeof name === 'number' ? name : names.en.indexOf(name);
  const el = items[i]; if (!el) return false; el.click(); await new Promise((r) => setTimeout(r, 700)); return true;
};
window.__screens = async function (idxs, opts) {
  const res = {};
  for (const i of idxs) {
    await window.__go(i);
    const m = await window.__matrix(opts);
    const slim = {}; for (const k of Object.keys(m)) { if (Array.isArray(m[k]) ? m[k].length : k === 'combos') slim[k] = Array.isArray(m[k]) ? m[k].slice(0, 6).map((s) => s.slice(0, 170)) : m[k]; }
    res[document.querySelector('main h1, main h2, h1')?.textContent?.trim() || i] = slim;
  }
  window.__set({ theme: 'gruvbox', mode: 'dark', scale: 1 });
  return JSON.stringify({ w: innerWidth, h: innerHeight, res });
};
