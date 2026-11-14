// Offline behavioral gate: real components, helper, api and auth-session; no service.
import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

const id = '11111111111111111111111111111111';
const base = '/renewal/jobs/' + id;
const definition = {
  id: 'flow',
  name: 'Offline flow',
  catalog_version: 2,
  revision: 7,
  inputs: {},
  nodes: [],
  edges: [],
};
const job = {
  id,
  ticket_number: 42,
  revision: 9,
  status: 'draft',
  parent_id: null,
  access: { can_manage: true },
  snapshot: { asset: { asset_id: 'asset', original_filename: 'offline.mp4' }, definition },
  runs: [],
  reviews: [],
};
const bundle = await build({
  stdin: {
    resolveDir: process.cwd(),
    loader: 'tsx',
    contents: `
    import React,{useState,useEffect} from 'react';import {createRoot} from 'react-dom/client';
    import {WorkflowStart} from './src/WorkflowStart';import {RenewalJobDetail} from './src/RenewalJobDetail';
    import {setCsrfToken} from './src/auth-session';setCsrfToken('offline-csrf');
    function App(){const [route,setRoute]=useState(location.hash);useEffect(()=>{const change=()=>setRoute(location.hash);addEventListener('hashchange',change);return()=>removeEventListener('hashchange',change)},[]);return route.startsWith('#/jobs/')?<RenewalJobDetail key={route} id={route.slice(7)}/>:<WorkflowStart/>}
    createRoot(document.getElementById('root')).render(<App/>);`,
  },
  bundle: true,
  write: false,
  platform: 'browser',
  format: 'iife',
  loader: { '.css': 'empty' },
  define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
});

const fixture = async (
  browser,
  { fail = '', direct = false, canManage = true, notReady = false, admitCommitted = false } = {},
) => {
  const context = await browser.newContext({ offline: true });
  const calls = [],
    errors = [],
    gates = new Map();
  let started = false,
    admitted = false,
    detailHeld = !direct;
  const current = () => ({
    ...job,
    access: { can_manage: canManage },
    status: started ? 'running' : admitted ? 'waiting' : 'draft',
  });
  await context.route('**/*', async (route) => {
    const req = route.request(),
      url = new URL(req.url());
    if (url.origin === 'https://handoff.invalid' && url.pathname === '/') {
      return route.fulfill({ contentType: 'text/html', body: '<div id="root"></div>' });
    }
    const path = url.pathname.replace(/^\/api/, '');
    const body = req.postDataJSON();
    calls.push({ path, method: req.method(), body, headers: req.headers() });
    const reply = (value, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) });
    if (path === '/videos') {
      return reply({ videos: [{ asset_id: 'asset', original_filename: 'offline.mp4' }] });
    }
    if (path === '/work-entry/workflows') {
      return reply({ definitions: [definition] });
    }
    if (path === '/work-entry/catalog') {
      return reply({ nodes: [] });
    }
    if (path === '/work-entry/workflows/flow') {
      return reply(definition);
    }
    if (path === '/work-entry/inspect') {
      return reply({
        supported: true,
        model_ready: true,
        definition_revision: 7,
        summary: [],
        reasons: [],
      });
    }
    if (path === '/work-entry/preview') {
      return reply({ token: 'immutable-preview', paid_roles: ['translate'], notice: '' });
    }
    if (path === '/work-entry/create') {
      gates.set('create', () =>
        reply(
          fail === 'create' ? { detail: 'offline create failure' } : { id },
          fail === 'create' ? 502 : 200,
        ),
      );
      return;
    }
    if (path === base) {
      // First GET is the explicit helper guard; subsequent GET is detail loading.
      if (detailHeld && calls.filter((c) => c.path === base).length > 1) {
        gates.set('detail', () => {
          detailHeld = false;
          return reply(current());
        });
        return;
      }
      return reply(current());
    }
    const stage = path.startsWith(base + '/') ? path.slice(base.length + 1) : '';
    if (['prepare-start', 'plan', 'confirm', 'admit', 'run'].includes(stage)) {
      gates.set(stage, () => {
        if (stage === 'admit' && admitCommitted) {
          admitted = true;
        }
        if (stage === fail) {
          return reply({ detail: `offline ${stage} failure` }, 502);
        }
        if (stage === 'run') {
          started = true;
        }
        return reply(
          stage === 'plan'
            ? {
                ready: !notReady,
                token: 'exact-plan-token',
                reasons: notReady ? ['offline plan requires attention'] : [],
              }
            : stage === 'confirm'
              ? { id: 'exact-consent' }
              : {},
        );
      });
      return;
    }
    errors.push('unexpected request ' + req.method() + ' ' + req.url());
    await route.abort();
  });
  const page = await context.newPage();
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(
    'https://handoff.invalid/' + (direct ? '#/jobs/' + id : '#/start?target=asset&workflow=flow'),
  );
  await page.addScriptTag({ content: bundle.outputFiles[0].text });
  const release = async (stage) => {
    await expect.poll(() => gates.has(stage)).toBe(true);
    const fn = gates.get(stage);
    gates.delete(stage);
    await fn();
  };
  const begin = async () => {
    const button = page.getByRole('button', { name: '작업 시작', exact: true });
    await expect(button).toBeEnabled();
    // Two events in one React batch exercise the synchronous fence, not just disabled DOM.
    await button.evaluate((el) => {
      el.click();
      el.click();
    });
    await release('create');
  };
  return { page, calls, errors, release, begin, context };
};

