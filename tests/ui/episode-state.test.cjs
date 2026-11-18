// DOM unit tests (no browser):
// npm install --prefix /tmp/ctxvault-ui-tests jsdom
// NODE_PATH=/tmp/ctxvault-ui-tests/node_modules node --test tests/ui/episode-state.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { JSDOM } = require('jsdom');
const { runInContext } = require('node:vm');

const staticDir = resolve(__dirname, '../../src/ctxvault/ui/static');

function setup() {
  const dom = new JSDOM('<div id="app"></div>', { url: 'http://localhost/', runScripts: 'outside-only' });
  const { window } = dom;
  const context = dom.getInternalVMContext();
  // Load the real bundled components, but mount the detail directly so this
  // exercises component reconciliation without a server or browser.
  for (const file of ['vendor/preact.umd.js', 'vendor/preact-hooks.umd.js', 'vendor/htm.umd.js', 'data.js']) {
    runInContext(readFileSync(resolve(staticDir, file), 'utf8'), context);
  }
  runInContext(readFileSync(resolve(staticDir, 'app.js'), 'utf8')
    .replace('render(html`<${App} />`, document.getElementById("app"));', '') + `
    CV.setNow(Date.parse('2026-11-18T10:00:00Z'));
    const episodes = ['alpha', 'beta'].map((id, i) => ({
      id, content: id + ' statement', source: 'owner',
      recorded_at: '2026-01-01T09:00:00Z', valid_from: '2026-01-01T09:00:00Z',
      confirmed_count: 1, last_confirmed_at: '2026-10-01T09:00:00Z',
      attestations: [{ at: '2026-10-01T09:00:00Z', source: id + ' verifier', metadata: { run_id: id + '-confirm' } }],
      closures: [{ closed_at: '2026-10-02T09:00:00Z', reason: id + ' repair', metadata: { run_id: id + '-close' },
        reopened_at: '2026-10-03T09:00:00Z', reopen_reason: id + ' repaired', reopen_metadata: { run_id: id + '-reopen' } }],
      disputes: [{ with: i ? 'alpha' : 'beta', noticed_at: '2026-10-04T09:00:00Z', metadata: { run_id: id + '-dispute' } }]
    }));
    const all = CV.statements(episodes), byId = new Map(all.map(x => [x.id, x]));
    window.selectEpisode = (id) => render(SidePanel({
      s: { sel: id }, setState() {}, all, byId, next: CV.successors(all),
      dec: x => ({ ...x, st: 'open', disputed: false }), at: CV.R.now, past: false
    }), document.getElementById('app'));
  `, context);
  const root = window.document.getElementById('app');
  const flush = () => new Promise(resolve => window.setTimeout(resolve, 0));
  const metadataButtons = () => [...root.querySelectorAll('button')].filter(b => b.textContent === 'run_id');
  return { window, root, flush, metadataButtons };
}

for (const [index, event] of ['close', 'reopen', 'dispute'].entries()) {
  test(`${event} metadata resets when selecting another episode`, async () => {
    const { window, root, flush, metadataButtons } = setup();
    try {
      window.selectEpisode('alpha');
      assert.equal(metadataButtons().length, 3);
      metadataButtons()[index].click();
      await flush();
      assert.ok(root.textContent.includes(`alpha-${event}`));
      // A refresh of the same episode must not close the active control.
      window.selectEpisode('alpha');
      assert.ok(root.textContent.includes(`alpha-${event}`));
      window.selectEpisode('beta');
      assert.ok(!root.textContent.includes(`beta-${event}`));
      assert.ok(!root.textContent.includes(`alpha-${event}`));
      window.selectEpisode('alpha');
      assert.ok(!root.textContent.includes(`alpha-${event}`));
    } finally { window.close(); }
  });
}

test('confirmations and their metadata reset when selecting another episode', async () => {
  const { window, root, flush, metadataButtons } = setup();
  const summary = () => [...root.querySelectorAll('div.hv-ac')].find(e => e.textContent.includes('1 time'));
  try {
    window.selectEpisode('alpha');
    assert.equal(metadataButtons().length, 3);
    summary().click();
    await flush();
    assert.equal(metadataButtons().length, 4);
    metadataButtons()[3].click();
    await flush();
    assert.ok(root.textContent.includes('alpha-confirm'));
    window.selectEpisode('alpha');
    assert.ok(root.textContent.includes('alpha-confirm'));
    window.selectEpisode('beta');
    assert.equal(metadataButtons().length, 3);
    assert.ok(!root.textContent.includes('alpha-confirm'));
    summary().click();
    await flush();
    assert.equal(metadataButtons().length, 4);
    assert.ok(!root.textContent.includes('beta-confirm'));
    window.selectEpisode('alpha');
    assert.equal(metadataButtons().length, 3);
  } finally { window.close(); }
});
