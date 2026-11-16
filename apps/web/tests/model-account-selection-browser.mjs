// Source-only, offline: no dist writes, provider traffic, or real registration.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

const connections = ['gemini', 'vertex_ai', 'gemini'].map((provider, i) => ({
  id: String(i + 1).repeat(32),
  name: '같은 계정 이름',
  provider,
  revision: 1,
  current_revision: 1,
  credential: 'reference_set',
  active: true,
  address_mode: 'official',
}));
const models = connections.map((connection, i) => ({
  id: String(i + 3).repeat(32),
  revision: 2,
  current_revision: 2,
  active: true,
  versions: Object.fromEntries(
    [1, 2].map((revision) => [
      revision,
      {
        revision,
        name: 'Gemini 동일 이름',
        model: 'gemini-3.8',
        provider: connection.provider,
        connection_id: connection.id,
        connection_revision: 1,
        model_types: ['text'],
        input_modalities: ['text'],
        output_modalities: ['text'],
        capabilities: ['text_generation'],
        translation_supported: true,
      },
    ]),
  ),
}));
const item = {
  id: 'gemini-3.8',
  label: 'Gemini 3.8',
  runtime_uses: ['translation'],
  profile: {
    model_types: ['text'],
    input_modalities: ['text'],
    output_modalities: ['text'],
    capabilities: ['text_generation'],
  },
  registration_token: 'fake-token',
  evidence: [],
  reason: 'fake catalog',
};

