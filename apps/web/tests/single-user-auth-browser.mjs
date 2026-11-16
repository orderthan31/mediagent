import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

// Real AuthGate and API/CSRF client; every HTTP response is an offline fixture.
test('single-user entry preserves actor and CSRF, hides and fences logout; normal login remains available', async () => {
  const bundle = await build({
    stdin: {
      resolveDir: process.cwd(),
      loader: 'tsx',
      contents: `import React from 'react';import{createRoot}from'react-dom/client';import{AuthGate,AccountMenu,useWorkspaceAuth}from'./src/AuthGate';import{request}from'./src/api';function Probe(){const auth=useWorkspaceAuth();window.forceLogout=()=>auth.logout();return <><AccountMenu/><h1>Workspace fixture</h1><button onClick={()=>request('/offline-write',{method:'POST',body:'{}',headers:{'Content-Type':'application/json'}})}>Probe CSRF</button></>;}createRoot(document.getElementById('root')).render(<AuthGate><Probe/></AuthGate>);`,
    },
    bundle: true,
    write: false,
    platform: 'browser',
    format: 'iife',
    define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
    loader: { '.css': 'empty' },
  });
  const browser = await chromium.launch({ headless: true });
  try {
    for (const enabled of [false, true]) {
      const context = await browser.newContext({ offline: true });
      const requests = [];
      await context.route('**/*', async (route) => {
        const req = route.request(),
          url = new URL(req.url());
        if (url.origin !== 'https://single-user.invalid') return route.abort();
        if (url.pathname === '/')
          return route.fulfill({
            contentType: 'text/html',
            body: '<html><body><div id="root"></div></body></html>',
          });
        requests.push({ path: url.pathname, method: req.method(), headers: req.headers() });
        if (url.pathname === '/api/auth/session')
          return route.fulfill({
            json: {
              enabled,
              setup_required: false,
              user: { id: 'a'.repeat(32), username: 'existing-owner', role: 'user' },
              csrf_token: 'offline-csrf',
            },
          });
        if (url.pathname === '/api/offline-write' || url.pathname === '/api/auth/logout')
          return route.fulfill({ json: {} });
        return route.abort();
      });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.goto('https://single-user.invalid/');
      await page.addScriptTag({ content: bundle.outputFiles[0].text });
      await expect(page.getByRole('heading', { name: 'Workspace fixture' })).toBeVisible();
      await expect(page.getByText('existing-owner', { exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toHaveCount(
        enabled ? 1 : 0,
      );
      await page.getByRole('button', { name: 'Probe CSRF' }).click();
      await expect
        .poll(() => requests.filter((r) => r.path === '/api/offline-write').length)
        .toBe(1);
      assert.equal(
        requests.find((r) => r.path === '/api/offline-write').headers['x-csrf-token'],
        'offline-csrf',
      );
      await page.evaluate(() => window.forceLogout());
      if (enabled) {
        await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeVisible();
        assert.equal(requests.filter((r) => r.path === '/api/auth/logout').length, 1);
      } else {
        await expect(page.getByRole('heading', { name: 'Workspace fixture' })).toBeVisible();
        assert.equal(requests.filter((r) => r.path === '/api/auth/logout').length, 0);
      }
      assert.deepEqual(errors, []);
      await context.close();
    }
  } finally {
    await browser.close();
  }
});
