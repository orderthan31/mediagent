// Actual parent + original WorkflowCanvas; all server effects are synthetic/offline.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';
const id = '1'.repeat(32),
  runId = '2'.repeat(32),
  nextRun = '3'.repeat(32),
  asset = '4'.repeat(32),
  recoveryId = '5'.repeat(32);
const definition = {
  id: 'synthetic-graph',
  name: '합성 복구 흐름',
  revision: 1,
  catalog_version: 2,
  inputs: {},
  nodes: [
    { id: 'speech', type: 'transcription_agent', position: { x: 100, y: 70 }, options: {} },
    { id: 'translation', type: 'translation_agent', position: { x: 550, y: 70 }, options: {} },
  ],
  edges: [
    {
      id: 'source-to-translation',
      source: { node: 'speech', port: 'transcript' },
      target: { node: 'translation', port: 'transcript' },
    },
  ],
};
const source = {
  type: 'audio',
  bytes: 16000,
  sha256: 'a'.repeat(64),
  storage_key: 'SYNTHETIC_ONLY',
};
const job = {
  id,
  ticket_number: 42,
  revision: 10,
  status: 'running',
  display_status: 'failed',
  parent_id: null,
  access: { can_manage: true },
  reviews: [],
  snapshot: {
    asset: { asset_id: asset, original_filename: '합성 원본.mp4', size_bytes: 32000 },
    inputs: {},
    definition,
    tool_definition: {
      nodes: [{ id: 'speech__transcribe', type: 'transcribe', options: {} }],
      edges: [],
    },
  },
  agent_workflow: {
    definition,
    edges: {},
    legacy_projection: false,
    nodes: [
      {
        id: 'speech',
        type: 'transcription_agent',
        label: '전사',
        status_label: '실패',
        state: 'failed',
        reason: '합성 응답 형식 오류',
        selected_tool_id: 'speech__transcribe',
        tools: [
          {
            node_id: 'speech__transcribe',
            label: '구간 전사',
            role: 'transcribe',
            state: 'failed',
            run_id: runId,
          },
        ],
      },
      {
        id: 'translation',
        type: 'translation_agent',
        label: '번역',
        state: 'waiting',
        status_label: '대기',
        reason: '',
        selected_tool_id: 'translation__translate',
        tools: [
          {
            node_id: 'translation__translate',
            label: '번역',
            role: 'translate',
            state: 'waiting',
            run_id: null,
          },
        ],
      },
    ],
  },
  runs: [
    {
      id: runId,
      node_id: 'speech__transcribe',
      node_type: 'transcribe',
      status: 'running',
      options: {},
      inputs: { audio: source },
      result: null,
      progress: {
        planned_segments: 96,
        completed_segments: 95,
        failed_segments: 1,
        finished_segments: 96,
      },
    },
  ],
};
const view = {
  version: 1,
  supported: true,
  blocked_reason: null,
  job_id: id,
  run_id: runId,
  role: 'transcription',
  job_revision: 10,
  recovery_revision: 0,
  context_sha256: 'a'.repeat(64),
  access: { can_manage: true },
  counts: {
    succeeded: 95,
    failed: 1,
    active: 0,
    unknown: 0,
    unattempted: 0,
    manual: 0,
    skipped: 0,
  },
  recovery: null,
  decisions: [],
  units: Array.from({ length: 96 }, (_, index) => ({
    index,
    status: index === 7 ? 'failed' : 'succeeded',
    error_code: index === 7 ? 'invalid_response' : null,
    source_ranges: [{ source_start: index * 10, source_end: (index + 1) * 10 }],
    source_rows: [],
    manual_schema: { duration_seconds: 10 },
    allowed_actions: index === 7 ? ['retry', 'skip', 'manual'] : [],
    attempts: [],
    provenance: { kind: 'synthetic' },
  })),
};
const catalog = {
  nodes: [
    { id: 'transcription_agent', label: '전사', inputs: {}, outputs: { transcript: 'transcript' } },
    {
      id: 'translation_agent',
      label: '번역',
      inputs: { transcript: 'transcript' },
      outputs: { transcript: 'transcript' },
    },
  ],
  independent_model_roles: false,
};
const bundle = await build({
  stdin: {
    resolveDir: process.cwd(),
    loader: 'tsx',
    contents: `import React from 'react';import{createRoot}from'react-dom/client';import{RenewalJobDetail}from'./src/RenewalJobDetail';window.__job=${JSON.stringify(job)};window.__view=${JSON.stringify(view)};window.__calls=[];createRoot(document.getElementById('root')).render(<RenewalJobDetail id=${JSON.stringify(id)}/>);`,
  },
  bundle: true,
  write: false,
  outdir: 'offline-canvas',
  platform: 'browser',
  format: 'iife',
  define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
  external: ['/fonts/*'],
  plugins: [
    {
      name: 'fake-api',
      setup(p) {
        p.onResolve({ filter: /^\.\/api$/ }, () => ({ path: 'api', namespace: 'fake-api' }));
        p.onLoad({ filter: /.*/, namespace: 'fake-api' }, () => ({
          loader: 'js',
          contents: `
export const mediaUrl=p=>'/api'+p;
export async function request(path,init={}){
 const body=init.body?JSON.parse(init.body):null;window.__calls.push({path,method:init.method||'GET',body});
 if(path==='/work-entry/catalog')return ${JSON.stringify(catalog)};
 if(!init.method&&path==='/renewal/jobs/${id}')return structuredClone(window.__job);
 if(!init.method&&path.endsWith('/unit-recovery'))return structuredClone(window.__view);
 if(path.endsWith('/unit-recovery/preview'))return {...body,preview_sha256:'f'.repeat(64),ready:true,additional_call_limit:0,models:[],warnings:[],blocked_reasons:[],retained_units:Array(95).fill({}),execution_units:[]};
 if(path.endsWith('/unit-recovery/decisions')){if(body.approve_calls!==false)throw Error('zero calls need no paid approval');window.__view.decisions=body.decisions;window.__view.recovery={id:'${recoveryId}',status:'approved',revision:1,request_id:body.request_id,additional_call_limit:0,executed_calls:0,can_continue:false};window.__view.recovery_revision=1;return structuredClone(window.__view);}
 if(path.endsWith('/unit-recovery/execute')){window.__view.units[7].status='skipped';window.__view.counts.failed=0;window.__view.counts.skipped=1;window.__view.recovery.can_continue=true;return structuredClone(window.__view);}
 if(path.endsWith('/unit-recovery/continue')){window.__view.recovery.status='applied';window.__view.recovery.can_continue=false;window.__job.revision++;window.__job.display_status='running';window.__job.runs[0].status='completed';window.__job.runs[0].result={outputs:{transcript:{type:'transcript',bytes:128,sha256:'b'.repeat(64)}},unit_recovery:{id:'${recoveryId}'}};window.__job.agent_workflow.nodes[0].state='completed';window.__job.agent_workflow.nodes[0].status_label='완료';window.__job.agent_workflow.nodes[0].tools[0].state='completed';window.__job.runs.push({id:'${nextRun}',node_id:'translation__translate',node_type:'translate',status:'running',options:{},inputs:{},result:null});window.__job.agent_workflow.nodes[1].state='running';return structuredClone(window.__job);}
 if(path.endsWith('/run')){window.__job.runs.push({id:'${nextRun}',node_id:'translation__translate',node_type:'translate',status:'running',options:{},inputs:{},result:null});window.__job.revision++;window.__job.agent_workflow.nodes[1].state='running';return structuredClone(window.__job);}
 throw Error('unexpected synthetic route '+path);
}`,
        }));
      },
    },
  ],
});
for (const width of [390, 1280])
  test(`original canvas → skip confirmation → explicit same-job resume at ${width}px`, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
      const context = await browser.newContext({ offline: true, viewport: { width, height: 900 } }),
        page = await context.newPage(),
        errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await context.route('**/*', (route) =>
        route.request().url() === 'https://canvas.invalid/'
          ? route.fulfill({
              contentType: 'text/html',
              body: '<!doctype html><html lang="ko"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div></html>',
            })
          : route.abort(),
      );
      await page.goto('https://canvas.invalid/');
      await page.addStyleTag({
        content: fs
          .readdirSync('dist/assets')
          .filter((n) => n.endsWith('.css'))
          .map((n) => fs.readFileSync('dist/assets/' + n, 'utf8'))
          .join('\n'),
      });
      await page.addScriptTag({
        content: bundle.outputFiles.find((f) => f.path.endsWith('.js')).text,
      });
      await expect(page.locator('.workflow-graph')).toHaveCount(1);
      assert.equal(await page.locator('.job-execution-flow').count(), 0);
      assert.equal(await page.getByRole('complementary', { name: '실행 정보' }).count(), 0);
      await expect(page.getByRole('tab', { name: '워크플로우', exact: true })).toHaveAttribute(
        'aria-selected',
        'true',
      );
      if (process.env.CANVAS_QA_DIR)
        await page.screenshot({
          path: process.env.CANVAS_QA_DIR + '/canvas-' + width + '.png',
          fullPage: true,
        });
      await page.getByRole('button', { name: '구간 복구', exact: true }).click();
      const panel = page.getByRole('region', { name: '구간 복구', exact: true });
      await panel.getByRole('button', { name: '구간 8 무시', exact: true }).click();
      assert.equal(
        await page.evaluate(() => window.__calls.filter((c) => c.method === 'POST').length),
        0,
      );
      await panel.getByRole('button', { name: '선택 내용 확인', exact: true }).click();
      await expect(
        panel.getByText('이 단계의 추가 모델 호출 없음 · 성공 구간은 다시 처리하지 않습니다.', {
          exact: true,
        }),
      ).toBeVisible();
      await panel.getByRole('button', { name: '선택 확정', exact: true }).click();
      assert.equal(
        await page.evaluate(
          () => window.__calls.filter((c) => c.path.endsWith('/continue')).length,
        ),
        0,
      );
      await expect(
        panel.getByRole('button', { name: '복구 적용·이어서 실행', exact: true }),
      ).toBeEnabled();
      await panel.getByRole('button', { name: '복구 적용·이어서 실행', exact: true }).click();
      await expect(page.getByRole('dialog', { name: '태스크 상세' })).toHaveCount(0);
      assert.equal(
        await page.evaluate(() => window.__calls.filter((c) => c.path.endsWith('/run')).length),
        0,
      );
      if (process.env.CANVAS_QA_DIR)
        await page.screenshot({
          path: process.env.CANVAS_QA_DIR + '/ready-to-resume-' + width + '.png',
          fullPage: true,
        });
      const posts = await page.evaluate(() => window.__calls.filter((c) => c.method === 'POST'));
      assert.deepEqual(
        posts.map((c) => c.path.split('/').at(-1)),
        ['preview', 'decisions', 'execute', 'continue'],
      );
      assert.equal(
        posts.at(-1).body.request_id,
        posts.find((p) => p.path.endsWith('/decisions')).body.request_id,
      );
      assert.ok(posts.every((c) => c.path.startsWith('/renewal/jobs/' + id)));
      assert.deepEqual(await page.evaluate(() => window.__job.snapshot.definition), definition);
      assert.deepEqual(errors, []);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    } finally {
      await browser.close();
    }
  });
