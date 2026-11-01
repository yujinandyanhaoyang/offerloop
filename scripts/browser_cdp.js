// browser_cdp.js — 通过 CDP 驱动宿主机 Chrome（求职投递自动化执行通道）。
// 复用已登录的现有标签（不新建 about:blank，避免重过 BOSS 安全验证）。
// 用法：
//   node browser_cdp.js status            检查浏览器与标签
//   node browser_cdp.js read [url] [秒]   读现有标签 DOM；给 url 则先导航
//   node browser_cdp.js buttons           列出可点元素（button/a/[role=button]）
//   node browser_cdp.js click <文字>      按可见文字点击元素（JS click）
const http = require('http');
const fs = require('fs');
const path = require('path');
const { selectTarget } = require('./browser_target');
const CONFIG_DIR = process.env.OFFERLOOP_ADAPTERS || process.env.OFFERLOOP_CONFIG || path.join(__dirname, '..', 'config');
const DATA_DIR = process.env.OFFERLOOP_HOME || path.join(__dirname, '..', 'data');
const PLATFORMS = JSON.parse(fs.readFileSync(path.join(CONFIG_DIR, 'platforms.json'), 'utf8'));
const COMPANIES = JSON.parse(fs.readFileSync(path.join(CONFIG_DIR, 'companies.json'), 'utf8'));
for (const [key, company] of Object.entries(COMPANIES)) {
  if (key.startsWith('_')) continue;
  PLATFORMS[key] = { ...company, base_url: company.careers_url,
    allowed_hosts: [new URL(company.careers_url).hostname],
    submit_selector: company.apply_selector, submit_kind: 'apply' };
}

const CDP = 'http://127.0.0.1:9222';

function httpJson(url, method = 'GET') {
  return new Promise((resolve, reject) => {
    const req = http.request(url, { method }, (res) => {
      let data = '';
      res.on('data', (c) => (data += c));
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch (e) { reject(new Error('bad json: ' + data.slice(0, 200))); }
      });
    });
    req.on('error', reject);
    req.setTimeout(15000, () => req.destroy(new Error('HTTP timeout')));
    req.end();
  });
}

async function listPages() {
  const list = await httpJson(CDP + '/json');
  return list.filter((t) => t.type === 'page');
}

let URL_FILTER = null;
let TAB_ID = null;
async function getPageTarget() {
  const pages = await listPages();
  return selectTarget(pages, { id: TAB_ID, url: URL_FILTER, hosts: p.allowed_hosts });
}

function connect(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let id = 0;
  const pending = new Map();
  const send = (method, params = {}, timeoutMs = 15000) => new Promise((resolve, reject) => {
    const mid = ++id;
    const timer = setTimeout(() => {
      if (pending.has(mid)) { pending.delete(mid); reject(new Error('CDP timeout: ' + method)); }
    }, timeoutMs);
    pending.set(mid, {
      resolve: (v) => { clearTimeout(timer); resolve(v); },
      reject: (e) => { clearTimeout(timer); reject(e); },
    });
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const p = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? p.reject(new Error(JSON.stringify(msg.error))) : p.resolve(msg.result);
    }
  };
  return new Promise((resolve, reject) => {
    ws.onopen = () => resolve({ ws, send });
    ws.onerror = () => reject(new Error('websocket error'));
  });
}

async function evalOn(page, expression) {
  const { ws, send } = await connect(page.webSocketDebuggerUrl);
  await send('Runtime.enable');
  const r = await send('Runtime.evaluate', { expression, returnByValue: true });
  ws.close();
  if (r.exceptionDetails) throw new Error('PAGE_EVALUATION_FAILED');
  return r.result && r.result.value;
}

async function status() {
  try {
    const v = await httpJson(CDP + '/json/version');
    const pages = await listPages();
    console.log('BROWSER:', v.Browser);
    console.log('PAGES:', pages.length);
    for (const p of pages) console.log(' -', p.id, p.url);
  } catch (e) {
    console.error('CDP 不可达:', e.message);
    console.error('先在宿主机运行 scripts/browser_launch.cmd。');
    process.exit(1);
  }
}

