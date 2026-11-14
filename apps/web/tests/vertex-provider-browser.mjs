// Real production component, entirely offline; no provider/auth/inference calls.
import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';
const A = 'a'.repeat(32),
  B = 'b'.repeat(32);
const fixture = JSON.stringify({
  type: 'service_account',
  project_id: 'fixture-project',
  client_email: 'synthetic@fixture-project.iam.gserviceaccount.com',
  private_key: '-----BEGIN PRIVATE KEY-----\n' + 'x'.repeat(2900) + '\n-----END PRIVATE KEY-----\n',
  token_uri: 'https://oauth2.googleapis.com/token',
});
const bundle = await build({
  stdin: {
    resolveDir: process.cwd(),
    loader: 'tsx',
    contents: `import React,{useState} from 'react';import{createRoot}from'react-dom/client';import{PageTitleProvider}from'./src/PageTitle';import{ProviderConnections}from'./src/ProviderConnections';import{AuthGate}from'./src/AuthGate';function App(){const[visible,toggle]=useState(true);window.toggle=toggle;const[r,s]=useState('#/serving/connections/${A}/edit');window.route=s;return <AuthGate><PageTitleProvider>{visible && <ProviderConnections route={r} query="" onSaved={()=>{}}/>}</PageTitleProvider></AuthGate>}createRoot(document.getElementById('root')).render(<App/>);`,
  },
  bundle: true,
  write: false,
  format: 'iife',
  platform: 'browser',
  define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
  loader: { '.css': 'empty' },
});
const harness = async (run, failCredential = false, authenticated = true) => {
  const browser = await chromium.launch({ headless: true });
  const writes = [],
    unexpected = [],
    errors = [];
  const rows = [A, B].map((id) => ({
    id,
    name: id === A ? 'Vertex A' : 'Vertex B',
    provider: 'vertex_ai',
    protocol: 'vertex_ai',
    endpoint: 'https://aiplatform.googleapis.com/v1/projects/fixture-project/locations/global',
    vertex_project: 'fixture-project',
    vertex_location: 'global',
    revision: 3,
    credential: 'reference_set',
  }));
  try {
    const context = await browser.newContext({ offline: true });
    await context.route('**/*', (route) => {
      const req = route.request(),
        u = new URL(req.url());
      if (u.origin === 'https://vertex.invalid') {
        if (u.pathname === '/api/auth/session' && req.method() === 'GET') {
          return route.fulfill({
            json: {
              enabled: true,
              user: authenticated
                ? { id: 'offline-admin', username: 'offline-admin', role: 'admin' }
                : null,
              csrf_token: authenticated ? 'offline-csrf' : undefined,
            },
          });
        }
        if (u.pathname === '/' && req.method() === 'GET') {
          return route.fulfill({ contentType: 'text/html', body: '<div id="root"></div>' });
        }
        if (u.pathname === '/api/settings/serving-connections' && req.method() === 'GET') {
          return route.fulfill({
            json: {
              connections: rows,
              providers: {
                openai: 'OpenAI',
                gemini: 'Gemini',
                anthropic: 'Anthropic',
                xai: 'xAI',
                openai_compatible: 'Custom',
                vertex_ai: 'Google Vertex AI',
              },
            },
          });
        }
        if (
          /^\/api\/settings\/serving-connections\/[a-f0-9]{32}(\/credential)?$/.test(u.pathname) &&
          req.method() === 'PUT'
        ) {
          assert.equal(req.headers()['x-csrf-token'], 'offline-csrf');
          const body = req.postDataJSON();
          writes.push({ path: u.pathname, body });
          if (u.pathname.endsWith('/credential') && failCredential) {
            return route.fulfill({ status: 400, json: { detail: 'Invalid credential' } });
          }
          const id = u.pathname.split('/')[4];
          return route.fulfill({ json: { ...rows[0], ...body, id, revision: body.revision + 1 } });
        }
      }
      unexpected.push(req.method() + ' ' + u.href);
      return route.abort();
    });
    const page = await context.newPage();
    page.setDefaultTimeout(5000);
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto('https://vertex.invalid');
    await page.addScriptTag({ content: bundle.outputFiles[0].text });
    if (authenticated) {
      await expect(page.getByRole('button', { name: '저장', exact: true })).toBeEnabled();
    } else {
      await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeVisible();
    }
    await run(page, writes);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
};
const upload = (page, text = fixture) =>
  page.getByLabel('서비스 계정 JSON 파일').setInputFiles({
    name: 'misclassified.data',
    mimeType: 'application/octet-stream',
    buffer: Buffer.from(text),
  });
test('unauthenticated production AuthGate mounts no credential editor and makes no writes', () =>
  harness(
    async (page, writes) => {
      await expect(page.getByLabel('서비스 계정 JSON 파일')).toHaveCount(0);
      await expect(page.getByRole('button', { name: '저장', exact: true })).toHaveCount(0);
      assert.deepEqual(writes, []);
    },
    false,
    false,
  ));
test('pending read unmount and remount cannot restore selected JSON', () =>
  harness(async (page, writes) => {
    await page.evaluate(() => {
      const original = File.prototype.text;
      File.prototype.text = function () {
        return new Promise((resolve) => {
          window.release = async () => resolve(await original.call(this));
        });
      };
    });
    await upload(page);
    await page.evaluate(() => window.toggle(false));
    await expect(page.getByLabel('서비스 계정 JSON 파일')).toHaveCount(0);
    await page.evaluate(() => window.toggle(true));
    await expect(page.getByRole('button', { name: '저장', exact: true })).toBeEnabled();
    await page.evaluate(() => window.release());
    await page.getByRole('button', { name: '저장', exact: true }).click();
    await expect.poll(() => writes.length).toBe(1);
    assert.equal(writes[0].body.secret, undefined);
  }));
test('Vertex fields, generic MIME, offline JSON save and revision order', () =>
  harness(async (page, writes) => {
    await expect(page.getByLabel('프로젝트 ID', { exact: true })).toHaveValue('fixture-project');
    await expect(page.getByLabel('리전', { exact: true })).toHaveValue('global');
    assert.equal(await page.getByLabel('서비스 계정 JSON 파일').getAttribute('accept'), null);
    await page.getByLabel('리전', { exact: true }).fill('us-central1');
    await upload(page);
    await expect(page.getByRole('button', { name: '저장', exact: true })).toBeEnabled();
    await page.evaluate(() => {
      document.querySelector('form').requestSubmit();
      document.querySelector('form').requestSubmit();
    });
    await expect.poll(() => writes.length).toBe(2);
    assert.equal(writes[0].body.vertex_location, 'us-central1');
    assert.equal(writes[0].body.endpoint, undefined);
    assert.equal(writes[1].body.revision, 4);
    assert.equal(writes[1].body.secret, fixture);
    assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0);
  }));
