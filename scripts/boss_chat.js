// boss_chat.js — 读 BOSS 会话列表 + 最新消息（走 API，绕开页面反爬）
// 用法: node boss_chat.js [--limit 20]
const http = require('http');
function httpJson(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => { let d = ''; res.on('data', (c) => (d += c)); res.on('end', () => { try { resolve(JSON.parse(d)); } catch (e) { reject(e); } }); }).on('error', reject);
  });
}
const argv = process.argv.slice(2);
function arg(name, def) { const i = argv.indexOf('--' + name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; }
const LIMIT = Number(arg('limit', '20'));
(async () => {
  const list = await httpJson('http://127.0.0.1:9222/json');
  const page = list.find((t) => t.type === 'page' && (t.url || '').includes('zhipin.com'));
  if (!page) { console.log(JSON.stringify({ ok: false, error: 'NO_ZHIPIN_PAGE' })); return; }
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  const send = (method, params = {}, timeoutMs = 25000) => new Promise((resolve, reject) => {
    const mid = ++id;
    const timer = setTimeout(() => { if (pending.has(mid)) { pending.delete(mid); reject(new Error('TIMEOUT:' + method)); } }, timeoutMs);
    pending.set(mid, { resolve: (v) => { clearTimeout(timer); resolve(v); }, reject: (e) => { clearTimeout(timer); reject(e); } });
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) { const p = pending.get(msg.id); pending.delete(msg.id); msg.error ? p.reject(new Error(msg.error.message)) : p.resolve(msg.result); }
  };
  await new Promise((r) => { ws.onopen = r; setTimeout(r, 3000); });
  const ev = async (expr) => {
    const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error('EVAL_FAILED: ' + JSON.stringify(r.exceptionDetails).slice(0, 200));
    return r.result && r.result.value;
  };
  try {
    await send('Runtime.enable');
    const expr = `(async () => {
      const url = '/wapi/zprelation/friend/getGeekFriendList.json?page=1&pageSize=${LIMIT}';
      const r = await fetch(url, { credentials: 'include', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      const d = await r.json();
      if (d.code !== 0) return JSON.stringify({ ok: false, code: d.code, message: d.message });
      const zp = d.zpData || {};
      const list = zp.result || zp.friendList || [];
      return JSON.stringify({
        ok: true,
        total: list.length,
        keys: list[0] ? Object.keys(list[0]) : [],
        items: list.map(f => ({
          name: f.name || f.bossName || '',
          company: f.brandName || f.company || '',
          title: f.jobName || f.bossTitle || '',
          msg: (f.lastMessage || f.lastMsg || f.lastText || '').slice(0, 80),
          time: f.lastTime || f.lastTs || f.updateTime || '',
          unread: f.unread || f.unreadCount || 0,
          encryptBossId: f.encryptBossId || f.bossId || ''
        }))
      });
    })()`;
    const res = await ev(expr);
    console.log(res);
    ws.close();
  } catch (e) { console.log('ERR', e.message); ws.close(); }
})();
