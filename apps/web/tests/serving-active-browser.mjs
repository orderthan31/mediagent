// SOURCE/OFFLINE: bundle current components before each run; no live API or paid calls.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

const id = (n) => n.toString(16).padStart(32, '0');
const connections = Array.from({ length: 24 }, (_, i) => ({
  id: id(i + 1),
  name:
    i === 0 ? 'Synthetic stopped provider' : i === 1 ? 'Legacy provider' : `Active provider ${i}`,
  provider: 'openai_compatible',
  endpoint: 'https://fixture.invalid/v1',
  revision: 3,
  current_revision: 3,
  credential: 'not_set',
  ...(i === 1 ? {} : { active: i !== 0 }),
}));
const models = connections.map((connection, i) => ({
  id: id(i + 100),
  revision: 2,
  current_revision: 2,
  state_revision: 1,
  active: i !== 0,
  versions: {
    2: {
      model_id: id(i + 100),
      revision: 2,
      name: i === 0 ? 'Synthetic stopped model' : `Active model ${i}`,
      provider: connection.provider,
      connection_id: connection.id,
      connection_revision: 1,
      model: 'literal-model',
      model_types: ['text'],
      input_modalities: ['text'],
      output_modalities: ['text'],
      capabilities: ['text_generation'],
    },
  },
}));
const bundle = await build({
  stdin: {
    resolveDir: process.cwd(),
    loader: 'tsx',
    contents: `import React,{useState} from 'react';import{createRoot}from'react-dom/client';import{PageTitleProvider}from'./src/PageTitle';import{ModelRegistryPage}from'./src/ModelRegistryPage';import{ProviderConnections}from'./src/ProviderConnections';const p=new URLSearchParams(location.search);function App(){const[q,setQ]=useState('');return <PageTitleProvider><input aria-label="Test search" value={q} onChange={e=>setQ(e.target.value)}/>{p.get('kind')==='provider'?<ProviderConnections route={p.get('route')||'#/serving/connections'} query={q}/>:<ModelRegistryPage identity={p.get('id')||undefined} form={p.get('form')==='1'} query={q}/>}</PageTitleProvider>}createRoot(document.getElementById('root')).render(<div className="video-workspace renewed-workspace ui02-workspace"><div className="video-main"><App/></div></div>);`,
  },
  bundle: true,
  write: false,
  format: 'iife',
  platform: 'browser',
  define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
  loader: { '.css': 'empty' },
});