test('invalid/oversize JSON is sanitized; unchanged credentials omitted', () =>
  harness(async (page, writes) => {
    for (const text of ['secret-sentinel-invalid', 'x'.repeat(32769)]) {
      await upload(page, text);
      await expect(page.getByRole('alert')).toContainText('JSON');
      await expect(page.getByRole('alert')).not.toContainText('secret-sentinel');
    }
    await page.getByRole('button', { name: '저장', exact: true }).click();
    await expect.poll(() => writes.length).toBe(1);
    assert.equal(writes[0].body.secret, undefined);
  }));
test('pending read disables save/clear; A-B-A cannot restore abandoned credential', () =>
  harness(async (page, writes) => {
    await page.evaluate(() => {
      const original = File.prototype.text;
      window.release = [];
      File.prototype.text = function () {
        return new Promise((resolve) =>
          window.release.push(async () => resolve(await original.call(this))),
        );
      };
    });
    await upload(page);
    await expect(page.getByRole('button', { name: '저장', exact: true })).toBeDisabled();
    await expect(page.getByRole('button', { name: '선택 지우기' })).toBeDisabled();
    await page.evaluate((b) => window.route('#/serving/connections/' + b + '/edit'), B);
    await expect(page.getByLabel('프로젝트 ID', { exact: true })).toBeVisible();
    await page.evaluate((a) => window.route('#/serving/connections/' + a + '/edit'), A);
    await expect(page.getByRole('button', { name: '저장', exact: true })).toBeEnabled();
    await page.evaluate(() => window.release[0]());
    await page.getByRole('button', { name: '저장', exact: true }).click();
    await expect.poll(() => writes.length).toBe(1);
    assert.equal(writes[0].body.secret, undefined);
  }));
