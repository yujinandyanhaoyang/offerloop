// boss_reply.js — 回复某个联系人（选会话 + 发消息；BOSS 聊天列表项 = div.friend-content）
// 用法: node boss_reply.js --contact "王攀" --message "您好..."
const http = require('http');
function httpJson(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => { let d = ''; res.on('data', (c) => (d += c)); res.on('end', () => { try { resolve(JSON.parse(d)); } catch (e) { reject(e); } }); }).on('error', reject);
  });
}
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
const argv = process.argv.slice(2);
function arg(name, def) { const i = argv.indexOf('--' + name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; }
const CONTACT = arg('contact', '');
const MESSAGE = arg('message', '');
if (!CONTACT || !MESSAGE) { console.log('用法: node boss_reply.js --contact <姓名> --message <内容>'); process.exit(1); }
(async () => {
  const list = await httpJson('http://127.0.0.1:9222/json');
  const page = list.find((t) => t.type === 'page' && (t.url || '').includes('web/geek/chat'));
  if (!page) { console.log(JSON.stringify({ ok: false, error: 'NO_CHAT_PAGE' })); return; }
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  const send = (method, params = {}, timeoutMs = 20000) => new Promise((resolve, reject) => {
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
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true });
    if (r.exceptionDetails) throw new Error('EVAL_FAILED:' + JSON.stringify(r.exceptionDetails).slice(0, 200));
    return r.result && r.result.value;
  };
  try {
    await send('Runtime.enable');
    // 1. 点会话（div.friend-content）
    const step1 = await ev(`(function(){var items=Array.from(document.querySelectorAll('div.friend-content'));var el=items.find(function(e){return (e.innerText||'').indexOf(${JSON.stringify(CONTACT)})>=0});if(!el)return 'NO_CONTACT';el.click();return 'CLICKED';})()`);
    if (step1 !== 'CLICKED') { console.log(JSON.stringify({ ok: false, contact: CONTACT, error: step1 })); ws.close(); return; }
    await sleep(1500);
    // 2. 校验 selected
    const sel = await ev(`(function(){var s=document.querySelector('div.friend-content.selected');return s?(s.innerText||'').replace(/\\s+/g,' ').trim().slice(0,40):'NONE';})()`);
    if (sel.indexOf(CONTACT) < 0) { console.log(JSON.stringify({ ok: false, contact: CONTACT, error: 'SELECT_MISMATCH', selected: sel })); ws.close(); return; }
    // 3. 插入 + 发送
    const ins = await ev(`(function(){var el=document.querySelector('#chat-input');if(!el)return 'NO_INPUT';el.focus();el.textContent='';document.execCommand('insertText',false,${JSON.stringify(MESSAGE)});return 'INSERTED';})()`);
    if (ins !== 'INSERTED') { console.log(JSON.stringify({ ok: false, contact: CONTACT, error: ins })); ws.close(); return; }
    await sleep(700);
    const sent = await ev(`(function(){var b=document.querySelector('button.btn-send');if(!b)return 'NO_SEND';b.click();return 'SENT';})()`);
    console.log(JSON.stringify({ ok: sent === 'SENT', contact: CONTACT, selected: sel, result: sent }));
    ws.close();
  } catch (e) { console.log('ERR', e.message); ws.close(); }
})();