async function open(url) {
  // 先关闭同 URL 的旧标签，避免重复打开后 selectTarget 判 AMBIGUOUS_TARGET。
  if (url) {
    try {
      const pages = await listPages();
      for (const p of pages) {
        if (p.url === url) { try { await httpJson(CDP + '/json/close/' + p.id, 'GET'); } catch (e) {} }
      }
    } catch (e) {}
  }
  const p = await httpJson(CDP + '/json/new?' + encodeURIComponent(url || 'about:blank'), 'PUT');
  console.log('OPENED:', p.id, p.url);
}

async function close(id) {
  if (!id) { console.error('需要标签ID（status 查看）'); process.exit(1); }
  await httpJson(CDP + '/json/close/' + id, 'GET');
  console.log('CLOSED:', id);
}

async function read(url, waitMs) {
  const page = await getPageTarget();
  if (!page) { console.error('无可用页面标签'); process.exit(1); }
  const { ws, send } = await connect(page.webSocketDebuggerUrl);
  await send('Page.enable');
  await send('Runtime.enable');
  if (url) {
    await send('Page.navigate', { url });
    await new Promise((r) => setTimeout(r, waitMs));
  }
  await new Promise((r) => setTimeout(r, 500));
  const r = await send('Runtime.evaluate', {
    expression: `JSON.stringify({title: document.title, url: location.href, len: document.body ? document.body.innerText.length : 0, text: document.body ? document.body.innerText.slice(0, 2000) : ''})`,
    returnByValue: true,
  });
  const out = JSON.parse(r.result.value);
  console.log('TITLE:', out.title);
  console.log('URL:', out.url);
  console.log('BODYLEN:', out.len);
  console.log('TEXT:', out.text);
  ws.close();
}

async function buttons() {
  const page = await getPageTarget();
  const out = await evalOn(page, `JSON.stringify(Array.from(document.querySelectorAll('button,a,[role=button]')).map((e,i)=>({i:i,tag:e.tagName,text:(e.innerText||'').trim().replace(/\\s+/g,' ').slice(0,40),cls:(e.className||'').toString().slice(0,60)})).filter(x=>x.text).slice(0,120))`);
  const arr = JSON.parse(out);
  for (const b of arr) console.log(b.i, b.tag, '[' + b.text + ']', '|', b.cls);
  console.log('TOTAL_SAMPLE:', arr.length);
}

async function click(text) {
  const page = await getPageTarget();
  const out = await evalOn(page, `(function(){var t=${JSON.stringify(text)};var els=Array.from(document.querySelectorAll('button,a,[role=button],span,div'));var el=els.find(e=>e.innerText&&e.innerText.trim()===t)||els.find(e=>e.innerText&&e.innerText.trim().includes(t));if(!el)return 'NOT_FOUND:'+t;el.click();return 'CLICKED:'+el.tagName+':'+(el.innerText||'').trim().slice(0,40);})()`);
  console.log(out);
  await new Promise((r) => setTimeout(r, 1500));
}

async function html(text) {
  const page = await getPageTarget();
  const out = await evalOn(page, `(function(){var t=${JSON.stringify(text)};var els=Array.from(document.querySelectorAll('a,button,[role=button],span'));var el=els.find(e=>e.innerText&&e.innerText.trim()===t)||els.find(e=>e.innerText&&e.innerText.trim().includes(t));if(!el)return 'NOT_FOUND:'+t;return el.outerHTML.slice(0,600);})()`);
  console.log(out);
}

