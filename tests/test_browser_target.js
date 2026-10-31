const test = require('node:test');
const assert = require('node:assert/strict');
const { selectTarget } = require('./browser_target');
const pages = [
  { id: '1', url: 'https://www.zhipin.com/web/geek/jobs' },
  { id: '2', url: 'https://i.zhaopin.com/resume' },
  { id: '3', url: 'https://example.org/?redirect=www.zhipin.com' },
];
test('platform routes to its own exact host', () => {
  assert.equal(selectTarget(pages, { hosts: ['i.zhaopin.com'] }).id, '2');
});
test('missing URL never falls back to another account or tab', () => {
  assert.throws(() => selectTarget(pages, { url: 'https://www.zhipin.com/missing' }), /TARGET_NOT_FOUND/);
});
test('URL fragment and spoofed host cannot match', () => {
  assert.throws(() => selectTarget(pages, { url: 'zhipin.com' }), /TARGET_NOT_FOUND/);
  assert.throws(() => selectTarget([pages[2]], { hosts: ['www.zhipin.com'] }), /TARGET_NOT_FOUND/);
});
test('multiple matching tabs require explicit choice', () => {
  assert.throws(() => selectTarget([...pages, { id: '4', url: pages[0].url }], { hosts: ['www.zhipin.com'] }), /AMBIGUOUS/);
  assert.equal(selectTarget(pages, { id: '1', hosts: ['www.zhipin.com'] }).id, '1');
});
test('tab ID cannot override site mismatch', () => {
  assert.throws(() => selectTarget(pages, { id: '2', hosts: ['www.zhipin.com'] }), /TARGET_NOT_FOUND/);
});
