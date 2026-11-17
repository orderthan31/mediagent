// SOURCE/OFFLINE: esbuild + routed Chromium harness used by translation-context-browser.mjs.
import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';
const workflow = 'f'.repeat(32),
  video = 'd'.repeat(32),
  jobId = 'b'.repeat(32);
const source = {
  id: workflow,
  revision: 1,
  name: 'literal auto source 🪴',
  inputs: {},
  edges: [],
  nodes: [
    {
      id: 'transcribe',
      type: 'transcribe',
      position: { x: 0, y: 0 },
      options: { max_model_calls: 'auto', source_language: 'en' },
      model_ref: { model_id: '1'.repeat(32), revision: 1 },
    },
  ],
};
const catalog = [
  {
    id: 'transcribe',
    label: '전사',
    inputs: {},
    outputs: { transcript: 'transcript' },
    options: { max_model_calls: ['auto', '1', '128'], source_language: ['en'] },
  },
];

test('concise start/detail copy preserves saved limits and pending-start fence (OFFLINE)', async () => {
  const bundle = await build({
    stdin: {
      resolveDir: process.cwd(),
      loader: 'tsx',
      contents: `import React from 'react';import{createRoot}from'react-dom/client';import{AuthGate}from'./src/AuthGate';import{PageTitleProvider}from'./src/PageTitle';import{WorkflowEditor}from'./src/WorkflowEditor';import{WorkflowStart}from'./src/WorkflowStart';import{RenewalJobDetail}from'./src/RenewalJobDetail';import{startTrackedJob}from'./src/job-start.mjs';const mode=new URLSearchParams(location.search).get('mode');if(mode==='pending'){const get=async(path)=>path.endsWith('/plan')?new Promise(()=>{}):{status:'draft',revision:1,runs:[]};const post=async()=>({});startTrackedJob(get,post,'${jobId}','offline');}createRoot(document.getElementById('root')).render(<AuthGate><PageTitleProvider>{mode==='editor'?<WorkflowEditor initialId="${workflow}"/>:['detail','pending'].includes(mode)?<RenewalJobDetail id="${jobId}"/>:<WorkflowStart/>}</PageTitleProvider></AuthGate>);`,
    },
    bundle: true,
    write: false,
    format: 'iife',
    platform: 'browser',
    define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
    loader: { '.css': 'empty' },
  });
  const browser = await chromium.launch({ headless: true });
  let graph = structuredClone(source);
  let budgets = [
    {
      node_id: 'literal-node',
      role: 'transcribe',
      budget_mode: 'input_derived',
      max_calls: null,
      planned_units: null,
      candidate_count: 2,
      budget_source: 'literal source',
    },
  ];
  const unexpected = [],
    errors = [],
    writes = [];
  try {
    const context = await browser.newContext({ offline: true });
    await context.route('**/*', (route) => {
      const req = route.request(),
        url = new URL(req.url()),
        p = url.pathname;
      const json = (value) => route.fulfill({ json: value });
      if (url.origin !== 'https://budget.invalid') {
        unexpected.push(url.href);
        return route.abort();
      }
      if (p === '/') {
        return route.fulfill({
          contentType: 'text/html',
          body: '<!doctype html><html lang="ko"><body><div id="root"></div></body></html>',
        });
      }
      if (p === '/api/auth/session') {
        return json({
          enabled: true,
          user: { id: jobId, role: 'admin', username: 'offline' },
          csrf_token: 'offline',
        });
      }
      if (p === '/api/videos/' + video + '/thumbnail') {
        return route.fulfill({ status: 204 });
      }
      if (p === '/api/videos') {
        return json({
          videos: [
            {
              asset_id: video,
              original_filename: 'literal original.mp4',
              size_bytes: 123,
              media: { duration: 12, width: 640, height: 360 },
              created_at: '2026-11-13T00:00:00Z',
            },
          ],
        });
      }
      if (['/api/work-entry/catalog', '/api/settings/node-catalog'].includes(p)) {
        return json({ nodes: catalog });
      }
      if (['/api/work-entry/workflows', '/api/settings/workflow-definitions'].includes(p)) {
        return json({ definitions: [{ id: workflow, name: graph.name, revision: 1 }] });
      }
      if (p === '/api/settings/registered-models') {
        return json({ models: [] });
      }
      if (p === '/api/settings/workflow-definitions/validate') {
        return json({ valid: true, issues: [] });
      }
      if (
        [
          '/api/work-entry/workflows/' + workflow,
          '/api/settings/workflow-definitions/' + workflow,
        ].includes(p)
      ) {
        if (req.method() === 'PUT') {
          writes.push(req.postDataJSON());
          graph = { ...req.postDataJSON(), id: workflow, revision: 1 };
        }
        return json(graph);
      }
      if (p === '/api/work-entry/inspect') {
        return json({
          supported: true,
          model_ready: true,
          definition_revision: 1,
          reasons: [],
          summary: graph.nodes.map((n) => ({
            ...n,
            model: { name: 'literal model', provider: 'fixture', revision: 1 },
          })),
        });
      }
      if (p === '/api/work-entry/preview') {
        return json({
          token: 'offline',
          paid_roles: ['transcribe'],
          model_call_budgets: budgets,
          notice: 'offline',
        });
      }
      if (p === '/api/renewal/jobs/' + jobId) {
        return json({
          id: jobId,
          ticket_number: 1,
          revision: 1,
          status: 'draft',
          parent_id: null,
          access: { can_manage: true },
          snapshot: {
            asset: { asset_id: video, original_filename: 'literal original.mp4' },
            definition: graph,
          },
          runs: [],
          reviews: [],
        });
      }
      unexpected.push(req.method() + ' ' + p);
      return route.abort();
    });
    const page = await context.newPage();
    page.on('pageerror', (e) => errors.push(e.message));
    const mount = async (mode) => {
      await page.goto(
        `https://budget.invalid/?mode=${mode}#/start?target=${video}&workflow=${workflow}`,
      );
      await page.addScriptTag({ content: bundle.outputFiles[0].text });
    };
    await mount('editor');
    await page.locator('[data-node-id="transcribe"]').first().click();
    const field = page.getByLabel('최대 모델 호출 수', { exact: true });
    await expect(field).toHaveValue('auto');
    await expect(field.locator('option[value="auto"]')).toHaveText('자동');
    for (const [index, value] of ['1', '128', 'auto'].entries()) {
      await field.selectOption(value);
      await expect(field).toHaveValue(value);
      await page.getByRole('button', { name: '저장', exact: true }).click();
      await expect.poll(() => writes.length).toBe(index + 1);
      assert.equal(graph.nodes[0].options.max_model_calls, value);
      await mount('editor');
      await page.locator('[data-node-id="transcribe"]').first().click();
      await expect(field).toHaveValue(value);
    }
    assert.deepEqual(graph.nodes, source.nodes);
    assert.equal(graph.name, source.name);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      for (const value of ['auto', '1', '128']) {
        graph.nodes[0].options.max_model_calls = value;
        budgets =
          value === 'auto'
            ? [
                {
                  node_id: 'literal-node',
                  role: 'transcribe',
                  budget_mode: 'input_derived',
                  max_calls: null,
                  planned_units: null,
                  candidate_count: 2,
                },
              ]
            : [{ node_id: 'literal-node', role: 'transcribe', max_calls: Number(value) }];
        await mount('start');
        await expect(page.getByRole('button', { name: '작업 시작', exact: true })).toBeEnabled();
        await expect(page.getByRole('region', { name: '이번 작업 모델 호출 상한' })).toHaveCount(0);
        assert.doesNotMatch(
          await page.locator('body').innerText(),
          /유한한 호출 상한|실제 입력 단위 수|API 비용|공급자 요금/,
        );
        await mount('detail');
        await expect(page.getByRole('button', { name: '작업 시작', exact: true })).toBeEnabled();
        await expect(page.locator('.job-start-scope')).toHaveCount(0);
        assert.doesNotMatch(
          await page.locator('body').innerText(),
          /유한한 호출 상한|실제 입력 단위 수|API 비용|공급자 요금/,
        );
      }
      await mount('pending');
      await expect(page.locator('[data-start-stage="plan"]')).toHaveText('시작 중…');
      await expect(page.getByRole('button', { name: '작업 시작', exact: true })).toBeDisabled();
      assert.doesNotMatch(
        await page.locator('body').innerText(),
        /원본과 실행 계획|다시 시작을 누르지|응답에 시간이 걸릴/,
      );
    }
    assert.deepEqual(unexpected, []);
    assert.deepEqual(errors, []);
    console.log(
      'OFFLINE: auto/1/128 save preserved; no billing/formula narration at 1440/390; concise pending state retains disabled Start; no provider/application start requests',
    );
  } finally {
    await browser.close();
  }
});