async function apply(p, send) {
  // 投递第一步：定位并（可选）点击投递按钮。dry-run 只定位不点击；点击=真实外发（chat 发招呼 / apply 投递简历）。
  const page = await getPageTarget();
  if (!URL_FILTER && !TAB_ID) throw new Error('apply requires --url <exact URL> or --tab <ID>');
  const sel = p.submit_selector;
  const expr = send
    ? `(function(){var bs=Array.from(document.querySelectorAll(${JSON.stringify(sel)})).filter(b=>b.getClientRects().length&&!b.disabled&&b.getAttribute('aria-disabled')!=='true');if(bs.length!==1)return 'SUBMIT_TARGET_NOT_UNIQUE_OR_ENABLED:'+bs.length;bs[0].click();return 'SUBMISSION_UNKNOWN['+${JSON.stringify(p.submit_kind)}+']:click dispatched; verify platform receipt before recording or retrying';})()`
    : `(function(){var b=document.querySelector(${JSON.stringify(sel)});return b?'FOUND['+${JSON.stringify(p.submit_kind)}+']:'+(b.innerText||'').trim():'NO_SUBMIT_BUTTON:'+${JSON.stringify(sel)};})()`;
  const out = await evalOn(page, expr);
  console.log(out);
  if (send) await new Promise((r) => setTimeout(r, 1500));
}

async function q(selector) {
  // 调试：按 CSS 选择器 dump 前若干元素的 outerHTML（多平台 DOM 发现用）。
  const page = await getPageTarget();
  const out = await evalOn(page, `(function(){var s=${JSON.stringify(selector)};var els=Array.from(document.querySelectorAll(s)).slice(0,3);return els.length?els.map(e=>e.outerHTML.slice(0,400)).join('\\n---\\n'):'NO_MATCH:'+s;})()`);
  console.log(out);
}

async function evaljs(code) {
  // 调试：执行任意 JS 并返回结果值（returnByValue）。
  const page = await getPageTarget();
  const out = await evalOn(page, code);
  console.log(out);
}

async function clicksel(selector, index) {
  // 按 CSS 选择器 + 序号点击（多平台 DOM 交互用，配合 q 定位）。
  const page = await getPageTarget();
  const i = Number(index || 0);
  const out = await evalOn(page, `(function(){var els=document.querySelectorAll(${JSON.stringify(selector)});var el=els[${i}];if(!el)return 'NO_MATCH:'+${JSON.stringify(selector)}+'['+${i}+']';el.click();return 'CLICKED:'+el.tagName+'.'+(el.className||'').toString().slice(0,60);})()`);
  console.log(out);
  await new Promise((r) => setTimeout(r, 1800));
}

async function setfile(selector, filePath) {
  // 给文件输入框设置文件（简历上传用）。CDP DOM.setFileInputFiles（nodeId + backendNodeId 双试）+ 触发 change。
  const page = await getPageTarget();
  const { ws, send } = await connect(page.webSocketDebuggerUrl);
  await send('DOM.enable');
  await send('Runtime.enable');
  const doc = await send('DOM.getDocument');
  const q = await send('DOM.querySelector', { nodeId: doc.root.nodeId, selector });
  if (!q.nodeId) { console.log('NO_INPUT:' + selector); ws.close(); return; }
  let r;
  try {
    r = await send('DOM.setFileInputFiles', { nodeId: q.nodeId, files: [filePath] });
    console.log('RESULT:', JSON.stringify(r));
  } catch (e) {
    console.log('NODEID_FAIL:', e.message);
    const d = await send('DOM.describeNode', { nodeId: q.nodeId });
    r = await send('DOM.setFileInputFiles', { backendNodeId: d.node.backendNodeId, files: [filePath] });
    console.log('RESULT2:', JSON.stringify(r));
  }
  await send('Runtime.evaluate', { expression: `(function(){var el=document.querySelector(${JSON.stringify(selector)});if(el){el.dispatchEvent(new Event('change',{bubbles:true}));return 'CHANGE:'+el.files.length+':'+(el.files[0]?el.files[0].name:'');}return 'NO_EL';})()` });
  console.log('SET_FILE:' + selector + ' <- ' + filePath);
  ws.close();
}