test('same-owner file supersession and provider switch discard stale JSON', () =>
  harness(async (page, writes) => {
    await page.evaluate(() => {
      const original = File.prototype.text;
      window.release = [];
      File.prototype.text = function () {
        return new Promise((resolve) =>
          window.release.push(async () => resolve(await original.call(this))),
        );
      };
    });
    await upload(page);
    const replacement = fixture.replace('fixture-project', 'replacement-project');
    await upload(page, replacement);
    await page.evaluate(() => window.release[0]());
    await expect(page.getByRole('button', { name: '저장', exact: true })).toBeDisabled();
    await page.evaluate(() => window.release[1]());
    await expect(page.getByRole('button', { name: '저장', exact: true })).toBeEnabled();
    await page.getByRole('button', { name: '저장', exact: true }).click();
    await expect.poll(() => writes.length).toBe(2);
    assert.equal(writes[1].body.secret, replacement);
    await expect(page.getByRole('button', { name: '저장', exact: true })).toBeEnabled();
    await upload(page);
    await page.locator('select').first().selectOption('openai');
    await page.evaluate(() => window.release[2]());
    const key = page.getByLabel('API 키', { exact: true });
    await expect(key).toHaveValue('');
    assert.equal(await key.getAttribute('type'), 'password');
    assert.equal(await key.getAttribute('maxlength'), '4096');
    await page.getByRole('button', { name: '저장', exact: true }).click();
    await expect.poll(() => writes.length).toBe(3);
    assert.equal(writes[2].body.secret, undefined);
  }));
test('parsed UTF-8 limit and explicit credential removal', () =>
  harness(async (page, writes) => {
    await page.evaluate(() => {
      File.prototype.text = async () =>
        JSON.stringify({
          type: 'service_account',
          project_id: 'p',
          client_email: 'e',
          private_key: '한'.repeat(12000),
          token_uri: 'https://oauth2.googleapis.com/token',
        });
    });
    await upload(page);
    await expect(page.getByRole('alert')).toContainText('32768');
    await page.getByRole('checkbox').check();
    await page.getByRole('button', { name: '저장', exact: true }).click();
    await expect.poll(() => writes.length).toBe(2);
    assert.equal(writes[1].body.secret, null);
    assert.equal(writes[1].body.revision, 4);
  }));
test('Vertex actions retain 44px touch targets without overriding ordinary providers', () =>
  harness(async (page, writes) => {
    const save = page.getByRole('button', { name: '저장', exact: true });
    for (const control of [save, page.getByRole('button', { name: '선택 지우기' })]) {
      await expect(control).toHaveCSS('min-height', '44px');
      assert.ok((await control.boundingBox()).height >= 44);
    }
    await page.locator('select').first().selectOption('openai');
    assert.equal(await save.evaluate((element) => element.style.minHeight), '');
    assert.equal(writes.length, 0);
  }));
test('credential failure preserves accepted metadata identity and fresh revision', () =>
  harness(async (page, writes) => {
    await page.evaluate(() => window.route('#/serving/connections/new'));
    await page.locator('select').first().selectOption('vertex_ai');
    await page.getByLabel('프로젝트 ID', { exact: true }).fill('fixture-project');
    await page.getByLabel('리전', { exact: true }).fill('global');
    await upload(page);
    await page.getByRole('button', { name: '저장', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('공급자 정보는 저장');
    assert.equal(writes.length, 2);
    await page.getByRole('button', { name: '선택 지우기' }).click();
    await page.getByRole('button', { name: '저장', exact: true }).click();
    await expect.poll(() => writes.length).toBe(3);
    assert.equal(writes[2].path, writes[0].path);
    assert.equal(writes[2].body.revision, 1);
  }, true));
