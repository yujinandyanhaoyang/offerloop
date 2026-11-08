// boss_send_mqtt.js — 直连 BOSS MQTT 发消息（协议已破解）
// 用法: node boss_send_mqtt.js --contact "韩一鸣" --message "你好"
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
const TOKEN = arg('token', 'D5U677O7Ofo-dm-x_qQulQByqZX_hOuI6cJdPlJU8VcpGjepHyOe4Fzvl3bjpQ4Q-mpAZmwBT4t5HuoO_lm6TCg~~');
if (!CONTACT || !MESSAGE) { console.log('用法: node boss_send_mqtt.js --contact <联系人> --message <内容> [--token <ws token>]'); process.exit(1); }

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
    if (r.exceptionDetails) throw new Error('EVAL: ' + JSON.stringify(r.exceptionDetails).slice(0, 400));
    return r.result && r.result.value;
  };
  try {
    await send('Runtime.enable');
    const expr = `(async () => {
      const log = [];
      // 1. 拿 encryptBossId + 发送方 uid
      const fl = await (await fetch('/wapi/zprelation/friend/getGeekFriendList.json?page=1&pageSize=100', { credentials: 'include', headers: { 'X-Requested-With': 'XMLHttpRequest' } })).json();
      const friends = (fl.zpData && fl.zpData.result) || [];
      const t = friends.find(f => ((f.name||'') + (f.brandName||'')).indexOf(${JSON.stringify(CONTACT)}) >= 0);
      if (!t) return JSON.stringify({ ok: false, error: 'CONTACT_NOT_FOUND' });
      log.push({ name: t.name, brand: t.brandName, bossId: t.encryptBossId, uid: t.uid });

      // 2. protobuf 编码工具
      function varint(n) { const out = []; do { let d = n % 128; n = Math.floor(n / 128); if (n > 0) d |= 0x80; out.push(d); } while (n > 0); return out; }
      function tag(field, wire) { return varint((field << 3) | wire); }
      function pbVarint(field, v) { return [...tag(field, 0), ...varint(v)]; }
      function pbBytes(field, bytes) { return [...tag(field, 2), ...varint(bytes.length), ...bytes]; }
      function pbStr(field, s) { return pbBytes(field, Array.from(new TextEncoder().encode(s))); }

      const now = Date.now();
      // from_id: 用页面里的 uid（登录用户）
      const myUid = t.uid ? 0 : 0;  // 服务端会覆盖，先用 0 试
      const msgBody = [
        ...pbBytes(1, [...pbVarint(1, myUid), ...pbVarint(7, 0)]),      // from
        ...pbBytes(2, [...pbVarint(1, t.uid || 0), ...pbStr(2, t.encryptBossId), ...pbVarint(7, 0)]),  // to
        ...pbVarint(3, 1),
        ...pbVarint(4, 1),
        ...pbVarint(5, 0),
        ...pbBytes(6, [...pbVarint(1, 1), ...pbVarint(2, 1), ...pbStr(3, ${JSON.stringify(MESSAGE)})]),  // 文本
        ...pbVarint(11, now)
      ];
      const payload = [...pbVarint(1, 1), ...pbBytes(3, msgBody)];

      // 3. MQTT PUBLISH 封包
      const topicBytes = Array.from(new TextEncoder().encode('chat'));
      const packetId = 1;
      const mqttBody = [(topicBytes.length >> 8), topicBytes.length & 0xff, ...topicBytes, (packetId >> 8), packetId & 0xff, ...payload];
      const publishFrame = new Uint8Array([0x32, ...varint(mqttBody.length), ...mqttBody]);  // 0x32 = PUBLISH QoS1

      // 4. MQTT CONNECT 封包
      function mqttStr(s) { const b = new TextEncoder().encode(s); return [b.length >> 8, b.length & 0xff, ...b]; }
      const clientId = 'ws-' + Math.random().toString(36).slice(2, 14).toUpperCase();
      const connectBody = [...mqttStr('MQIsdp'), 0x03, 0xc2, 0x00, 0x19,
        ...mqttStr(clientId), ...mqttStr('AGcBCt5srvvzgzj4|0'), ...mqttStr(${JSON.stringify(TOKEN)})];
      const connectFrame = new Uint8Array([0x10, ...varint(connectBody.length), ...connectBody]);

      // 5. 建连 + 发送
      const result = await new Promise((resolve) => {
        try {
          const s = new WebSocket('wss://ws6.zhipin.com/chatws', ${JSON.stringify(TOKEN)});
          s.binaryType = 'arraybuffer';
          const timer = setTimeout(() => resolve({ err: 'TIMEOUT', log }), 15000);
          s.onopen = () => {
            s.send(connectFrame);
            setTimeout(() => {
              s.send(publishFrame);
              setTimeout(() => { clearTimeout(timer); resolve({ ok: true, sentPayload: payload.length, frameLen: publishFrame.length, log }); }, 2000);
            }, 1000);
          };
          s.onmessage = (m) => {
            const b = new Uint8Array(m.data);
            const type = (b[0] >> 4) & 0xf;
            if (type === 2) { log.push('CONNACK'); }
            if (type === 4) { log.push('PUBACK'); clearTimeout(timer); resolve({ ok: true, ack: true, log }); }
          };
          s.onerror = () => { clearTimeout(timer); resolve({ err: 'WS_ERROR', log }); };
        } catch (e) { resolve({ err: 'EX:' + e.message, log }); }
      });
      return JSON.stringify(result);
    })()`;
    console.log('RESULT:', await ev(expr));
    ws.close();
  } catch (e) { console.log('ERR', e.message); ws.close(); }
})();
