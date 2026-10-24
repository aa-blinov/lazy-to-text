window.__cap = async function (opts) {
  opts = opts || {};
  const FAKE = 'http://127.0.0.1:18593';
  const cv = document.createElement('canvas'); cv.width = cv.height = 1; const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (c) => { cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c; cx.fillRect(0, 0, 1, 1); const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const L = (r) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r[0]) + 0.7152 * f(r[1]) + 0.0722 * f(r[2]); };
  const R = (a, b) => { const x = L(a), y = L(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const over = (t, b) => { const a = t[3]; return [t[0] * a + b[0] * (1 - a), t[1] * a + b[1] * (1 - a), t[2] * a + b[2] * (1 - a), 1]; };
  function bgOf(el) { const ch = []; for (let e = el; e; e = e.parentElement) ch.push(e); let bg = [0, 0, 0, 1]; for (const e of ch.reverse()) { const c = rgba(getComputedStyle(e).backgroundColor); if (c[3] > 0) bg = over(c, bg); } return bg; }
  const app = document.getElementById('app'); app.style.width = '520px'; app.style.height = '96px'; app.style.overflow = 'hidden'; app.style.position = 'relative';
  if (!document.getElementById('__nt')) { const s = document.createElement('style'); s.id = '__nt'; s.textContent = '*{transition:none!important;animation:none!important}'; document.head.appendChild(s); }
  const LONG = { en: 'Please send the quarterly report to the whole finance team before Friday afternoon and copy the director as well, thank you very much', ru: 'Пожалуйста, отправьте квартальный отчёт всей финансовой команде до пятницы и поставьте в копию директора, большое спасибо заранее' };
  const DET = { en: 'Auto-paste did not work: the system refused the paste keystroke. The text is on the clipboard.', ru: 'Auto-paste did not work: the system refused the paste keystroke. The text is on the clipboard.' };
  const states = opts.states || ['recording', 'processing', 'pasted', 'copied', 'failed', 'too_short'];
  const bad = [], seen = {};
  for (const lang of opts.langs || ['en', 'ru']) {
    await fetch(FAKE + '/cfg?language=' + lang); await new Promise((r) => setTimeout(r, 700));
    for (const st of states) {
      await fetch(FAKE + '/push?name=state&data=' + encodeURIComponent(JSON.stringify({ state: st === 'recording' || st === 'processing' ? st : 'idle' })));
      if (!(st === 'recording' || st === 'processing')) {
        const d = st === 'pasted' ? { outcome: 'pasted', text: LONG[lang] } : st === 'copied' ? { outcome: 'copied', detail: lang === 'ru' ? 'Cmd+V' : 'Cmd+V', text: LONG[lang] } : st === 'failed' ? { outcome: 'failed', detail: DET[lang], text: LONG[lang] } : { outcome: 'failed', kind: 'too_short', detail: 'The recording was too short to transcribe. Speak a little longer before you stop.', text: '' };
        await fetch(FAKE + '/push?name=delivery&data=' + encodeURIComponent(JSON.stringify(d)));
      }
      await new Promise((r) => setTimeout(r, 350));
      for (const th of opts.palettes || ['gruvbox', 'github', 'dracula', 'nord', 'solarized', 'catppuccin']) for (const m of ['light', 'dark']) {
        document.documentElement.dataset.theme = th; document.documentElement.dataset.mode = m; await new Promise((r) => setTimeout(r, 40));
        const c = document.querySelector('[role=status]'); const tag = lang + '/' + st + '/' + th + '/' + m;
        if (!c) { bad.push(tag + ' NO CAPSULE'); continue; }
        const r = c.getBoundingClientRect(); const ar = app.getBoundingClientRect();
        if (r.left < ar.left - 0.5 || r.right > ar.right + 0.5) bad.push(tag + ' OUT-H ' + [r.left, r.right].map(Math.round)); if (r.height > 57) bad.push(tag + ' TALL ' + r.height); const inner = c.querySelector('.min-w-0'); if (inner && inner.getBoundingClientRect().bottom > r.bottom + 0.5 || inner && inner.getBoundingClientRect().top < r.top - 0.5) bad.push(tag + ' INNER-V ' + Math.round(inner.getBoundingClientRect().height) + ' in ' + Math.round(r.height));
        const ds = [...c.querySelectorAll('div')].filter((e) => getComputedStyle(e).overflow !== 'visible' || e.className.includes('truncate') || e.className.includes('line-clamp'));
        for (const e of ds) {
          const sw = e.scrollWidth, cw = e.clientWidth, sh = e.scrollHeight, ch = e.clientHeight;
          if (sw > cw + 1 || sh > ch + 1) { const k = lang + '/' + st + ' ' + e.textContent.trim().slice(0, 40) + ' sw' + sw + '/cw' + cw + ' sh' + sh + '/ch' + ch + ' title=' + (e.title ? 'y' : 'n'); seen[k] = (seen[k] || 0) + 1; }
        }
        const kids = [...c.querySelectorAll('div,span')].filter((e) => [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()));
        for (const e of kids) { const bg = bgOf(e); const fg = over(rgba(getComputedStyle(e).color), bg); const cr = R(fg, bg); if (cr < 4.5) bad.push(tag + ' CONTRAST ' + cr.toFixed(2) + ' ' + e.textContent.trim().slice(0, 20)); }
        const dot = c.querySelector('[data-testid=dot]'); const dbg = over(rgba(getComputedStyle(dot).backgroundColor), bgOf(c)); const dcr = R(dbg, bgOf(c)); if (dcr < 3) bad.push(tag + ' DOT ' + dcr.toFixed(2));
        const bd = over(rgba(getComputedStyle(c).borderTopColor), bgOf(c)); const bcr = R(bd, [0, 0, 0, 1]);
      }
    }
  }
  return JSON.stringify({ badCount: bad.length, bad: bad.slice(0, 25), clipped: seen });
};
'ok'
