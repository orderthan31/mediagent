// Synthetic job-detail integration; every network request is blocked.
// Mirrors the installed 96-unit / 95 preserved / one failure discovery shape.
import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';
import { readFile, readdir } from 'node:fs/promises';

const jobId = 'a'.repeat(32);
const runId = 'b'.repeat(32);
const definition = {
  id: 'c'.repeat(32),
  name: 'Offline discovery',
  revision: 1,
  catalog_version: 2,
  inputs: {},
  edges: [],
  nodes: [{ id: 'speech', type: 'transcription_agent', position: { x: 0, y: 80 }, options: {} }],
};
const job = {
  id: jobId,
  ticket_number: 41,
  status: 'running',
  display_status: 'failed',
  revision: 10,
  access: { can_manage: true },
  reviews: [],
  artifact_manifest: { entry_count: 0 },
  snapshot: {
    asset: { asset_id: 'd'.repeat(32), original_filename: 'offline.mp4' },
    definition,
    tool_definition: {
      nodes: [{ id: 'speech__transcribe', type: 'transcribe', options: {} }],
      edges: [],
    },
  },
  agent_workflow: {
    definition,
    edges: {},
    nodes: [
      {
        id: 'speech',
        type: 'transcription_agent',
        label: '전사 에이전트',
        state: 'failed',
        status_label: '오류',
        reason: '모델 응답 형식 오류',
        selected_tool_id: 'speech__transcribe',
        outputs: [],
        tools: [
          {
            node_id: 'speech__transcribe',
            role: 'transcribe',
            label: '구간 전사 처리',
            state: 'failed',
            reason: '모델 응답 형식 오류',
            run_id: runId,
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
      display_status: 'failed',
      options: {},
      inputs: {},
      result: null,
    },
  ],
};
const view = {
  version: 1,
  supported: true,
  blocked_reason: null,
  job_id: jobId,
  run_id: runId,
  task_id: runId,
  role: 'transcription',
  job_revision: 10,
  recovery_revision: 0,
  context_sha256: 'e'.repeat(64),
  access: { can_manage: true },
  recovery: null,
  counts: {
    succeeded: 95,
    failed: 1,
    unknown: 0,
    active: 0,
    unattempted: 0,
    manual: 0,
    skipped: 0,
  },
  units: Array.from({ length: 96 }, (_, index) => ({
    index,
    status: index === 7 ? 'failed' : 'succeeded',
    error_code: index === 7 ? 'invalid_response' : null,
    source_ranges: [{ source_start: index * 60, source_end: (index + 1) * 60 }],
    source_rows: [],
    manual_schema: { duration_seconds: 60 },
    allowed_actions: index === 7 ? ['retry', 'skip', 'manual'] : [],
    attempts: [],
    provenance: { kind: 'original' },
  })),
};
const bundle = await build({
  stdin: {
    resolveDir: process.cwd(),
    loader: 'tsx',
    contents: `
    import React from 'react';import {createRoot} from 'react-dom/client';
    import {RenewalJobDetail} from './src/RenewalJobDetail';
    window.__job=${JSON.stringify(job)};window.__view=${JSON.stringify(view)};window.__calls=[];
    createRoot(document.getElementById('root')).render(<div className="video-workspace renewed-workspace ui02-workspace"><main className="video-main"><RenewalJobDetail id="${jobId}"/></main></div>);`,
  },
  bundle: true,
  write: false,
  outdir: 'offline',
  platform: 'browser',
  format: 'iife',
  define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
  loader: { '.css': 'empty' },
  plugins: [
    {
      name: 'offline-only',
      setup(p) {
        p.onResolve({ filter: /^\.\/api$/ }, () => ({ path: 'api', namespace: 'offline' }));
        p.onLoad({ filter: /.*/, namespace: 'offline' }, () => ({
          loader: 'js',
          contents: `
      export const base='/api';export const mediaUrl=p=>'/api'+p;export class ApiError extends Error{}
      export const request=async(path,init={})=>{const method=init.method||'GET';const body=init.body?JSON.parse(init.body):null;
        window.__calls.push({path,method,body});const b='/renewal/jobs/${jobId}';
        if(path===b)return structuredClone(window.__job);
        if(path==='/work-entry/catalog')return {nodes:[{id:'transcription_agent',label:'전사 에이전트',inputs:{media:'media'},outputs:{media:'media'},options:{}}],independent_model_roles:true};
        if(path===b+'/projection-recoveries')return {can_manage:true,candidates:[],operations:[]};
        if(path===b+'/model-role')return {enrolled:true,tasks:[]};
        if(path.endsWith('/logs'))return {run_id:'${runId}',node_id:'speech__transcribe',state:'running',display_state:'failed',has_more:false,shown_calls:0,total_calls:96,entries:[],console:{available:false,truncated:false,lines:[]}};
        if(path.endsWith('/unit-recovery')&&method==='GET')return structuredClone(window.__view);
        if(path.endsWith('/unit-recovery/preview')&&method==='POST')return {...body,preview_sha256:'f'.repeat(64),ready:true,decisions:body.decisions,additional_call_limit:0,models:[],warnings:[],blocked_reasons:[],retained_units:Array(95).fill({}),execution_units:[]};
        throw new Error('OFFLINE_ONLY_UNMAPPED '+method+' '+path);};
      export const uploadRequest=request;export const resumeUpload=()=>{throw new Error('NO_UPLOAD')};`,
        }));
      },
    },
  ],
});
const cssNames = (await readdir('dist/assets')).filter((n) => n.endsWith('.css'));
const css = (await Promise.all(cssNames.map((n) => readFile('dist/assets/' + n, 'utf8')))).join(
  '\n',
);
for (const width of [390, 1280]) {
  test(`job detail exposes failed unit actions without scrolling through 95 successes at ${width}px`, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
      const context = await browser.newContext({ offline: true, viewport: { width, height: 900 } });
      await context.route('**/*', (r) => r.abort());
      const page = await context.newPage();
      page.setDefaultTimeout(8000);
      const errors = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.route('https://recovery-discovery.invalid/', (route) =>
        route.fulfill({
          contentType: 'text/html',
          body: '<html lang="ko"><head></head><body><div id="root"></div></body></html>',
        }),
      );
      await page.goto('https://recovery-discovery.invalid/');
      await page.addStyleTag({ content: css });
      await page.addScriptTag({
        content: bundle.outputFiles.find((f) => f.path.endsWith('.js')).text,
      });
      await page.waitForTimeout(150);
      assert.deepEqual(errors, []);
      assert.ok(
        await page.locator('[data-node-id="speech"]').count(),
        await page.locator('body').innerText(),
      );
      await page.getByRole('button', { name: '구간 복구', exact: true }).click();
      const panel = page.getByRole('region', { name: '구간 복구', exact: true });
      await expect(panel).toContainText('복구 요청 전');
      const retry = panel.getByRole('button', { name: '구간 8 재시도', exact: true });
      const skip = panel.getByRole('button', { name: '구간 8 무시', exact: true });
      const manual = panel.getByRole('button', { name: '구간 8 직접 입력', exact: true });
      if (process.env.RECOVERY_QA_SCREENSHOTS)
        await page.screenshot({
          path: process.env.RECOVERY_QA_SCREENSHOTS + '/recovery-' + width + '.png',
          fullPage: true,
        });
      await expect(retry).toBeInViewport();
      await expect(skip).toBeInViewport();
      await expect(manual).toBeInViewport();
      await expect(panel.locator('[data-unit="0"]')).not.toBeVisible();
      await skip.click();
      assert.equal(
        await page.evaluate(() => window.__calls.filter((c) => c.method !== 'GET').length),
        0,
      );
      const preview = panel.getByRole('button', { name: '선택 내용 확인', exact: true });
      await expect(preview).toBeInViewport();
      await preview.click();
      assert.deepEqual(
        await page.evaluate(() =>
          window.__calls
            .filter((c) => c.method !== 'GET')
            .map((c) => ({ suffix: c.path.split('/').at(-1), body: c.body.decisions })),
        ),
        [{ suffix: 'preview', body: [{ unit_index: 7, action: 'skip' }] }],
      );
      await expect(
        panel.getByText('이 단계의 추가 모델 호출 없음 · 성공 구간은 다시 처리하지 않습니다.', {
          exact: true,
        }),
      ).toBeVisible();
      await panel.getByText('성공·보존 95개 구간 보기', { exact: true }).click();
      await expect(panel.locator('[data-unit="0"]')).toBeVisible();
      assert.equal(
        await page.evaluate(() =>
          window.__calls.some((c) => /\/(decisions|execute|continue)$/.test(c.path)),
        ),
        false,
      );
      await browser.close();
    } finally {
      await browser.close();
    }
  });
}
