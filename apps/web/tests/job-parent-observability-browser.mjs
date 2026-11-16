import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

const jobId = '1'.repeat(32),
  runId = '2'.repeat(32),
  assetId = '3'.repeat(32);
const ref = { type: 'audio', bytes: 16000, sha256: 'a'.repeat(64), storage_key: 'SYNTHETIC_ONLY' };
const definition = {
  id: 'synthetic',
  catalog_version: 2,
  revision: 1,
  inputs: {},
  nodes: [{ id: 'speech', type: 'transcription_agent', position: { x: 0, y: 0 }, options: {} }],
  edges: [],
};
const job = {
  id: jobId,
  ticket_number: 42,
  revision: 1,
  status: 'running',
  display_status: 'held',
  parent_id: null,
  access: { can_manage: false },
  reviews: [],
  snapshot: {
    asset: {
      asset_id: assetId,
      original_filename: '테스트 원본.mp4',
      size_bytes: 32000,
      sha256: 'b'.repeat(64),
    },
    definition,
    tool_definition: {
      nodes: [{ id: 'speech__transcribe', type: 'transcribe', options: {} }],
      edges: [],
    },
  },
  agent_workflow: {
    definition,
    legacy_projection: false,
    edges: {},
    nodes: [
      {
        id: 'speech',
        type: 'transcription_agent',
        label: '전사',
        state: 'held',
        status_label: '보류',
        reason: '응답 형식 오류',
        selected_tool_id: 'speech__transcribe',
        tools: [
          {
            node_id: 'speech__transcribe',
            role: 'transcribe',
            label: '구간 전사',
            state: 'held',
            reason: '응답 형식 오류',
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
      display_status: 'held',
      error_code: 'invalid_response',
      options: {},
      inputs: { audio: ref },
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
const response = {
  job_id: jobId,
  total_records: 1,
  truncated: false,
  has_more: false,
  sources: [
    {
      run_id: runId,
      node_id: 'speech__transcribe',
      available: true,
      raw_available: false,
      policy: 'private_diagnostics_v1',
      truncated: false,
    },
  ],
  records: [
    {
      id: 'failure',
      at: null,
      level: 'ERROR',
      message: '저장된 응답 형식 오류',
      run_id: runId,
      node_id: 'speech__transcribe',
      unit_index: 7,
      candidate_index: 0,
      error_code: 'invalid_response',
      source: 'stored_failure',
      provenance: 'recorded_state',
    },
  ],
};
const bundle = await build({
  nodePaths: [process.cwd() + '/node_modules'],
  stdin: {
    resolveDir: process.env.JOB_PARENT_SOURCE || process.cwd(),
    loader: 'tsx',
    contents: `import React from 'react';import{createRoot}from'react-dom/client';import{RenewalJobDetail}from'./src/RenewalJobDetail';createRoot(document.getElementById('root')).render(<RenewalJobDetail id=${JSON.stringify(jobId)}/>);`,
  },
  bundle: true,
  write: false,
  outdir: 'offline-parent',
  format: 'iife',
  platform: 'browser',
  external: ['/fonts/*'],
  define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
});
for (const { state, severity, filter, statusText } of [
  { state: 'held', severity: 'WARNING', filter: 'ALL', statusText: '보류' },
  { state: 'failed', severity: 'ERROR', filter: 'ERROR', statusText: '실패' },
])
  for (const width of [390, 1280])
    test(`actual job parent correlates failure, logs, filtered data and recovery without mutation for ${state} at ${width}px`, async () => {
      const fixtureJob = structuredClone(job);
      fixtureJob.display_status = state;
      fixtureJob.agent_workflow.nodes[0].state = state;
      fixtureJob.agent_workflow.nodes[0].tools[0].state = state;
      fixtureJob.runs[0].display_status = state;
      const fixtureLogs = structuredClone(response);
      fixtureLogs.records[0].level = severity;
      const browser = await chromium.launch({ headless: true });
      try {
        const context = await browser.newContext({
            offline: true,
            viewport: { width, height: 1000 },
          }),
          calls = [],
          errors = [];
        await context.route('**/*', (route) => {
          const req = route.request(),
            url = new URL(req.url());
          if (url.origin !== 'https://parent.invalid') return route.abort();
          if (url.pathname === '/')
            return route.fulfill({
              contentType: 'text/html',
              body: '<!doctype html><html lang="ko"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div></html>',
            });
          calls.push({ path: url.pathname, method: req.method() });
          if (url.pathname === `/api/renewal/jobs/${jobId}`)
            return route.fulfill({ json: fixtureJob });
          if (url.pathname === `/api/renewal/jobs/${jobId}/logs`)
            return route.fulfill({ json: fixtureLogs });
          if (url.pathname.endsWith('/unit-recovery'))
            return route.fulfill({
              json: { supported: false, reason: '합성 테스트: 복구 실행 없음' },
            });
          return route.fulfill({ json: {} });
        });
        const page = await context.newPage();
        page.setDefaultTimeout(4000);
        page.on('pageerror', (e) => errors.push(e.message));
        await page.goto('https://parent.invalid/');
        const css = fs
          .readdirSync('dist/assets')
          .filter((n) => n.endsWith('.css'))
          .map((n) => fs.readFileSync('dist/assets/' + n, 'utf8'))
          .join('\n');
        await page.addStyleTag({ content: css });
        await page.addScriptTag({
          content: bundle.outputFiles.find((f) => f.path.endsWith('.js')).text,
        });
        await expect(page.getByRole('tab', { name: '워크플로우', exact: true })).toHaveAttribute(
          'aria-selected',
          'true',
        );
        await page.getByRole('button', { name: '로그 보기', exact: true }).first().click();
        await expect(page.getByRole('tab', { name: '로그', exact: true })).toHaveAttribute(
          'aria-selected',
          'true',
        );
        await expect(page.getByRole('combobox', { name: '로그 등급', exact: true })).toHaveCount(0);
        await expect(page.getByRole('log')).toContainText('로그 없음');
        await expect(page.getByRole('log')).not.toContainText('저장된 응답 형식 오류');
        await page.getByRole('button', { name: '결과 보기', exact: true }).click();
        await expect(page.getByRole('tab', { name: '데이터·결과', exact: true })).toHaveAttribute(
          'aria-selected',
          'true',
        );
        const table = page.getByRole('table', { name: '작업 전체 파일과 단계 상태' });
        await expect(table.getByText(statusText, { exact: true })).toHaveCount(2);
        await expect(table.getByText('원본', { exact: true })).toHaveCount(0);
        await page.getByRole('tab', { name: '로그', exact: true }).click();
        await page.getByRole('button', { name: '태스크 보기', exact: true }).click();
        await expect(page.getByRole('tab', { name: '워크플로우', exact: true })).toHaveAttribute(
          'aria-selected',
          'true',
        );
        await expect(
          page.getByRole('region', { name: '선택한 단계 상세', exact: true }),
        ).toBeVisible();
        await page.getByRole('tab', { name: '데이터·결과', exact: true }).click();
        await page.getByRole('combobox', { name: '단계', exact: true }).selectOption('all');
        await expect(table.getByText('테스트 원본.mp4', { exact: true })).toBeVisible();
        assert.equal(await table.locator('a[download]').count(), 2);
        assert.ok(calls.every((c) => c.method === 'GET'));
        assert.deepEqual(errors, []);
        assert.ok(
          await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
        );
        if (process.env.JOB_PARENT_SCREENSHOT_DIR) {
          await page.screenshot({
            path: process.env.JOB_PARENT_SCREENSHOT_DIR + `/parent-data-${width}.png`,
            fullPage: true,
          });
        }
      } finally {
        await browser.close();
      }
    });
