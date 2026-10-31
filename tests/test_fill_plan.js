const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { fillPlan } = require('./browser_pw');

async function fixture(run) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'job-fill-'));
  const file = path.join(dir, 'plan.json');
  fs.writeFileSync(file, JSON.stringify({ route: { application_form: 'https://example.test/form' }, steps: [
    { field: 'name', type: 'text', selector: '#name', value: 'fixture', status: 'prepared_needs_page_verification' },
    { field: 'submit', type: 'submit', status: 'separate_submission' },
  ] }));
  let value = '', writes = 0;
  const page = { url: () => 'https://example.test/form', locator: () => ({
    count: async () => 1, isEnabled: async () => true,
    fill: async v => { value = v; writes++; }, inputValue: async () => value,
  }) };
  try { await run({ page, file, writes: () => writes }); }
  finally { fs.rmSync(dir, { recursive: true }); }
}
test('preflight performs no fill or submit', async () => fixture(async ({ page, file, writes }) => {
  await fillPlan(page, file, false); assert.equal(writes(), 0);
}));
test('fill commits supported field once and does not submit', async () => fixture(async ({ page, file, writes }) => {
  await fillPlan(page, file, true); assert.equal(writes(), 1);
}));
test('wrong destination blocks before any write', async () => fixture(async ({ page, file, writes }) => {
  page.url = () => 'https://wrong.test/form';
  await assert.rejects(fillPlan(page, file, true), /DESTINATION/); assert.equal(writes(), 0);
}));
test('ambiguous field blocks before any write', async () => fixture(async ({ page, file, writes }) => {
  page.locator = () => ({ count: async () => 2 });
  await assert.rejects(fillPlan(page, file, true), /NOT_UNIQUE/); assert.equal(writes(), 0);
}));
