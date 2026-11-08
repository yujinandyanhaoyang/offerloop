// boss_send_ws.js — 直接连 BOSS MQTT (wss://ws6.zhipin.com/chatws) 发消息
// 用法: node boss_send_ws.js --contact "韩一鸣" --message "你好"
const http = require('http');
function httpJson(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => { let d = ''; res.on('data', (c) => (d += c)); res.on('end', () => { try { resolve(JSON.parse(d)); } catch (e) { reject(e); } }); }).on('error', reject);
  });
}
const argv = process.argv.slice(2);
function arg(name, def) { const i = argv.indexOf('--' + name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; }
const CONTACT = arg('contact', '');
const MESSAGE = arg('message', '');
if (!CONTACT || !MESSAGE) { console.log('用法: node boss_send_ws.js --contact <联系人> --message <内容>'); process.exit(1); }

(async () => {
  const list = await httpJson('http://127.0.0.1:9222/json');
  const page = list.find((t) => t.type === 'page' && (t.url || '').includes('zhipin.com'));
  if (!page) { console.log(JSON.stringify({ ok: false, error: 'NO_ZHIPIN_PAGE' })); return; }
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  const send = (method, params = {}, timeoutMs = 40000) => new Promise((resolve, reject) => {
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
    if (r.exceptionDetails) throw new Error('EVAL: ' + JSON.stringify(r.exceptionDetails).slice(0, 300));
    return r.result && r.result.value;
  };
  try {
    await send('Runtime.enable');
    const expr = `(async () => {
      const log = [];
      // 1. 找目标会话
      const fl = await (await fetch('/wapi/zprelation/friend/getGeekFriendList.json?page=1&pageSize=100', { credentials: 'include', headers: { 'X-Requested-With': 'XMLHttpRequest' } })).json();
      const friends = (fl.zpData && fl.zpData.result) || [];
      const t = friends.find(f => ((f.name||'') + (f.brandName||'')).indexOf(${JSON.stringify(CONTACT)}) >= 0);
      if (!t) return JSON.stringify({ ok: false, error: 'CONTACT_NOT_FOUND' });
      log.push({ name: t.name, brand: t.brandName, bossId: t.encryptBossId });

      // 2. 从 cookie 取 wbg/wt2 作为客户端标识
      function getCookie(n) { const m = document.cookie.match(new RegExp('(?:^|; )' + n + '=([^;]*)')); return m ? m[1] : ''; }
      const wbg = getCookie('wbg');
      log.push({ hasWbg: !!wbg, wbgLen: wbg.length });

      // 3. 生成 clientId 和 password（参考抓包格式）
      const clientId = 'ws-' + wbg.toUpperCase();
      // MQTT password 需要服务端签发的 token；先试 wbg/wt2 组合
      const password = getCookie('wt2') || '';
      const username = (getCookie('__zp_stoken__') || '').slice(0, 20);
      log.push({ clientId, pwdLen: password.length });

      // 4. 建 WS（注意：subprotocol 是必需的）
      const sock = await new Promise((resolve) => {
        try {
          const s = new WebSocket('wss://ws6.zhipin.com/chatws');
          s.binaryType = 'arraybuffer';
          const timer = setTimeout(() => resolve({ err: 'WS_TIMEOUT' }), 8000);
          s.onopen = () => { clearTimeout(timer); resolve({ ok: true, sock: s }); };
          s.onerror = () => { clearTimeout(timer); resolve({ err: 'WS_ERROR_NO_SUBPROTOCOL' }); };
        } catch (e) { resolve({ err: 'EX: ' + e.message }); }
      });
      if (!sock.ok) return JSON.stringify({ ok: false, log, error: sock.err });
      log.push({ wsOpened: true });
      sock.sock.close();
      return JSON.stringify({ ok: true, log, note: 'WS 可建连，需补 subprotocol/password' });
    })()`;
    console.log(await ev(expr));
    ws.close();
  } catch (e) { console.log('ERR', e.message); ws.close(); }
})();