async function upload(buttonSelector, filePath) {
  // 文件选择器拦截上传：拦截原生文件选择器，点按钮后把文件设进 input（修复 DOM.setFileInputFiles 直设不生效）。
  const page = await getPageTarget();
  const { ws, send } = await connect(page.webSocketDebuggerUrl);
  await send('Page.enable');
  await send('DOM.enable');
  await send('Runtime.enable');
  await send('Page.setInterceptFileChooserDialog', { enabled: true });
  const chooserPromise = new Promise((resolve, reject) => {
    const timer = setTimeout(() => { ws.removeEventListener('message', handler); reject(new Error('file chooser timeout')); }, 12000);
    function handler(ev) {
      const msg = JSON.parse(ev.data);
      if (msg.method === 'Page.fileChooserOpened') {
        clearTimeout(timer);
        ws.removeEventListener('message', handler);
        resolve(msg.params);
      }
    }
    ws.addEventListener('message', handler);
  });
  await send('Runtime.evaluate', { expression: `(function(){var el=document.querySelector(${JSON.stringify(buttonSelector)});if(el){el.click();return 'CLICKED';}return 'NO_EL';})()` });
  const chooser = await chooserPromise;
  await send('DOM.setFileInputFiles', { backendNodeId: chooser.backendNodeId, files: [filePath] });
  await send('Page.setInterceptFileChooserDialog', { enabled: false });
  console.log('UPLOADED:' + buttonSelector + ' <- ' + filePath);
  ws.close();
}

async function setinput(selector, value) {
  // 给文本输入框设值 + 触发 input/change（Vue v-model 用）。
  const page = await getPageTarget();
  const out = await evalOn(page, `(function(){var el=document.querySelector(${JSON.stringify(selector)});if(!el)return 'NO_EL';el.value=${JSON.stringify(value)};el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));return 'SET:'+el.value;})()`);
  console.log(out);
}

async function sendmsg(text) {
  // BOSS 聊天发消息：contenteditable 用 execCommand('insertText') 才能触发框架（textContent+InputEvent 不生效）。
  const page = await getPageTarget();
  const out = await evalOn(page, `(function(){var el=document.querySelector('#chat-input');if(!el)return 'NO_INPUT';el.focus();el.textContent='';document.execCommand('insertText',false,${JSON.stringify(text)});var btn=document.querySelector('button.btn-send');if(!btn)return 'NO_SEND';var dis=btn.className.includes('disabled');if(dis)return 'SEND_DISABLED';btn.click();return 'SENT';})()`);
  console.log(out);
}

async function jobs(p) {
  const page = await getPageTarget();
  const anchor = p.card_anchor;
  const companySel = p.company_selector;
  const base = p.base_url;
  const out = await evalOn(page, `(function(){
    // 1) SSR 状态优先：智联等平台把岗位列表放在 window.__INITIAL_STATE__.positionList
    try {
      var st = window.__INITIAL_STATE__ || {};
      var list = st.positionList || (st.searchResult && st.searchResult.positionList) || [];
      if (list && list.length) {
        return JSON.stringify(list.map(function(x){
          return {
            title: x.name || x.jobName || '',
            company: x.companyName || '',
            city: x.workCity || x.cityDistrict || '',
            salary: x.salary60 || '',
            years: x.workingExp || '',
            education: x.education || '',
            source_url: x.positionURL || '',
            job_id: x.jobId || x.number || '',
            source_level: 'partial',
            observed_on: new Date().toISOString().slice(0,10),
            summary: (x.jobDescription || '').slice(0,160),
            next_action: '打开详情页核验原JD与准入'
          };
        }));
      }
    } catch (e) {}
    // 2) DOM 兜底
    var names = Array.from(document.querySelectorAll(${JSON.stringify(anchor)}));
    var items = names.map(function(a){
      var card = a.closest(${JSON.stringify(p.card_selector)}) || a.closest('[class*=card]') || a.closest('li') || a.parentElement;
      var text = (card ? card.innerText.replace(/\\s+/g,' ').trim() : '');
      var cityM = text.match(/(杭州|深圳|上海|北京|广州|成都|南京|武汉|西安|苏州|合肥|长沙|天津|重庆|宁波|厦门|青岛)(?=\\s*[·\\s])/);
      var yearsM = text.match(/(\\d+-\\d+年|\\d+年以上|经验不限|应届生|在校生)/);
      var eduM = text.match(/(本科|硕士|博士|大专|学历不限)/);
      var companyEl = card ? card.querySelector(${JSON.stringify(companySel)}) : null;
      var href = a.getAttribute('href') || '';
      var anchorText = a.innerText.trim();
      return {
        title: ${p.anchor_is_company ? "''" : 'anchorText'},
        company: ${p.anchor_is_company ? 'anchorText' : "companyEl ? companyEl.innerText.trim() : ''"},
        city: cityM ? cityM[1] : '',
        years: yearsM ? yearsM[1] : '',
        education: eduM ? eduM[1] : '',
        source_url: href.startsWith('http') ? href : ${JSON.stringify(base)} + href,
        source_level: 'partial',
        observed_on: new Date().toISOString().slice(0,10),
        summary: text.slice(0, 160),
        next_action: '打开详情页核验原JD与准入'
      };
    });
    return JSON.stringify(items);
  })()`);
  console.log(out);
}

