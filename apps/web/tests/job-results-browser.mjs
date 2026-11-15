import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

const job = 'a'.repeat(32),
  run = 'b'.repeat(32);
const base = '/renewal/jobs/' + job;
const fixture = {
  runs: [
    {
      id: run,
      node_id: 'export',
      status: 'completed',
      result: {
        outputs: {
          transcript: { type: 'transcript', sha256: 'c'.repeat(64), bytes: 80 },
          video: { type: 'video', sha256: 'd'.repeat(64), bytes: 1000 },
          metadata: { type: 'media_metadata', sha256: 'e'.repeat(64), bytes: 20 },
        },
      },
    },
  ],
  agents: [
    {
      id: 'result',
      label: '결과',
      outputs: [
        {
          name: 'transcript',
          run_id: run,
          node_id: 'export',
          port: 'transcript',
          type: 'transcript',
        },
        { name: 'video', run_id: run, node_id: 'export', port: 'video', type: 'video' },
        { name: 'video', run_id: run, node_id: 'export', port: 'video', type: 'video' },
      ],
    },
  ],
};
const bundle = await build({
  stdin: {
    resolveDir: process.cwd(),
    loader: 'tsx',
    contents: `
    import React from 'react';import{createRoot}from'react-dom/client';import{JobFiles}from'./src/JobFiles';
    createRoot(document.getElementById('root')).render(<JobFiles base=${JSON.stringify(base)} {...${JSON.stringify(fixture)}}/>);`,
  },
  bundle: true,
  write: false,
  outdir: 'offline-results',
  platform: 'browser',
  format: 'iife',
  external: ['/fonts/*'],
  define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
});
for (const width of [320, 1280]) {
  test(`one result owner, one download per file, real inert text preview at ${width}px`, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
      const calls = [],
        errors = [];
      const context = await browser.newContext({ offline: true, viewport: { width, height: 900 } });
      await context.route('**/*', (route) => {
        const r = route.request(),
          url = new URL(r.url());
        if (url.origin !== 'https://results-offline.invalid') {
          return route.abort();
        }
        if (url.pathname === '/') {
          return route.fulfill({
            contentType: 'text/html',
            body: '<html lang="ko"><div id="root"></div></html>',
          });
        }
        calls.push({ path: url.pathname, method: r.method() });
        if (
          r.method() === 'GET' &&
          url.pathname === '/api' + base + '/artifacts/' + run + '/transcript'
        ) {
          return route.fulfill({
            contentType: 'text/plain',
            body: '<script>window.__unsafe=1</script>\nexact terminal-like text is inert here too',
          });
        }
        return route.abort();
      });
      const page = await context.newPage();
      page.on('pageerror', (error) => errors.push(error.message));
      await page.goto('https://results-offline.invalid/');
      await page.addStyleTag({
        content: bundle.outputFiles.find((f) => f.path.endsWith('.css')).text,
      });
      await page.addScriptTag({
        content: bundle.outputFiles.find((f) => f.path.endsWith('.js')).text,
      });
      const results = page.getByRole('region', { name: '결과 파일', exact: true });
      await expect(results).toHaveCount(1);
      await expect(
        results.getByRole('link', { name: '결과 영상 다운로드', exact: true }),
      ).toHaveCount(1);
      await expect(
        results.getByRole('link', { name: '전사문(JSON) 다운로드', exact: true }),
      ).toHaveCount(1);
      await expect(
        results.getByRole('button', { name: '영상 정보(JSON) 보기', exact: true }),
      ).not.toBeVisible();
      assert.deepEqual(calls, [], 'No automatic media/body request or preview generation');
      await results.getByRole('button', { name: '전사문(JSON) 보기', exact: true }).click();
      await expect(results.locator('.job-result-text')).toHaveText(
        '<script>window.__unsafe=1</script>\nexact terminal-like text is inert here too',
      );
      assert.equal(await page.evaluate(() => window.__unsafe), undefined);
      await results.getByRole('button', { name: '미리보기 닫기', exact: true }).click();
      await expect(results.getByRole('region', { name: '선택한 결과 보기' })).toHaveCount(0);
      assert.equal(calls.filter((c) => c.method !== 'GET').length, 0);
      assert.deepEqual(errors, []);
      assert.equal(
        await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
        false,
      );
    } finally {
      await browser.close();
    }
  });
}
