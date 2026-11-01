#!/usr/bin/env node
// 延迟发送：等待 N 秒后，在智联当前会话的输入框发送一条消息。
// 用于落实「对方回复后等 5–6 分钟再回」的沟通节奏（cdp 输入 + 点发送）。
// 用法: node reply_with_delay.js <delaySeconds> <message>
//
// 依赖: 调试 Chrome 已开（127.0.0.1:9222），且当前标签停在 i.zhaopin.com/im 的某个会话。
const http = require('http');

function httpJson(u) {
  return new Promise((res, rej) => {
    http.get(u, (r) => {
      let d = '';
      r.on('data', (c) => (d += c));
      r.on('end', () => res(JSON.parse(d)));
    }).on('error', rej);
  });
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const delay = parseInt(process.argv[2] || '300', 10);
  const msg = process.argv[3] || '';
  if (!msg) { console.error('USAGE: node reply_with_delay.js <delaySeconds> <message>'); process.exit(1); }

  console.log('[delay] waiting ' + delay + 's before sending ...');
  await sleep(delay * 1000);

  const list = await httpJson('http://127.0.0.1:9222/json');
  const page = list.find((p) => p.type === 'page' && p.url.includes('i.zhaopin.com/im'));
  if (!page) { console.error('NO_IM_TAB'); process.exit(1); }

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const send = (m, p = {}) => new Promise((res, rej) => {
    const mid = ++id;
    const h = (e) => { const d = JSON.parse(e.data); if (d.id === mid) { ws.removeEventListener('message', h); d.error ? rej(new Error(JSON.stringify(d.error))) : res(d.result); } };
    ws.addEventListener('message', h);
    ws.send(JSON.stringify({ id: mid, method: m, params: p }));
  });
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  const ev = async (x) => (await send('Runtime.evaluate', { expression: x, returnByValue: true })).result.value;

  // focus textarea and clear
  await ev("(function(){var ta=document.querySelector('textarea.im-sender__input');if(ta)ta.focus();return ta?'ok':'no'})()");
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, modifiers: 2, commands: ['selectAll'] });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, modifiers: 2, commands: ['selectAll'] });
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Backspace', code: 'Backspace', windowsVirtualKeyCode: 8, commands: ['deleteBackward'] });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Backspace', code: 'Backspace', windowsVirtualKeyCode: 8, commands: ['deleteBackward'] });
  await sleep(300);
  await send('Input.insertText', { text: msg });
  await sleep(400);

  const r = await ev("(function(){var bs=Array.from(document.querySelectorAll('button')).filter(function(b){return (b.innerText||'').trim()==='发送'&&b.getClientRects().length});if(!bs.length)return 'NO_BTN';bs[0].click();return 'SENT'})()");
  console.log('[send] ' + r + ' :: ' + msg.slice(0, 40));
  await sleep(1200);
  ws.close();
})().catch((e) => { console.error(String(e)); process.exit(1); });
