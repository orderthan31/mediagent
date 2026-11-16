// Offline literal captured-console contract, not native provider execution.
import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';
const raw = '[INFO] worker started\nERROR timeout: <img src=x onerror="window.__injected=1">';
const capture = {
  id: 'captured',
  at: '2026-11-16T10:33:11Z',
  level: 'UNKNOWN',
  message: 'THIS IS NOT THE CONSOLE TEXT',
  run_id: 'run',
  node_id: 'translate',
  source: 'console',
  provenance: 'captured',
  terminal_text: raw,
  stream: 'stderr',
};
const db = {
  id: 'stored',
  at: null,
  level: 'ERROR',
  message: 'SYNTHETIC DB FAILURE DO NOT RENDER',
  run_id: 'run',
  node_id: 'translate',
  source: 'stored_failure',
  provenance: 'recorded_state',
};
const bundle = await build({
  stdin: {
    resolveDir: process.cwd(),
    loader: 'tsx',
    contents: `import React from'react';import{createRoot}from'react-dom/client';import{JobLogExplorer}from'./src/JobLogExplorer';import{JobExecutionWorkspace}from'./src/JobExecutionWorkspace';window.__calls=[];createRoot(document.getElementById('root')).render(<JobExecutionWorkspace showSummary={false} activeTab="logs" onTabChange={()=>{}} status="failed" stages={[]} onStageSelect={()=>{}} onStageLogs={()=>{}} progress={null} data={null} logs={<JobLogExplorer jobId="job" runs={[{id:'run',node_id:'translate',label:'번역'}]} onRunChange={()=>{}}/>}/>);`,
  },
  bundle: true,
  write: false,
  outdir: 'offline-terminal',
  platform: 'browser',
  format: 'iife',
  define: { 'import.meta.env': '{}' },
  plugins: [
    {
      name: 'fake-api',
      setup(p) {
        p.onResolve({ filter: /^\.\/api$/ }, () => ({ path: 'api', namespace: 'fake' }));
        p.onLoad({ filter: /.*/, namespace: 'fake' }, () => ({
          contents: `export async function request(path,init={}){window.__calls.push({path,method:init.method||'GET'});return ${JSON.stringify({ job_id: 'job', records: [db, capture], terminal_records: [capture], sources: [{ run_id: 'run', node_id: 'translate', available: true, raw_available: true, truncated: false }], has_more: false, truncated: false, total_records: 2 })};}`,
          loader: 'js',
        }));
      },
    },
  ],
});
for (const width of [320, 390, 1280])
  test(`literal console and unboxed page tabs at ${width}px`, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      await page.setContent('<html lang="ko"><div id="root"></div></html>');
      await page.addStyleTag({
        content: bundle.outputFiles.find((f) => f.path.endsWith('.css')).text,
      });
      await page.addScriptTag({
        content: bundle.outputFiles.find((f) => f.path.endsWith('.js')).text,
      });
      const terminal = page.getByRole('log', { name: '터미널 출력' });
      await expect(terminal).toHaveText(raw);
      assert.equal(await page.locator('.job-log-explorer__record').count(), 0);
      assert.equal(await page.locator('.job-log-explorer__notice').count(), 0);
      assert.equal(await page.getByText('SYNTHETIC DB FAILURE DO NOT RENDER').count(), 0);
      assert.equal(await page.getByText('THIS IS NOT THE CONSOLE TEXT').count(), 0);
      assert.equal(await page.evaluate(() => window.__injected), undefined);
      assert.equal(await page.locator('img').count(), 0);
      const geometry = await page
        .locator('.job-workspace')
        .evaluate((node) => ({
          border: getComputedStyle(node).borderTopWidth,
          radius: getComputedStyle(node).borderRadius,
          overflow: getComputedStyle(node).overflow,
        }));
      assert.equal(geometry.border, '0px');
      assert.equal(geometry.radius, '0px');
      assert.notEqual(geometry.overflow, 'clip');
      await page.getByLabel('로그 검색').fill('timeout');
      await expect(terminal).toHaveText(raw);
      await page.getByLabel('로그 검색').fill('not present');
      await expect(terminal).toHaveText('로그 없음');
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      assert.ok(await page.evaluate(() => window.__calls.every((c) => c.method === 'GET')));
    } finally {
      await browser.close();
    }
  });
