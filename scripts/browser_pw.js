// browser_pw.js — Playwright 客户端（connectOverCDP 连现有宿主机 Chrome）
// 解决 CDP 文件上传不生效（真实点击触发 filechooser）+ 简化下拉/文本填写。
// 用法：
//   node scripts/browser_pw.js [--url <url片段>] upload <按钮选择器> <文件路径>
//   node scripts/browser_pw.js [--url <url片段>] fill <选择器> <值>
//   node scripts/browser_pw.js [--url <url片段>] click <选择器>
//   node scripts/browser_pw.js [--url <url片段>] select <触发器选择器> <选项文字>
//   node scripts/browser_pw.js [--url <url片段>] read
//   node scripts/browser_pw.js [--url <url片段>] eval <js代码>
const { selectTarget } = require('./browser_target');
const fs = require('fs');
const crypto = require('crypto');

const CDP = 'http://127.0.0.1:9222';

function parseArgs(argv) {
  let url = null;
  const rest = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--url') { url = argv[++i]; }
    else rest.push(argv[i]);
  }
  return { url, cmd: rest[0], args: rest.slice(1) };
}

async function getPage(urlFilter) {
  const { chromium } = require('playwright-core');
  const browser = await chromium.connectOverCDP(CDP);
  const pages = browser.contexts().flatMap(context => context.pages());
  let page;
  try {
    if (!urlFilter) throw new Error('--url <exact URL> is required');
    page = selectTarget(pages.map(page => ({ url: page.url(), page })), { url: urlFilter }).page;
  } catch (error) { await browser.close(); throw error; }
  return { browser, page };
}

async function upload(page, buttonSelector, filePath) {
  const [chooser] = await Promise.all([
    page.waitForEvent('filechooser', { timeout: 15000 }),
    page.click(buttonSelector),
  ]);
  await chooser.setFiles(filePath);
  console.log('FILE_SELECTED: verify server-side upload and saved attachment before proceeding');
}

async function fill(page, selector, value) {
  await page.fill(selector, value);
  if (await page.locator(selector).inputValue() !== value) throw new Error('FIELD_READBACK_MISMATCH');
  console.log('FIELD_READBACK_OK: ' + selector + '; server-side save not verified');
}

async function click(page, selector) {
  await page.click(selector);
  console.log('CLICKED:' + selector);
}

async function select(page, triggerSelector, optionText) {
  await page.click(triggerSelector);
  // searchable select：点开后在 filter input 里逐字输入以过滤（fill 可能不触发过滤，type 逐字触发）
  const filterInput = page.locator(triggerSelector + ' input');
  if (await filterInput.count()) {
    await filterInput.click();
    await filterInput.type(optionText);
    await page.waitForTimeout(600);
  }
  await page.locator('li, [role=option], [class*=option]').filter({ hasText: optionText }).first().click();
  console.log('SELECTED:' + optionText);
}

async function read(page) {
  const text = await page.evaluate(() => document.body.innerText);
  console.log(text.slice(0, 2500));
}

async function evaljs(page, code) {
  const r = await page.evaluate(code);
  console.log(JSON.stringify(r));
}

async function fillPlan(page, file, commit) {
  const plan = JSON.parse(fs.readFileSync(file, 'utf8'));
  const actual = new URL(page.url());
  const destinations = [plan.route?.resume, plan.route?.application_form].filter(Boolean);
  if (!destinations.some(url => {
    const expected = new URL(url);
    return actual.origin === expected.origin && actual.pathname === expected.pathname;
  })) throw new Error('FORM_DESTINATION_MISMATCH');
  const results = [];
  // Preflight the entire supported subset before the first write.
  const actions = [];
  for (const step of plan.steps) {
    if (step.status !== 'prepared_needs_page_verification' || !['text', 'file_upload'].includes(step.type)) {
      results.push({ field: step.field, status: 'not_executed', reason: step.reason || 'requires separate observed interaction' });
      continue;
    }
    if (step.value === undefined) throw new Error('PLAN_HAS_NO_VALUES: use execution.py --output');
    const locator = page.locator(step.selector);
    if (await locator.count() !== 1 || !(await locator.isEnabled())) throw new Error('FIELD_NOT_UNIQUE_OR_ENABLED: ' + step.field);
    if (step.type === 'file_upload') {
      const hash = crypto.createHash('sha256').update(fs.readFileSync(step.value)).digest('hex');
      if (hash !== step.sha256) throw new Error('ATTACHMENT_CHANGED: ' + step.field);
    }
    actions.push({ step, locator });
  }
  for (const { step, locator } of actions) {
    if (!commit) { results.push({ field: step.field, status: 'preflight_ok' }); continue; }
    if (step.type === 'text') {
      await locator.fill(String(step.value));
      if (await locator.inputValue() !== String(step.value)) throw new Error('FIELD_READBACK_MISMATCH: ' + step.field);
    } else {
      await locator.setInputFiles(step.value);
      const count = await locator.evaluate(el => el.files.length);
      if (count !== 1) throw new Error('ATTACHMENT_SELECTION_NOT_CONFIRMED');
    }
    results.push({ field: step.field, status: 'local_field_readback_ok', persisted: false });
    // Emit after each write so a later failure retains partial progress without values.
    console.log(JSON.stringify(results[results.length - 1]));
  }
  console.log(JSON.stringify({ mode: commit ? 'fill_only' : 'preflight', results,
    saved: 'unverified', submitted: false, note: 'Does not save or submit; verify server persistence separately.' }));
}

const { url, cmd, args } = parseArgs(process.argv.slice(2));

if (require.main === module) (async () => {
  try {
    const { browser, page } = await getPage(url);
    if (cmd === 'upload') await upload(page, args[0], args[1]);
    else if (cmd === 'fill-plan') await fillPlan(page, args[0], args[1] === '--commit');
    else if (cmd === 'fill') await fill(page, args[0], args[1]);
    else if (cmd === 'click') await click(page, args[0]);
    else if (cmd === 'select') await select(page, args[0], args[1]);
    else if (cmd === 'read') await read(page);
    else if (cmd === 'eval') await evaljs(page, args[0]);
    else { console.error('用法: [--url <片段>] upload <选择器> <文件> | fill <选择器> <值> | click <选择器> | select <选择器> <选项文字> | read | eval <js>'); process.exit(1); }
    await browser.close();
  } catch (e) {
    console.error('ERR', e.message);
    process.exit(1);
  }
})();
module.exports = { fillPlan };