test('create routes immediately; one explicit handoff continues through every delayed stage', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const f = await fixture(browser);
    await f.begin();
    await expect(f.page.locator('.job-detail')).toBeVisible({ timeout: 1500 });
    await expect(f.page.getByRole('status').filter({ hasText: '시작 준비' })).toBeVisible();
    assert.equal(f.calls.filter((c) => c.path === '/work-entry/create').length, 1);
    await f.release('detail');
    for (const stage of ['prepare-start', 'plan', 'confirm', 'admit', 'run']) {
      await expect(f.page.locator('[data-start-stage="' + stage + '"]')).toBeVisible();
      await expect(f.page.getByRole('button', { name: '작업 시작', exact: true })).toBeDisabled();
      await f.release(stage);
    }
    await expect(f.page.locator('.job-detail-toolbar')).toContainText('처리 중');
    const mutations = f.calls.filter(
      (c) =>
        c.method === 'POST' && !['/work-entry/inspect', '/work-entry/preview'].includes(c.path),
    );
    assert.deepEqual(
      mutations.map((c) => c.path),
      [
        '/work-entry/create',
        base + '/prepare-start',
        base + '/confirm',
        base + '/admit',
        base + '/run',
      ],
    );
    const nonce = mutations[0].body.request_id;
    assert.equal(mutations[0].body.token, 'immutable-preview');
    assert.equal(mutations[0].body.paid_confirmed, true);
    assert.deepEqual(
      mutations.slice(1).map((c) => c.body),
      [
        { revision: 9, request_id: nonce + '-prepare' },
        { token: 'exact-plan-token', request_id: nonce + '-confirm' },
        { consent_id: 'exact-consent', request_id: nonce + '-admit' },
        {},
      ],
    );
    assert.ok(mutations.every((c) => c.headers['x-csrf-token'] === 'offline-csrf'));
    assert.deepEqual(f.errors, []);
    await f.context.close();
  } finally {
    await browser.close();
  }
});