async function search(p, kw, city) {
  const url = p.search_url.replace('{kw}', encodeURIComponent(kw || '')).replace('{city}', (p.city_code && p.city_code[city]) || city || '');
  console.log(url);
}

async function shot(filePath) {
  // 截图当前标签到 PNG（DOM 结构发现与证据留存用）。
  const page = await getPageTarget();
  if (!page) { console.error('无可用页面标签'); process.exit(1); }
  const { ws, send } = await connect(page.webSocketDebuggerUrl);
  await send('Page.enable');
  const r = await send('Page.captureScreenshot', { format: 'png' });
  const out = filePath || path.join(DATA_DIR, 'shot-' + Date.now() + '.png');
  fs.writeFileSync(out, Buffer.from(r.data, 'base64'));
  console.log('SHOT:', out);
  ws.close();
}

async function netcapture(durationSec, filterKeyword) {
  // 智联求职意向改值走 API 抓包：开启 Network 域，监听 POST/PUT/PATCH，记录 url/method/headers/postData/status。
  // 用法：node browser_cdp.js --platform zhaopin --url <resume页URL> netcapture <秒> [url关键字过滤]
  const page = await getPageTarget();
  if (!page) { console.error('无可用页面标签'); process.exit(1); }
  const { ws, send } = await connect(page.webSocketDebuggerUrl);
  await send('Network.enable', { maxPostDataSize: 1048576, maxTotalBufferSize: 10485760, maxResourceBufferSize: 1048576 });
  const captured = [];
  const byReq = new Map();
  const handler = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.method === 'Network.requestWillBeSent') {
      const r = msg.params.request || {};
      const url = r.url || '';
      const method = (r.method || '').toUpperCase();
      if (method === 'POST' || method === 'PUT' || method === 'PATCH') {
        if (filterKeyword && !url.includes(filterKeyword)) return;
        const item = { requestId: msg.params.requestId, method, url, type: msg.params.type, wallTime: msg.params.wallTime, headers: r.headers || {}, postData: r.postData || null };
        captured.push(item);
        byReq.set(msg.params.requestId, item);
      }
    } else if (msg.method === 'Network.responseReceived') {
      const item = byReq.get(msg.params.requestId);
      if (item) {
        item.status = msg.params.response.status;
        item.respMime = msg.params.response.mimeType;
      }
    }
  };
  ws.addEventListener('message', handler);
  console.log('CAPTURING', durationSec + 's', filterKeyword ? ('filter=' + filterKeyword) : '(all POST/PUT/PATCH)');
  await new Promise((r) => setTimeout(r, durationSec * 1000));
  ws.removeEventListener('message', handler);
  for (const c of captured) {
    if (!c.postData) {
      try { const d = await send('Network.getRequestPostData', { requestId: c.requestId }); c.postData = d.postData; }
      catch (e) { c.postDataError = e.message; }
    }
  }
  const outDir = DATA_DIR;
  fs.mkdirSync(outDir, { recursive: true });
  const outPath = path.join(outDir, '智联抓包-' + Date.now() + '.json');
  fs.writeFileSync(outPath, JSON.stringify(captured, null, 2));
  console.log('CAPTURED_COUNT:', captured.length);
  for (const c of captured) console.log(' -', c.method, String(c.status || '?'), c.url.slice(0, 120));
  console.log('SAVED:', outPath);
  ws.close();
}

