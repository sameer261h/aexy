// Drives the running app and saves one image per pull-request claim.
// Run through capture.sh, which supplies TOK and WS.
import { createRequire } from 'module';

// Playwright lives in the frontend workspace, not next to this file.
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium } = require('@playwright/test');

const { TOK, WS, SEQ } = process.env;
const OUT = new URL('.', import.meta.url).pathname;
const BASE = 'http://localhost:3000';

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, colorScheme: 'dark' });
await context.addInitScript(([token, workspace]) => {
  localStorage.setItem('token', token);
  localStorage.setItem('current_workspace_id', workspace);
  localStorage.setItem('aexy-theme', JSON.stringify({ state: { theme: 'dark' }, version: 0 }));
}, [TOK, WS]);
const page = await context.newPage();


const SHOTS = [
  { file: 'pr1-slack-connected',    url: '/settings/integrations', role: ['button', 'Slack'] },
  { file: 'pr2-records-grid',       url: '/crm/deal' },
  { file: 'pr3-deals-board',        url: '/crm/deal', role: ['button', 'Board'], pause: 3000 },
  { file: 'pr3-lists-membership',   url: '/crm/deal', role: ['button', 'Lists'] },
  { file: 'pr4-sequences-list',     url: '/crm/sequences', wait: 4000 },
  SEQ && { file: 'pr4-sequence-detail', url: `/crm/sequences/${SEQ}`, wait: 4500 },
  { file: 'pr5-trigger-palette',    url: '/automations/85763658-5f67-4d93-895e-1929059712c4', wait: 5000 },
  { file: 'pr6-test-run-skipped',   url: '/automations/85763658-5f67-4d93-895e-1929059712c4', wait: 5000,
    steps: [{ role: ['button', 'Test'] }, { pause: 2000 },
            { select: '[role=dialog] select, .fixed select' }, { pause: 1000 },
            { text: 'Run Test' }, { pause: 11000 }] },
  { file: 'pr7-run-history',        url: '/automations/85763658-5f67-4d93-895e-1929059712c4', wait: 5000,
    steps: [{ css: 'button[title*=History], button[aria-label*=History]' }, { pause: 3000 }] },
].filter(Boolean);

for (const shot of SHOTS) {
  try {
    await page.goto(BASE + shot.url, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(shot.wait ?? 2500);
    const steps = shot.steps ?? [shot.role && { role: shot.role }, shot.pause && { pause: shot.pause }].filter(Boolean);
    for (const s of steps) {
      if (s.role)   await page.getByRole(s.role[0], { name: s.role[1] }).first().click({ timeout: 8000 });
      if (s.text)   await page.getByText(s.text, { exact: false }).first().click({ timeout: 8000 });
      if (s.css)    await page.locator(s.css).first().click({ timeout: 8000 });
      if (s.select) { const sel = page.locator(s.select).first();
                      const vals = await sel.locator('option').evaluateAll(o => o.map(x => x.value).filter(Boolean));
                      await sel.selectOption(vals[0]); }
      if (s.pause)  await page.waitForTimeout(s.pause);
    }
    await page.waitForTimeout(1500);
    await page.screenshot({ path: OUT + shot.file + '.png' });
    console.log('   ok   ' + shot.file);
  } catch (e) {
    console.log('   FAIL ' + shot.file + ' — ' + String(e).split('\n')[0].slice(0, 80));
  }
}
await browser.close();
