// boss_greet.js — BOSS 批量打招呼（浏览器 fetch 动态 token + 随机延迟 + code=9 退避 + 每日上限）
// 用法：
//   node boss_greet.js --keyword "外包" --city 101210100 --count 5 [--dry-run]
//   node boss_greet.js --keyword "软件测试" --city 101280600 --count 3
const http = require('http');

function httpJson(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => { let d = ''; res.on('data', (c) => (d += c)); res.on('end', () => { try { resolve(JSON.parse(d)); } catch (e) { reject(e); } }); }).on('error', reject);
  });
}
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
function rand(min, max) { return min + Math.random() * (max - min); }

const argv = process.argv.slice(2);
function arg(name, def) {
  const i = argv.indexOf('--' + name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : def;
}
const KEYWORD = arg('keyword', '外包');
const CITY = arg('city', '101210100');
const COUNT = Number(arg('count', '5'));
const DRY = argv.includes('--dry-run');
const DELAY_MIN = Number(arg('delay-min', '4'));
const DELAY_MAX = Number(arg('delay-max', '10'));

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
    // 1. 搜索
    const searchExpr = `(async () => {
      const url = '/wapi/zpgeek/search/joblist.json?query=' + encodeURIComponent(${JSON.stringify(KEYWORD)}) + '&city=${CITY}&page=1&pageSize=30';
      const r = await fetch(url, { credentials: 'include', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      const d = await r.json();
      if (d.code !== 0) return JSON.stringify({ ok: false, error: 'SEARCH_FAIL', code: d.code, message: d.message });
      const jobs = (d.zpData && d.zpData.jobList) || [];
      return JSON.stringify({ ok: true, jobs: jobs.map(j => ({ n: j.jobName, b: j.brandName, s: j.securityId, e: j.encryptJobId, l: j.lid, c: j.contact, sal: j.salaryDesc })) });
    })()`;
    const searchRes = JSON.parse(await ev(searchExpr));
    if (!searchRes.ok) { console.log(JSON.stringify(searchRes)); ws.close(); return; }
    const jobs = searchRes.jobs;
    console.log(JSON.stringify({ stage: 'search', keyword: KEYWORD, city: CITY, total: jobs.length }));

    const target = jobs.slice(0, COUNT);
    const results = [];
    for (let i = 0; i < target.length; i++) {
      const j = target[i];
      if (j.c) { results.push({ job: j.n, brand: j.b, status: 'skip_already_contacted' }); continue; }
      if (DRY) { results.push({ job: j.n, brand: j.b, salary: j.sal, status: 'dry_run' }); continue; }
      // 2. friend/add
      const addExpr = `(async () => {
        const url = '/wapi/zpgeek/friend/add.json?jobId=' + encodeURIComponent(${JSON.stringify(j.e)}) + '&securityId=' + encodeURIComponent(${JSON.stringify(j.s)}) + '&lid=' + encodeURIComponent(${JSON.stringify(j.l || '')});
        const r = await fetch(url, { method: 'POST', credentials: 'include', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        const d = await r.json();
        return JSON.stringify({ code: d.code, message: d.message, encBossId: d.zpData && d.zpData.encBossId });
      })()`;
      const res = JSON.parse(await ev(addExpr));
      results.push({ job: j.n, brand: j.b, salary: j.sal, status: res.code === 0 ? 'ok' : 'fail', code: res.code, message: res.message });
      if (res.code === 9) {
        console.log(JSON.stringify({ stage: 'backoff', reason: 'code_9', wait_s: 30 }));
        await sleep(30000);
      }
      await sleep(rand(DELAY_MIN, DELAY_MAX) * 1000);
    }
    console.log(JSON.stringify({ stage: 'done', dry_run: DRY, results }, null, 2));
    ws.close();
  } catch (e) { console.log('ERR', e.message); ws.close(); }
})();
