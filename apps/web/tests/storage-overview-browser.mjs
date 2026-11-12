// Actual workspace and authenticated settings route; synthetic offline reads only.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

test('storage menu and independent read states fit PC and 390px without mutations', async () => {
  const apiPath = path.resolve('src/api.ts');
  const bundle = await build({
    stdin: {
      resolveDir: process.cwd(),
      loader: 'tsx',
      contents: `import React from 'react';import{createRoot}from'react-dom/client';
        import{AuthGate}from'./src/AuthGate';import{VideoWorkspace}from'./src/VideoWorkspace';import{PageTitleProvider}from'./src/PageTitle';
        window.__calls=[];window.__modes={totals:'defer',resources:'defer'};window.__release={};
        window.__totals={originals:{count:'23',bytes:'34212632653'},observed_at:'2026-01-01T00:00:00+00:00'};
        window.__resources={status:'connected',observed_at:'2026-01-01T00:00:00Z',storage:[
          {name:'C:',source:'Host physical disk',status:'connected',total:10737418240,free:3221225472},
          {name:'Object storage',source:'Connected object volume',status:'connected',total:21474836480,free:4294967296},
          {name:'PRIVATE /host/path',source:'PRIVATE credential-owner',status:'unavailable'}]};
        createRoot(document.getElementById('root')).render(<AuthGate><PageTitleProvider><VideoWorkspace/></PageTitleProvider></AuthGate>);`,
    },
    bundle: true,
    write: false,
    platform: 'browser',
    format: 'iife',
    define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
    loader: { '.css': 'empty' },
    plugins: [
      {
        name: 'offline-api',
        setup(plugin) {
          plugin.onResolve({ filter: /api$/ }, (args) =>
            path.resolve(path.dirname(args.importer), args.path + '.ts') === apiPath
              ? { path: 'api', namespace: 'offline' }
              : undefined,
          );
          plugin.onLoad({ filter: /.*/, namespace: 'offline' }, () => ({
            loader: 'js',
            contents: `
        export const base='/api';export const mediaUrl=p=>'/api'+p;export class ApiError extends Error{}
        export const request=async(path,init={})=>{const method=init.method||'GET';window.__calls.push({path,method});
          if(method!=='GET')throw new Error('unit forbids mutation');
          const kind=path==='/renewal/storage-overview'?'totals':path==='/system/resources'?'resources':null;
          if(kind){const mode=window.__modes[kind];if(mode==='error')throw new Error('PRIVATE DSN/query error');
            if(mode==='defer')return new Promise((resolve,reject)=>{window.__release[kind]=resolve;init.signal?.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError')));});
            return structuredClone(window['__'+kind]);}
          if(path==='/auth/session')return{enabled:true,user:{id:'unit-admin',username:'unit-admin',role:window.__ordinary?'user':'admin'}};
          if(path==='/capabilities')return{features:['verified_uploads']};
          if(path==='/videos')return{videos:[]};if(path==='/jobs')return{jobs:[]};if(path==='/video-uploads')return{uploads:[]};
          throw new Error('unexpected offline GET '+path);};
        export const uploadRequest=request;export const resumeUpload=()=>{throw new Error('unit forbids upload')};
      `,
          }));
        },
      },
    ],
  });
  const browser = await chromium.launch({
    channel: process.platform === 'win32' ? 'msedge' : undefined,
    headless: true,
  });
  try {
    const context = await browser.newContext({ offline: true });
    await context.route('**/*', (route) => route.abort());
    const css = fs
      .readdirSync('dist/assets')
      .filter((name) => name.endsWith('.css'))
      .map((name) => fs.readFileSync(path.join('dist/assets', name), 'utf8'))
      .join('\n');
    for (const width of [1440, 390]) {
      const page = await context.newPage();
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await page.route('https://storage-unit.invalid/', (route) =>
        route.fulfill({
          contentType: 'text/html',
          body: '<!doctype html><html lang="ko"><body><div id="root"></div></body></html>',
        }),
      );
      await page.goto('https://storage-unit.invalid/#/settings');
      await page.addStyleTag({ content: css });
      await page.addScriptTag({ content: bundle.outputFiles[0].text });
      for (const name of ['공급자·API 키 설정', '모델 설정', '워크플로우 설정']) {
        await expect(page.getByRole('link', { name, exact: false })).toBeVisible();
      }
      await page.getByRole('link', { name: '저장소 현황', exact: false }).click();
      const originals = page.getByRole('region', { name: '등록된 원본' });
      const resources = page.getByRole('region', { name: '저장 공간 관측' });
      await expect(originals).toContainText('확인 중');
      await expect(resources).toContainText('확인 중');
      assert.equal(await originals.getByText('0개', { exact: true }).count(), 0);
      assert.equal(await originals.getByText('0.00 GB', { exact: true }).count(), 0);
      await page.evaluate(() =>
        window.__release.totals({ ...window.__totals, originals: { count: '0', bytes: '0' } }),
      );
      await expect(originals).toContainText('0개');
      await expect(originals).toContainText('0.00 GB');
      await expect(resources).toContainText('확인 중');
      await page.evaluate(() =>
        window.__release.resources({ status: 'unavailable', nodes: [], storage: [] }),
      );
      await expect(resources).toContainText('관측 없음');
      assert.equal(await resources.locator('dd').count(), 0);
      await expect(originals).toContainText('0개');
      await page.evaluate(() => {
        window.__modes = { totals: 'success', resources: 'success' };
      });
      await originals.getByRole('button', { name: '다시 확인', exact: true }).click();
      await resources.getByRole('button', { name: '다시 확인', exact: true }).click();
      await expect(originals).toContainText('23개');
      await expect(originals).toContainText('34.21 GB');
      await expect(originals).toContainText('논리 용량');
      const disks = resources.locator('.storage-measurement');
      await expect(disks.nth(0).locator('dd')).toHaveText(['10.74 GB', '7.52 GB', '3.22 GB']);
      await expect(disks.nth(1).locator('dd')).toHaveText(['21.47 GB', '17.18 GB', '4.29 GB']);
      assert.equal(await disks.nth(2).locator('dd').count(), 0);
      await expect(resources).not.toContainText('GiB');
      await expect(originals).not.toContainText('bytes');
      await expect(resources).toContainText('미확인');
      await expect(resources).toContainText('관측 시각');
      // Section headings are document content, not the global sticky application header.
      for (const region of [originals, resources]) {
        const heading = region.getByRole('heading', { level: 2 }).locator('..');
        const style = await heading.evaluate((node) => {
          const computed = getComputedStyle(node);
          return { position: computed.position, zIndex: computed.zIndex };
        });
        assert.deepEqual(style, { position: 'static', zIndex: 'auto' });
        await region.getByRole('button', { name: '다시 확인', exact: true }).click({ trial: true });
      }
      await expect(page.locator('main.settings-page')).not.toContainText('PRIVATE');
      await page.evaluate(() => {
        window.__modes = { totals: 'error', resources: 'error' };
      });
      await originals.getByRole('button', { name: '다시 확인', exact: true }).click();
      await resources.getByRole('button', { name: '다시 확인', exact: true }).click();
      await expect(originals).toContainText('조회 실패');
      await expect(originals).toContainText('이전 확인값');
      await expect(originals).toContainText('34.21 GB');
      await expect(resources).toContainText('조회 실패');
      await expect(resources).toContainText('이전 관측값');
      await expect(page.locator('main.settings-page')).not.toContainText('PRIVATE');
      await page.evaluate(() => {
        window.__modes.resources = 'success';
        window.__resources = { status: 'stale', observed_at: '2025-01-01T00:00:00Z', storage: [] };
      });
      await resources.getByRole('button', { name: '다시 확인', exact: true }).click();
      await expect(resources).toContainText('관측이 오래됨');
      await expect(resources).toContainText('2025');
      await expect(resources).not.toContainText('10.74 GB');
      for (const element of [
        originals,
        resources,
        originals.getByRole('button'),
        resources.getByRole('button'),
      ]) {
        const box = await element.boundingBox();
        assert.ok(box && box.x >= 0 && box.x + box.width <= width + 1, JSON.stringify(box));
      }
      assert.equal(
        await page
          .locator('main.settings-page')
          .getByRole('button', { name: /삭제|정리|승인|활성|만료/ })
          .count(),
        0,
      );
      assert.ok((await page.evaluate(() => window.__calls)).every((call) => call.method === 'GET'));
      await page.getByRole('link', { name: '시스템 설정으로', exact: true }).click();
      await expect(page.getByRole('link', { name: '저장소 현황', exact: false })).toBeVisible();
      // Re-entry starts from unknown; errors must not inherit confirmed zero or old measurements.
      await page.evaluate(() => {
        window.__modes = { totals: 'error', resources: 'error' };
      });
      await page.getByRole('link', { name: '저장소 현황', exact: false }).click();
      await expect(originals).toContainText('조회 실패');
      await expect(resources).toContainText('조회 실패');
      assert.equal(await originals.locator('dd').count(), 0);
      assert.equal(await resources.locator('dd').count(), 0);
      await page.evaluate(() => {
        window.__modes = { totals: 'success', resources: 'success' };
        window.__totals.originals = { count: '2', bytes: '9007199254740993' };
        window.__resources = { status: 'connected', storage: [] };
      });
      await originals.getByRole('button', { name: '다시 확인', exact: true }).click();
      await resources.getByRole('button', { name: '다시 확인', exact: true }).click();
      await expect(originals).toContainText('9007199.25 GB');
      await expect(originals).toContainText('2개');
      await expect(resources).toContainText('수집된 저장 공간 없음');
      await expect(resources).toContainText('관측 시각 미확인');
      await page.close();
    }
    const ordinary = await context.newPage();
    await ordinary.route('https://storage-unit.invalid/', (route) =>
      route.fulfill({
        contentType: 'text/html',
        body: '<!doctype html><html lang="ko"><body><div id="root"></div></body></html>',
      }),
    );
    await ordinary.goto('https://storage-unit.invalid/#/settings/storage');
    await ordinary.evaluate(() => {
      window.__ordinary = true;
    });
    await ordinary.addScriptTag({ content: bundle.outputFiles[0].text });
    await expect(ordinary.getByRole('alert')).toContainText('관리자만 이용');
    assert.equal(
      (await ordinary.evaluate(() => window.__calls)).filter(
        (call) => call.path === '/renewal/storage-overview' || call.path === '/system/resources',
      ).length,
      0,
    );
    await ordinary.close();
  } finally {
    await browser.close();
  }
});
