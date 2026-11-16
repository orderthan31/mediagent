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
    const root=createRoot(document.getElementById('root')); const props=${JSON.stringify(fixture)};
    window.renderFiles=(overrides={})=>root.render(<JobFiles base=${JSON.stringify(base)} {...props} onOpenLogs={(id)=>window.openedLog=id} {...overrides}/>); window.renderFiles();`,
  },
  bundle: true,
  write: false,
  outdir: 'offline-results',
  platform: 'browser',
  format: 'iife',
  external: ['/fonts/*'],
  define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
});
for (const width of [390, 1280]) {
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
      ).toBeVisible();
      assert.deepEqual(calls, [], 'No automatic media/body request or preview generation');
      await expect(results.getByRole('columnheader')).toHaveCount(6);
      await expect(results.locator('[data-result-key]')).toHaveCount(3);
      await results.getByRole('searchbox', { name: '파일 검색', exact: true }).fill('metadata');
      await expect(results.locator('[data-result-key]')).toHaveCount(1);
      await results.getByRole('button', { name: '필터 초기화', exact: true }).click();
      await results
        .getByRole('combobox', { name: '유형', exact: true })
        .selectOption('intermediate');
      await expect(results.locator('[data-result-key]')).toHaveCount(1);
      await results.getByRole('button', { name: '필터 초기화', exact: true }).click();
      await results.getByRole('button', { name: '전사문(JSON) 보기', exact: true }).click();
      await expect(results.locator('.job-result-text')).toHaveText(
        '<script>window.__unsafe=1</script>\nexact terminal-like text is inert here too',
      );
      assert.equal(await page.evaluate(() => window.__unsafe), undefined);
      await results.getByRole('button', { name: '미리보기 닫기', exact: true }).click();
      await expect(results.getByRole('region', { name: '선택한 결과 보기' })).toHaveCount(0);
      // Pending old text is fenced on job/source identity, not just the row label.
      await results.getByRole('button', { name: '전사문(JSON) 보기', exact: true }).click();
      await expect(results.locator('.job-result-text')).toBeVisible();
      await page.evaluate(() =>
        window.renderFiles({ base: '/renewal/jobs/' + '9'.repeat(32), stale: true }),
      );
      await expect(results.getByRole('region', { name: '선택한 결과 보기' })).toHaveCount(0);
      await expect(results.getByRole('alert')).toContainText('마지막 확인 결과');
      await page.evaluate(() =>
        window.renderFiles({
          runs: [
            { id: 'failure', node_id: 'translate', status: 'failed' },
            { id: 'waiting', node_id: 'encode', status: 'waiting' },
          ],
        }),
      );
      await expect(results.locator('a[download]')).toHaveCount(0);
      await expect(results.locator('[data-stage-run]')).toHaveCount(2);
      await results
        .locator('[data-stage-run="failure"]')
        .getByRole('button', { name: '로그', exact: true })
        .click();
      assert.equal(await page.evaluate(() => window.openedLog), 'failure');
      await results.getByRole('combobox', { name: '상태', exact: true }).selectOption('waiting');
      await expect(results.locator('[data-stage-run]')).toHaveCount(1);
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