async function submitJob(p, execute, confirm) {
  // 投递执行器：定位投递按钮 → (execute 时)点击 → 处理确认页 → 抓回执（url/文本/成功标记/截图）。
  // dry-run（无 execute）：只定位不点击；execute：点击一次；confirm：点击后再点确认按钮。
  const page = await getPageTarget();
  if (!page) { console.error('无可用页面标签'); process.exit(1); }
  const sel = p.submit_selector;
  if (!sel) throw new Error('submit adapter not configured: ' + platform);
  const { ws, send } = await connect(page.webSocketDebuggerUrl);
  const ev = async (expr) => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true });
    if (r.exceptionDetails) throw new Error('PAGE_EVAL_FAILED');
    return r.result && r.result.value;
  };
  const locate = `(function(){try{var bs=Array.from(document.querySelectorAll(${JSON.stringify(sel)})).filter(function(b){return b.getClientRects().length&&!b.disabled&&b.getAttribute('aria-disabled')!=='true'});return JSON.stringify({count:bs.length,text:bs.length?bs[0].innerText.trim().slice(0,60):''});}catch(e){return JSON.stringify({error:e.message})}})()`;
  const found = JSON.parse(await ev(locate));
  const receiptDir = path.join(DATA_DIR, 'receipts');
  async function capture(label) {
    let state = {};
    try { state = JSON.parse(await ev(`JSON.stringify({url:location.href,title:document.title,text:(document.body?document.body.innerText:'').slice(0,1800)})`)); } catch (e) { state = { error: e.message }; }
    const markers = ['投递成功', '申请成功', '已投递', '提交成功', '已申请', '投递完成', '已发送', '简历已投递'];
    const hits = Array.isArray(state.text) ? [] : markers.filter(function (m) { return (state.text || '').includes(m); });
    let dlg = { dialog: false };
    try { dlg = JSON.parse(await ev(`(function(){try{var d=document.querySelector('[class*=dialog],[class*=modal],[class*=popup]');if(!d||!d.getClientRects().length)return JSON.stringify({dialog:false});var btns=Array.from(d.querySelectorAll('button')).map(function(b){return b.innerText.trim()}).filter(Boolean).slice(0,8);return JSON.stringify({dialog:true,text:(d.innerText||'').replace(/\\s+/g,' ').slice(0,200),buttons:btns});}catch(e){return JSON.stringify({error:e.message})}})()`)); } catch (e) { dlg = { dialog: false, error: e.message }; }
    let shot = null;
    try {
      const r = await send('Page.captureScreenshot', { format: 'png' });
      fs.mkdirSync(receiptDir, { recursive: true });
      shot = path.join(receiptDir, 'receipt-' + (label || 'x') + '-' + Date.now() + '.png');
      fs.writeFileSync(shot, Buffer.from(r.data, 'base64'));
    } catch (e) { shot = 'ERROR:' + e.message; }
    return { url: state.url, title: state.title, excerpt: (state.text || '').slice(0, 500), success_markers: hits, dialog: dlg, screenshot: shot };
  }
  if (!execute) {
    console.log(JSON.stringify({ mode: 'dry_run', submit_kind: p.submit_kind, selector: sel, located: found.count || 0, button_text: found.text || '', action: 'would_click', external_send: false }, null, 2));
    ws.close();
    return;
  }
  if (found.count !== 1) {
    console.log(JSON.stringify({ mode: 'execute', state: 'target_not_unique', located: found.count || 0, selector: sel, external_send: false }, null, 2));
    ws.close();
    return;
  }
  await ev(`(function(){document.querySelector(${JSON.stringify(sel)}).click();return 'clicked'})()`);
  await new Promise((r) => setTimeout(r, 2600));
  let rec = await capture('click');
  if (confirm && rec.dialog && rec.dialog.dialog && rec.dialog.buttons && rec.dialog.buttons.length) {
    const want = rec.dialog.buttons.find(function (t) { return /确认|提交|确定|继续|投递/.test(t); });
    if (want) {
      try {
        await ev(`(function(){var d=document.querySelector('[class*=dialog],[class*=modal],[class*=popup]');if(!d)return 'no_dialog';var b=Array.from(d.querySelectorAll('button')).find(function(x){return x.innerText.trim()===${JSON.stringify(want)}});if(!b)return 'no_btn';b.click();return 'confirmed:'+${JSON.stringify(want)};})()`);
        await new Promise((r) => setTimeout(r, 2600));
        rec = await capture('confirm');
        rec.confirmed_button = want;
      } catch (e) { rec.confirm_error = e.message; }
    }
  }
  const state = rec.success_markers.length ? 'success' : (rec.dialog && rec.dialog.dialog ? 'confirm_dialog' : 'unknown');
  console.log(JSON.stringify({ mode: 'execute', submit_kind: p.submit_kind, selector: sel, state: state, url_after: rec.url, title_after: rec.title, text_excerpt: rec.excerpt, success_markers: rec.success_markers, dialog: rec.dialog, screenshot: rec.screenshot, external_send: true }, null, 2));
  ws.close();
}