const harness = async (run) => {
  const browser = await chromium.launch({ headless: true });
  const unexpected = [],
    errors = [];
  try {
    const context = await browser.newContext({ offline: true });
    await context.route('**/*', (route) => {
      const request = route.request(),
        url = new URL(request.url());
      if (url.origin === 'https://serving.invalid' && request.method() === 'GET') {
        if (url.pathname === '/') {
          return route.fulfill({
            contentType: 'text/html',
            body: '<html lang="ko"><div id="root"></div></html>',
          });
        }
        const assetPath = path.resolve('dist', url.pathname.slice(1));
        if (
          assetPath.startsWith(path.resolve('dist') + path.sep) &&
          fs.existsSync(assetPath) &&
          fs.statSync(assetPath).isFile()
        ) {
          return route.fulfill({ body: fs.readFileSync(assetPath) });
        }
        const providers = { openai_compatible: 'Custom provider' };
        if (url.pathname === '/api/settings/registered-models') {
          return route.fulfill({ json: { models, providers } });
        }
        if (url.pathname === '/api/settings/serving-connections') {
          return route.fulfill({ json: { connections, providers } });
        }
      }
      unexpected.push(request.method() + ' ' + url.href);
      return route.abort();
    });
    const page = await context.newPage();
    page.on('pageerror', (error) => errors.push(error.message));
    const mount = async (params) => {
      await page.goto('https://serving.invalid/?' + new URLSearchParams(params));
      await page.addScriptTag({ content: bundle.outputFiles[0].text });
      if (params.layout === '1') {
        const css = fs
          .readdirSync('dist/assets')
          .filter((name) => name.endsWith('.css'))
          .map((name) => fs.readFileSync(path.join('dist/assets', name), 'utf8'))
          .join('\n');
        await page.addStyleTag({
          content: css + '\n' + fs.readFileSync('src/serving-connections.css', 'utf8'),
        });
      }
    };
    await run(page, mount);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
};

for (const kind of ['model', 'provider']) {
  test(`${kind}: active default, reversible checkbox, query and pagination (OFFLINE)`, async () => {
    await harness(async (page, mount) => {
      await mount({ kind });
      const rows = page.locator(
        kind === 'model' ? '.serving-resource-row' : '.provider-resource-row',
      );
      const stopped = page.getByText(`Synthetic stopped ${kind}`, { exact: true });
      await expect(rows).toHaveCount(20);
      await expect(stopped).toHaveCount(0);
      await expect(
        page.getByText(kind === 'model' ? 'Active model 1' : 'Legacy provider', { exact: true }),
      ).toBeVisible();
      const toggle = page.getByRole('checkbox', { name: '사용 중지 포함', exact: true });
      await expect(toggle).not.toBeChecked();
      await page.getByRole('button', { name: '다음 페이지' }).click();
      await expect(page.getByLabel('페이지 선택')).toHaveValue('2');
      await toggle.check();
      await expect(page.getByLabel('페이지 선택')).toHaveValue('1');
      await expect(stopped).toBeVisible();
      await page.getByRole('button', { name: '다음 페이지' }).click();
      await toggle.uncheck();
      await expect(page.getByLabel('페이지 선택')).toHaveValue('1');
      await expect(stopped).toHaveCount(0);
      await page.getByLabel('Test search').fill(`sYnThEtIc StOpPeD ${kind}`);
      await expect(rows).toHaveCount(0);
      await toggle.check();
      await expect(rows).toHaveCount(1);
      await expect(stopped).toBeVisible();
      await toggle.uncheck();
      await expect(rows).toHaveCount(0);
      await page
        .getByLabel('Test search')
        .fill(kind === 'provider' ? 'CUSTOM PROVIDER' : 'ACTIVE MODEL');
      await expect(rows).toHaveCount(20);
      await page.getByRole('button', { name: '다음 페이지' }).click();
      await page
        .getByLabel('Test search')
        .fill(kind === 'provider' ? 'Legacy provider' : 'Active model 1');
      await expect(page.getByLabel('페이지 선택')).toHaveValue('1');
    });
  });
}

test('inactive direct detail/edit and pinned provider survive; new registration excludes it (OFFLINE)', async () => {
  await harness(async (page, mount) => {
    await mount({ kind: 'model', id: models[0].id });
    await expect(page.getByText('Synthetic stopped provider', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '사용 재개', exact: true })).toBeVisible();
    await expect(page.getByRole('checkbox', { name: '사용 중지 포함' })).toHaveCount(0);
    await page.getByRole('button', { name: '수정', exact: true }).click();
    assert.equal(new URL(page.url()).hash, `#/serving/${models[0].id}/edit`);
    await mount({ kind: 'model', id: models[0].id, form: '1' });
    const select = page.getByLabel('공급자 연결', { exact: true });
    await expect(select).toHaveValue(connections[0].id);
    await expect(select.locator('option:checked')).toHaveText('Synthetic stopped provider');
    await expect(
      page.getByText('공급자 연결 설정이 변경됐습니다. 저장된 연결은 유지됩니다.', {
        exact: false,
      }),
    ).toBeVisible();
    await expect(page.getByLabel('등록 model')).toHaveValue('literal-model');
    await select.selectOption(connections[2].id);
    await expect(select.locator(`option[value="${connections[0].id}"]`)).toHaveCount(1);
    await select.selectOption(connections[0].id);
    await mount({ kind: 'model', form: '1' });
    await expect(select.locator(`option[value="${connections[1].id}"]`)).toHaveText(
      'Legacy provider',
    );
    await expect(select.locator(`option[value="${connections[2].id}"]`)).toHaveText(
      'Active provider 2',
    );
    await expect(select.locator(`option[value="${connections[0].id}"]`)).toHaveCount(0);
    await mount({ kind: 'provider', route: `#/serving/connections/${connections[0].id}` });
    await expect(page.getByText('https://fixture.invalid/v1', { exact: true })).toBeVisible();
    await expect(page.getByRole('checkbox', { name: '사용 중지 포함' })).toHaveCount(0);
    await page.getByRole('button', { name: '수정', exact: true }).click();
    assert.equal(new URL(page.url()).hash, `#/serving/connections/${connections[0].id}/edit`);
    await mount({ kind: 'provider', route: `#/serving/connections/${connections[0].id}/edit` });
    await expect(page.getByLabel('이름', { exact: true })).toHaveValue(
      'Synthetic stopped provider',
    );
    await expect(page.getByRole('button', { name: '저장', exact: true })).toBeEnabled();
  });
});

for (const kind of ['model', 'provider']) {
  test(`${kind}: production-CSS list filter stays inline and touchable (OFFLINE)`, async () => {
    await harness(async (page, mount) => {
      await mount({ kind, layout: '1' });
      for (const width of [320, 390, 1280]) {
        await page.setViewportSize({ width, height: 900 });
        const geometry = await page
          .getByRole('checkbox', { name: '사용 중지 포함', exact: true })
          .evaluate((input) => {
            const label = input.closest('label').getBoundingClientRect();
            const box = input.getBoundingClientRect();
            return {
              height: label.height,
              inset: box.left - label.left,
              centerDelta: Math.abs(box.top + box.height / 2 - (label.top + label.height / 2)),
              overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
            };
          });
        assert.ok(geometry.height >= 44, JSON.stringify(geometry));
        assert.ok(geometry.inset <= 8, JSON.stringify(geometry));
        assert.ok(geometry.centerDelta <= 2, JSON.stringify(geometry));
        assert.equal(geometry.overflow, 0);
      }
    });
  });
}