test('account controls preserve pins, fence stale catalogs and fit mobile (OFFLINE)', async () => {
  const bundle = await build({
    stdin: {
      resolveDir: process.cwd(),
      loader: 'tsx',
      contents: `
    import React,{useState} from 'react';import{createRoot}from'react-dom/client';
    import{NodeModelBinding}from'./src/NodeModelBinding';import{ModelCatalogPicker}from'./src/ModelCatalogPicker';
    import{ModelRegistryPage}from'./src/ModelRegistryPage';import{PageTitleProvider}from'./src/PageTitle';
    const connections=${JSON.stringify(connections)};
    window.picks=[];window.changes=[];
    function App(){const [account,setAccount]=useState(0);const[value,setValue]=useState({model_id:'${models[0].id}',revision:1});
      return new URLSearchParams(location.search).has('registry') ? <PageTitleProvider><ModelRegistryPage form/></PageTitleProvider> : <>
      <NodeModelBinding type="translate" value={value} changed={v=>{window.changes.push(v);setValue(v)}} fallbacks={[{model_id:'${models[1].id}',revision:1}]} fallbackChanged={v=>window.fallbacks=v}/>
      <button onClick={()=>setAccount(1)}>Switch catalog account</button>
      <ModelCatalogPicker connection={connections[account]} revision={1} model="" onQueryStart={()=>{}} onPick={(item,binding)=>window.picks.push({item,binding})}/></>;
    }createRoot(document.getElementById('root')).render(<App/>);`,
    },
    bundle: true,
    write: false,
    format: 'iife',
    define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
    loader: { '.css': 'empty' },
  });
  const browser = await chromium.launch({ headless: true });
  const unexpected = [],
    writes = [];
  let pending;
  let emptyLists = false;
  try {
    const context = await browser.newContext({
      offline: true,
      viewport: { width: 375, height: 850 },
    });
    await context.route('**/*', async (route) => {
      const req = route.request(),
        url = new URL(req.url());
      if (url.origin !== 'https://model-ui.invalid') {
        unexpected.push(url.href);
        return route.abort();
      }
      if (url.pathname === '/') {
        return route.fulfill({
          contentType: 'text/html',
          body: '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div>',
        });
      }
      if (url.pathname === '/api/settings/registered-models') {
        return route.fulfill({
          json: {
            models: emptyLists ? [] : models,
            providers: { gemini: 'Gemini', vertex_ai: 'Vertex AI' },
          },
        });
      }
      if (url.pathname === '/api/settings/serving-connections') {
        return route.fulfill({ json: { connections: emptyLists ? [] : connections } });
      }
      if (url.pathname.endsWith('/model-catalog')) {
        const id = url.pathname.split('/').at(-2);
        const respond = () =>
          route.fulfill({
            json: {
              connection_id: id,
              connection_revision: 1,
              complete: true,
              models: [item],
              inference_verified: false,
            },
          });
        if (id === connections[0].id) {
          pending = respond;
          return;
        }
        return respond();
      }
      writes.push([req.method(), url.pathname]);
      return route.abort();
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto('https://model-ui.invalid/');
    await page.addScriptTag({ content: bundle.outputFiles[0].text });
    await page.addStyleTag({ content: await readFile('src/model-selection.css', 'utf8') });
    const accounts = page.getByLabel('공급자 / 계정', { exact: true });
    await expect(accounts).toBeEnabled();
    await expect(accounts.locator('option')).toHaveCount(4);
    const labels = await accounts.locator('option').allTextContents();
    assert.equal(new Set(labels).size, labels.length);
    assert.match(await accounts.textContent(), /Google AI Studio/);
    assert.match(await accounts.textContent(), /Vertex AI/);
    const model = page.getByLabel('호환 등록 모델');
    await expect(model).toHaveValue(models[0].id + '@1');
    await accounts.selectOption(JSON.stringify(['vertex_ai', connections[1].id]));
    await expect(model).toHaveValue(models[0].id + '@1');
    assert.deepEqual(await page.evaluate(() => window.changes), []);
    await model.selectOption(models[1].id + '@2');
    assert.deepEqual(await page.evaluate(() => window.changes), [
      { model_id: models[1].id, revision: 2 },
    ]);
    await page.getByText('대체 모델 (선택)', { exact: true }).click();
    await expect(page.getByLabel('폴백 1 모델', { exact: true })).toHaveValue(models[1].id + '@1');
    await page.getByRole('button', { name: '공식 모델 목록 조회', exact: true }).click();
    await expect.poll(() => !!pending).toBe(true);
    await page.getByRole('button', { name: 'Switch catalog account' }).click();
    await pending().catch(() => {});
    await expect(page.getByLabel('공식 모델', { exact: true })).toBeDisabled();
    assert.deepEqual(await page.evaluate(() => window.picks), []);
    await page.getByRole('button', { name: '공식 모델 목록 조회', exact: true }).click();
    await expect(page.getByLabel('공식 모델', { exact: true })).toBeEnabled();
    await page.getByLabel('공식 모델', { exact: true }).selectOption(item.id);
    assert.equal(
      (await page.evaluate(() => window.picks))[0].binding.connection_id,
      connections[1].id,
    );
    assert.equal(await page.evaluate(() => innerWidth), 375);
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      true,
    );
    await page.goto('https://model-ui.invalid/?registry');
    await page.addScriptTag({ content: bundle.outputFiles[0].text });
    await page.addStyleTag({ content: await readFile('src/model-selection.css', 'utf8') });
    await expect(page.getByLabel('공급자 / 계정', { exact: true })).toBeEnabled();
    await expect(page.getByRole('button', { name: '저장', exact: true })).toBeDisabled();
    await page.getByLabel('공급자 / 계정', { exact: true }).selectOption(connections[1].id);
    await page.getByRole('button', { name: '공식 모델 목록 조회', exact: true }).click();
    await page.getByLabel('공식 모델', { exact: true }).selectOption(item.id);
    await expect(page.getByRole('button', { name: '저장', exact: true })).toBeEnabled();
    await page.getByLabel('공급자 / 계정', { exact: true }).selectOption(connections[0].id);
    await expect(page.getByRole('button', { name: '저장', exact: true })).toBeDisabled();
    await expect(page.getByLabel('공식 모델', { exact: true })).toHaveValue('');
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      true,
    );
    emptyLists = true;
    await page.goto('https://model-ui.invalid/?registry');
    await page.addScriptTag({ content: bundle.outputFiles[0].text });
    await expect(page.getByLabel('공급자 / 계정', { exact: true })).toBeEnabled();
    await expect(page.getByLabel('공급자 / 계정', { exact: true }).locator('option')).toHaveCount(
      1,
    );
    await expect(page.getByRole('button', { name: '저장', exact: true })).toBeDisabled();
    await expect(page.getByText('공급자 / 계정을 먼저 선택하세요.', { exact: true })).toBeVisible();
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(writes, []);
  } finally {
    await browser.close();
  }
});