const argv = process.argv.slice(2);
let platform = 'boss';
const args = [];
for (let i = 0; i < argv.length; i++) {
  if (argv[i] === '--platform' && argv[i + 1]) { platform = argv[i + 1]; i++; }
  else if (argv[i] === '--url' && argv[i + 1]) { URL_FILTER = argv[i + 1]; i++; }
  else if (argv[i] === '--tab' && argv[i + 1]) { TAB_ID = argv[i + 1]; i++; }
  else args.push(argv[i]);
}
const p = PLATFORMS[platform];
if (!p) throw new Error('Unknown platform: ' + platform);
const cmd = args[0];
const arg = args[1];
const waitMs = Number(args[2] || 8000);

(async () => {
  if (cmd === 'apply' && !p.submit_selector) throw new Error('Submission adapter not configured');
  if (cmd === 'status') await status();
  else if (cmd === 'open') await open(arg);
  else if (cmd === 'close' && arg) await close(arg);
  else if (cmd === 'read') await read(arg, waitMs);
  else if (cmd === 'buttons') await buttons();
  else if (cmd === 'jobs') await jobs(p);
  else if (cmd === 'click' && arg) await click(arg);
  else if (cmd === 'html' && arg) await html(arg);
  else if (cmd === 'apply') await apply(p, arg === 'send');
  else if (cmd === 'q' && arg) await q(arg);
  else if (cmd === 'eval' && arg) await evaljs(arg);
  else if (cmd === 'clicksel' && arg) await clicksel(arg, args[2]);
  else if (cmd === 'setfile' && arg) await setfile(arg, args[2]);
  else if (cmd === 'upload' && arg) await upload(arg, args[2]);
  else if (cmd === 'setinput' && arg) await setinput(arg, args[2]);
  else if (cmd === 'sendmsg' && arg) await sendmsg(arg);
  else if (cmd === 'search') await search(p, arg, args[2]);
  else if (cmd === 'netcapture') await netcapture(Number(arg) || 180, args[2]);
  else if (cmd === 'shot') await shot(args[1]);
  else if (cmd === 'submit') await submitJob(p, arg === 'execute' || arg === 'confirm', arg === 'confirm');
  else { console.error('用法: node browser_cdp.js [--platform boss|zhaopin] status | open [url] | close <id> | read [url] [秒] | buttons | jobs | click <文字> | html <文字> | apply [send] | q <选择器> | eval <js> | clicksel <选择器> [序号] | setfile <选择器> <文件> | upload <按钮选择器> <文件> | setinput <选择器> <值> | search <关键词> <城市> | netcapture <秒> [url关键字]'); process.exit(1); }
})().catch((e) => { console.error('ERR', e.message); process.exit(1); });
