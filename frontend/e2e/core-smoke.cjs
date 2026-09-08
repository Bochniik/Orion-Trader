/* Production-browser regression with deterministic HTTP fixtures, never market data.
 * Build first. Set ORION_PLAYWRIGHT_MODULE to an installed Playwright package if
 * it is not on Node's module path. Optional ORION_E2E_OUTPUT stores screenshots.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.ORION_PLAYWRIGHT_MODULE || 'playwright');
const output = process.env.ORION_E2E_OUTPUT || fs.mkdtempSync(path.join(os.tmpdir(), 'orion-core-qa-'));
fs.mkdirSync(output, { recursive: true });
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1', '--port', '4173', '--strictPort'], { cwd: path.resolve(__dirname, '..'), stdio: 'pipe' });
let browser;
let serverLog = '';
server.stdout.on('data', value => { serverLog += value; });
server.stderr.on('data', value => { serverLog += value; });
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

function decision(ticker) {
  const timestamp = new Date(Date.now() - 10000).toISOString();
  return {
    ticker, company_name: `${ticker} test company`, timestamp, evaluated_at: timestamp,
    expires_at: new Date(Date.now() + 300000).toISOString(), direction: 'LONG', decision: 'BUY',
    actionable: true, status: 'qualified', confidence: 80, confidence_kind: 'calibrated_directional_probability',
    entry_zone: [99, 100], invalidation: 98, targets: [104, 105], risk_reward: 2,
    expected_move: 0.4, timeframe: '5m', liquidity_tier: 'A', liquidity_score: 90,
    market_regime: 'Bullish Trend', reasons: ['Relative volume, momentum and the validated model agree.'], warnings: [],
    semantics: 'Test fixture. Not a recommendation or live market result.',
    model_outputs: { quote_as_of: timestamp }, evidence: null, decision_id: `decision-${ticker}`,
  };
}

(async () => {
  try {
    for (let attempt = 0; attempt < 40; attempt++) {
      try { if ((await fetch('http://127.0.0.1:4173')).ok) break; } catch {}
      if (attempt === 39) throw new Error(`Preview failed: ${serverLog}`);
      await pause(150);
    }
    browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, serviceWorkers: 'block' });
    const page = await context.newPage();
    const errors = [], requests = [];
    page.on('pageerror', error => errors.push(error.message));
    let mode = 'empty', saved = ['AAPL'], checked = false, connected = false;
    const jobs = new Map();
    const plans = new Map();
    await context.route('**/api/**', async route => {
      const request = route.request(), url = new URL(request.url());
      const endpoint = url.pathname.replace(/^\/api/, '');
      const method = request.method();
      requests.push(`${method} ${endpoint}`);
      if (method !== 'GET') assert.equal(request.headers()['x-csrf-token'], 'fixture-csrf');
      let data = {}, status = 200;
      if (endpoint === '/auth/session') data = { user: { id: 'fixture-user', email: 'test@example.com' }, csrf_token: 'fixture-csrf' };
      else if (endpoint === '/auth/logout') data = { logged_out: true };
      else if (endpoint === '/watchlist') data = { tickers: saved };
      else if (endpoint.startsWith('/watchlist/')) {
        const ticker = decodeURIComponent(endpoint.split('/').at(-1));
        saved = method === 'DELETE' ? saved.filter(item => item !== ticker) : [...new Set([...saved, ticker])];
        data = { tickers: saved };
      } else if (endpoint === '/core/jobs' && method === 'POST') {
        const body = request.postDataJSON();
        const id = `job-${jobs.size}`;
        let result;
        if (body.kind === 'today') result = { status: mode === 'unavailable' ? 'unavailable' : 'ready', generated_at: new Date().toISOString(),
          message: mode === 'unavailable' ? 'No saved model has passed validation.' : 'No high-quality setups detected right now.',
          opportunities: mode === 'qualified' ? [decision('NVDA'), decision('MSFT')] : [],
          coverage: { liquidity_candidates_ranked: 80, unique_tickers: 16 }, scope: 'Deterministic test sample.' };
        else if (body.kind === 'analyze') result = decision(body.ticker);
        else result = { plans: [...plans.values()] };
        jobs.set(id, { id, state: body.ticker === 'SLOW' ? 'running' : mode === 'error' ? 'failed' : 'completed', stage: mode === 'error' ? 'Test provider unavailable.' : 'Reviewing evidence', result });
        data = { id, state: 'running', stage: 'Checking data readiness' }; status = 202;
      } else if (endpoint.startsWith('/core/jobs/')) {
        const id = endpoint.split('/').at(-1);
        if (method === 'DELETE') jobs.set(id, { id, state: 'cancelled', stage: 'Cancelled' });
        data = jobs.get(id);
      } else if (endpoint === '/core/plans') data = { plans: [...plans.values()] };
      else if (endpoint === '/core/decisions') data = { decisions: [] };
      else if (endpoint.startsWith('/core/plans/')) {
        const id = endpoint.split('/').at(-1);
        if (method === 'DELETE') plans.delete(id);
        else plans.set(id, { decision_id: id, decision: decision(id.replace('decision-', '')), latest_check: null });
        data = { enabled: method !== 'DELETE' };
      } else if (endpoint === '/search') data = { results: [] };
      else if (endpoint.startsWith('/quote/')) data = { ticker: endpoint.split('/').at(-1), price: 100, change_percent: 1, volume: 50000000 };
      else if (endpoint.startsWith('/candles/')) data = { candles: Array.from({ length: 70 }, (_, i) => ({ time: new Date(Date.UTC(2026, 5, i + 1)).toISOString().slice(0, 10), open: 100+i, high: 102+i, low: 99+i, close: 101+i, volume: 1000000+i*1000 })) };
      else if (endpoint === '/portfolio/active') data = { source: 'local', source_label: 'Local simulated portfolio', currency: 'USD', total_value: 10000, cash: 9700, positions: { MSFT: { ticker: 'MSFT', quantity: 3, average_price: 100, market_value: 300, allocation_percent: 3 } }, trades: [] };
      else if (endpoint === '/alerts' || endpoint === '/alerts/check') {
        if (endpoint.endsWith('/check')) checked = true;
        data = { alerts: [{ id: 1, ticker: 'AAPL', enabled: true, triggered: checked, message: checked ? 'AAPL reached the saved price threshold.' : null, last_checked_at: checked ? new Date().toISOString() : null }] };
      } else if (endpoint === '/workspace') data = { active_source: 'local', alpaca: { connected }, trading212_demo: { connected: false } };
      else if (endpoint === '/broker/alpaca/connect') { connected = true; data = { status: { connected: true } }; }
      else if (endpoint === '/broker/alpaca/disconnect') { connected = false; }
      else throw new Error(`Unmocked API request: ${method} ${endpoint}`);
      await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
    });
    await page.goto('http://127.0.0.1:4173');
    await page.getByRole('heading', { name: 'No high-quality setups detected right now.' }).waitFor();
    assert.equal(await page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button').count(), 3);
    assert.ok(page.url().endsWith('#/today'));
    mode = 'qualified';
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.getByRole('article', { name: 'NVDA analysis' }).waitFor();
    await page.screenshot({ path: path.join(output, 'today-desktop.png'), fullPage: true });
    await page.getByRole('article', { name: 'NVDA analysis' }).getByRole('button', { name: 'Analyze', exact: true }).click();
    await page.getByRole('heading', { name: 'NVDA', exact: true }).waitFor();
    const input = page.getByLabel('Stock ticker or company');
    await input.fill('SLOW');
    const pendingSlow = page.waitForRequest(request => request.url().endsWith('/core/jobs') && request.postDataJSON()?.ticker === 'SLOW');
    await page.getByRole('button', { name: 'Analyze', exact: true }).last().click();
    await pendingSlow;
    await input.fill('MSFT');
    await input.press('Enter');
    await page.getByRole('heading', { name: 'MSFT', exact: true }).waitFor();
    await pause(550);
    assert.equal(await page.getByRole('heading', { name: 'SLOW', exact: true }).count(), 0);
    await page.getByRole('button', { name: 'Save stock', exact: true }).click();
    await page.getByRole('button', { name: 'Saved', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Save plan to monitor', exact: true }).click();
    await page.getByRole('button', { name: 'Plan saved', exact: true }).waitFor();
    await page.screenshot({ path: path.join(output, 'analyze-desktop.png'), fullPage: true });
    await page.locator('.core-chart > summary').click();
    await page.locator('canvas').first().waitFor();
    assert.ok(await page.locator('canvas').count() > 0);
    await page.getByRole('navigation').getByRole('button', { name: 'My Stocks', exact: true }).click();
    await page.getByRole('button', { name: 'Stop monitoring', exact: true }).waitFor();
    await page.locator('.watchlist-row').filter({ hasText: 'MSFT' }).getByRole('button', { name: 'Remove', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Check saved alerts now' }).click();
    await page.getByText('AAPL reached the saved price threshold.').waitFor();
    await page.locator('.watchlist-row').filter({ hasText: 'MSFT' }).getByRole('button', { name: 'Remove', exact: true }).click();
    await page.getByText('MSFT removed from your watchlist. Positions are unchanged.').waitFor();
    assert.equal(await page.locator('.core-position-list').getByRole('button').count(), 1);
    await page.screenshot({ path: path.join(output, 'my-stocks-desktop.png'), fullPage: true });
    await page.getByRole('button', { name: 'Data & account', exact: true }).click();
    await page.getByRole('dialog').waitFor();
    await page.getByLabel('Paper API key', { exact: true }).fill('not-a-real-key');
    await page.getByLabel('Secret key', { exact: true }).fill('not-a-real-secret');
    await page.getByRole('button', { name: 'Connect data' }).click();
    await page.getByRole('button', { name: 'Disconnect', exact: true }).waitFor();
    assert.ok(!(await page.evaluate(() => JSON.stringify(localStorage))).includes('not-a-real'));
    await page.keyboard.press('Escape');
    assert.equal(await page.getByRole('dialog').count(), 0);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('navigation').getByRole('button', { name: 'Analyze', exact: true }).click();
    await page.getByRole('heading', { name: 'MSFT', exact: true }).waitFor();
    await page.screenshot({ path: path.join(output, 'analyze-mobile.png'), fullPage: true });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.getByRole('navigation').getByRole('button', { name: 'Today', exact: true }).click();
    await page.getByRole('article', { name: 'NVDA analysis' }).waitFor();
    await page.screenshot({ path: path.join(output, 'today-mobile.png'), fullPage: true });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    mode = 'unavailable';
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.getByRole('heading', { name: 'Market scan unavailable' }).waitFor();
    mode = 'error';
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.getByRole('heading', { name: 'Unable to check the market' }).waitFor();
    assert.equal(await page.getByRole('article').count(), 0);
    await page.getByRole('button', { name: 'Data & account', exact: true }).click();
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await page.getByRole('heading', { name: 'Enter OrionTrader', exact: true }).waitFor();
    assert.equal(await page.getByRole('navigation').count(), 0);
    assert.deepEqual(errors, []);
    assert.ok(!requests.some(value => /orders|autonomy|models\/train/.test(value)));
    assert.ok(requests.some(value => value.startsWith('DELETE /core/jobs/')));
    console.log(`PASS: production navigation, race protection, chart, watchlist/position separation, alerts, connections, mobile overflow, error states, logout, no training/order requests. Screenshots: ${output}`);
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
