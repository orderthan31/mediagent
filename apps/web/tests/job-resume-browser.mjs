// Actual React component in Chromium, fully offline: no API/provider/runtime calls.
import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';
const snapshot = {
  id: 'job',
  revision: 3,
  status: 'running',
  access: { can_manage: true },
  runs: [{ id: 'run', status: 'completed', result: { unit_recovery: { id: 'receipt' } } }],
  reviews: [],
};
async function setup(browser, patch = {}) {
  const bundle = await build({
    stdin: {
      resolveDir: process.cwd(),
      loader: 'tsx',
      contents: `
 import React,{useState} from 'react';import{createRoot}from'react-dom/client';import{JobResumeControl}from'./src/JobResumeControl';
 window.__view=${JSON.stringify({ ...snapshot, ...patch })};window.__calls=[];window.__mode='ok';window.__changed=0;
 function App(){const[job,setJob]=useState(window.__view);const[show,setShow]=useState(true);window.__set=setJob;window.__show=setShow;return show?<JobResumeControl job={job} onChanged={()=>{window.__changed++;setJob(structuredClone(window.__view))}}/>:null}createRoot(document.getElementById('root')).render(<App/>);`,
    },
    bundle: true,
    write: false,
    outdir: 'offline',
    platform: 'browser',
    format: 'iife',
    plugins: [
      {
        name: 'fake-api',
        setup(p) {
          p.onResolve({ filter: /^\.\/api$/ }, () => ({ path: 'api', namespace: 'fake' }));
          p.onLoad({ filter: /.*/, namespace: 'fake' }, () => ({
            loader: 'js',
            contents: `export async function request(path,init){window.__calls.push({path,method:init?.method||'GET',body:init?.body});if(!init){if(window.__mode==='defer-get')return new Promise(r=>window.__resolve=()=>r(structuredClone(window.__view)));return structuredClone(window.__view)}if(window.__mode==='lost')throw Error('lost');if(window.__mode==='defer-post')return new Promise(r=>window.__resolve=r);return {};}`,
          }));
        },
      },
    ],
  });
  const context = await browser.newContext({
    offline: true,
    viewport: { width: 390, height: 844 },
  });
  await context.route('**/*', (r) => r.abort());
  const page = await context.newPage();
  await page.route('https://resume.test/', (r) =>
    r.fulfill({
      contentType: 'text/html',
      body: '<html lang="ko"><body><div id="root"></div></body></html>',
    }),
  );
  await page.goto('https://resume.test/');
  await page.addStyleTag({ content: bundle.outputFiles.find((f) => f.path.endsWith('.css')).text });
  page.__resumeBundle = bundle.outputFiles.find((f) => f.path.endsWith('.js')).text;
  await page.addScriptTag({ content: page.__resumeBundle });
  return page;
}
const runButton = (page) => page.getByRole('button', { name: '이어서 실행', exact: true });
const posts = (page) => page.evaluate(() => window.__calls.filter((c) => c.method === 'POST'));
test('mount is inert; explicit same-job resume has no billing notice and is one-shot while busy', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await setup(browser);
    await expect(runButton(page)).toBeEnabled();
    assert.deepEqual(await page.evaluate(() => window.__calls), []);
    await expect(page.getByText(/유료/)).toHaveCount(0);
    await page.evaluate(() => (window.__mode = 'defer-post'));
    await runButton(page).evaluate((el) => {
      el.click();
      el.click();
    });
    await expect(runButton(page)).toBeDisabled();
    await expect.poll(async () => (await posts(page)).length).toBe(1);
    assert.deepEqual(await posts(page), [
      { path: '/renewal/jobs/job/run', method: 'POST', body: '{}' },
    ]);
    await page.evaluate(() => window.__resolve({}));
    await expect.poll(() => page.evaluate(() => window.__changed)).toBe(1);
    await expect(runButton(page)).toBeDisabled();
    await page.getByRole('button', { name: '실행 상태 확인', exact: true }).click();
    assert.equal((await posts(page)).length, 1);
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      true,
    );
  } finally {
    await browser.close();
  }
});
test('lost response stays disabled through GET-only check and component remount', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await setup(browser);
    await page.evaluate(() => (window.__mode = 'lost'));
    await runButton(page).click();
    await expect(page.getByRole('status')).toContainText('중복 실행');
    await expect(runButton(page)).toBeDisabled();
    await page.getByRole('button', { name: '실행 상태 확인', exact: true }).click();
    await expect(page.getByRole('status')).toContainText('다시 보내지 않았습니다');
    await page.evaluate(() => window.__show(false));
    await expect(runButton(page)).toHaveCount(0);
    await page.evaluate(() => window.__show(true));
    await expect(runButton(page)).toBeDisabled();
    assert.equal((await posts(page)).length, 1);
    await page.reload();
    await page.addScriptTag({ content: page.__resumeBundle });
    await expect(runButton(page)).toBeDisabled();
    await page.getByRole('button', { name: '실행 상태 확인', exact: true }).click();
    assert.deepEqual(await posts(page), []);
  } finally {
    await browser.close();
  }
});
test('fresh cancelled/active/read-only/wrong-scope/stale receipt/revision blocks dispatch', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const patch of [
      { status: 'cancelled' },
      { access: { can_manage: false } },
      { id: 'other' },
      { revision: 4 },
      { runs: [{ id: 'run', status: 'running' }] },
      { runs: [{ id: 'run', status: 'completed', result: { unit_recovery: { id: 'other' } } }] },
    ]) {
      const page = await setup(browser);
      await page.evaluate((p) => (window.__view = { ...window.__view, ...p }), patch);
      await runButton(page).click();
      await expect.poll(() => page.evaluate(() => window.__changed)).toBe(1);
      assert.deepEqual(await posts(page), []);
      await page.context().close();
    }
  } finally {
    await browser.close();
  }
});
test('changing job during pending GET fences old dispatch and old callback', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await setup(browser);
    await page.evaluate(() => (window.__mode = 'defer-get'));
    await runButton(page).click();
    await expect.poll(() => page.evaluate(() => typeof window.__resolve)).toBe('function');
    await page.evaluate(() => window.__set({ ...window.__view, id: 'next-job' }));
    await expect(runButton(page)).toBeEnabled();
    await page.evaluate(() => window.__resolve());
    await page.waitForTimeout(50);
    assert.deepEqual(await posts(page), []);
    assert.equal(await page.evaluate(() => window.__changed), 0);
  } finally {
    await browser.close();
  }
});
test('unavailable session storage fails closed before POST', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await setup(browser);
    await page.evaluate(() =>
      Object.defineProperty(window, 'sessionStorage', {
        get() {
          throw Error('storage blocked');
        },
      }),
    );
    await runButton(page).click();
    await expect(page.getByRole('status')).toContainText('실행 요청을 보내지 않았습니다');
    assert.deepEqual(await posts(page), []);
  } finally {
    await browser.close();
  }
});
test('ineligible snapshots expose no resume action', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const patch of [
      { access: { can_manage: false } },
      { status: 'completed' },
      { status: 'cancelling' },
      { cancel_requested: true },
      { runs: [{ id: 'run', status: 'failed' }] },
      { runs: [{ id: 'run', status: 'completed', result: null }] },
    ]) {
      const page = await setup(browser, patch);
      await expect(runButton(page)).toHaveCount(0);
      assert.deepEqual(await page.evaluate(() => window.__calls), []);
      await page.context().close();
    }
  } finally {
    await browser.close();
  }
});