for (const fail of ['create', 'prepare-start', 'plan', 'confirm', 'admit', 'run']) {
  test('visible failure without automatic retry: ' + fail, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
      const f = await fixture(browser, { fail });
      await f.begin();
      if (fail !== 'create') {
        await expect(f.page.locator('.job-detail')).toBeVisible({ timeout: 1500 });
        await f.release('detail');
        for (const stage of ['prepare-start', 'plan', 'confirm', 'admit', 'run']) {
          await f.release(stage);
          if (stage === fail) {
            break;
          }
        }
      }
      await expect(
        f.page.getByRole('alert').filter({ hasText: 'offline ' + fail + ' failure' }),
      ).toBeVisible();
      const before = f.calls.filter((c) => c.method === 'POST' || c.path.endsWith('/plan')).length;
      await f.page.waitForTimeout(600);
      assert.equal(
        f.calls.filter((c) => c.method === 'POST' || c.path.endsWith('/plan')).length,
        before,
      );
      assert.deepEqual(f.errors, []);
      await f.context.close();
    } finally {
      await browser.close();
    }
  });
}

test('not-ready plan remains visible in detail and never becomes implicit consent or retry', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const f = await fixture(browser, { notReady: true });
    await f.begin();
    await expect(f.page.locator('.job-detail')).toBeVisible();
    await f.release('detail');
    await f.release('prepare-start');
    await f.release('plan');
    await expect(f.page.getByRole('alert')).toContainText('offline plan requires attention');
    await f.page.waitForTimeout(600);
    assert.deepEqual(
      f.calls.filter((c) => c.method === 'POST' && c.path.startsWith(base)).map((c) => c.path),
      [base + '/prepare-start'],
    );
    assert.equal(f.calls.filter((c) => c.path === base + '/plan').length, 1);
    assert.deepEqual(f.errors, []);
    await f.context.close();
  } finally {
    await browser.close();
  }
});

test('unclear admit response reconciles committed waiting status without another start or run', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const f = await fixture(browser, { fail: 'admit', admitCommitted: true });
    await f.begin();
    await expect(f.page.locator('.job-detail')).toBeVisible();
    await f.release('detail');
    for (const stage of ['prepare-start', 'plan', 'confirm', 'admit']) {
      await f.release(stage);
    }
    await expect(f.page.getByRole('alert')).toContainText('offline admit failure');
    await expect(f.page.locator('.job-detail-toolbar')).toContainText('대기');
    await expect(f.page.getByRole('button', { name: '작업 시작', exact: true })).toHaveCount(0);
    await f.page.waitForTimeout(600);
    assert.equal(f.calls.filter((c) => c.path === base + '/admit').length, 1);
    assert.equal(f.calls.filter((c) => c.path === base + '/run').length, 0);
    assert.equal(f.calls.filter((c) => c.path === '/work-entry/create').length, 1);
    assert.deepEqual(f.errors, []);
    await f.context.close();
  } finally {
    await browser.close();
  }
});

test('direct/reloaded detail never starts; explicit double click starts once; read-only has no Start', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const f = await fixture(browser, { direct: true });
    const button = f.page.getByRole('button', { name: '작업 시작', exact: true });
    await expect(button).toBeEnabled();
    await f.page.reload();
    await f.page.addScriptTag({ content: bundle.outputFiles[0].text });
    await expect(button).toBeEnabled();
    assert.equal(f.calls.filter((c) => c.method === 'POST').length, 0);
    await button.evaluate((el) => {
      el.click();
      el.click();
    });
    for (const stage of ['prepare-start', 'plan', 'confirm', 'admit', 'run']) {
      await f.release(stage);
    }
    await expect(f.page.locator('.job-detail-toolbar')).toContainText('처리 중');
    assert.equal(f.calls.filter((c) => c.path === base + '/prepare-start').length, 1);
    assert.deepEqual(f.errors, []);
    await f.context.close();
    const reader = await fixture(browser, { direct: true, canManage: false });
    await expect(reader.page.locator('.job-detail-toolbar')).toBeVisible();
    await expect(reader.page.getByRole('button', { name: '작업 시작', exact: true })).toHaveCount(
      0,
    );
    assert.equal(reader.calls.filter((c) => c.method === 'POST').length, 0);
    assert.deepEqual(reader.errors, []);
    await reader.context.close();
  } finally {
    await browser.close();
  }
});
