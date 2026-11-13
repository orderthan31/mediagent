// Explicit offline browser gate, like the repository's other *-browser.mjs scripts.
// Synthetic components only; no server, operating site or user session.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

test('PC and 390px production cells, failure log entry and required markers work offline', async () => {
  const job = {
    id: 'unit-job',
    ticket_number: 31,
    revision: 1,
    status: 'failed',
    display_status: 'failed',
    parent_id: null,
    access: { can_manage: true },
    reviews: [],
    artifact_manifest: { entry_count: 0 },
    snapshot: {
      asset: {
        asset_id: 'unit-asset',
        original_filename: 'literal_filename_with_a_very_long_name_and_한국어.mp4',
      },
      definition: {
        id: 'unit-definition',
        catalog_version: 2,
        revision: 1,
        inputs: {},
        nodes: [
          {
            id: 'speech',
            type: 'transcription_agent',
            position: { x: 0, y: 0 },
            options: { source_language: 'auto' },
          },
        ],
        edges: [],
      },
      tool_definition: {
        nodes: [{ id: 'speech__transcribe', type: 'transcribe', options: {} }],
        edges: [],
      },
    },
    agent_workflow: {
      nodes: [
        {
          id: 'speech',
          type: 'transcription_agent',
          label: '전사 에이전트',
          state: 'failed',
          status_label: '실패',
          reason: 'unit unknown response · 자동 재실행하지 않습니다.',
          selected_tool_id: 'speech__transcribe',
          tools: [
            {
              node_id: 'speech__transcribe',
              role: 'transcribe',
              label: '전사',
              state: 'held',
              reason: 'unit unknown response',
              run_id: 'unit-run',
            },
          ],
          outputs: [],
        },
      ],
      edges: {},
    },
    runs: [
      {
        id: 'unit-run',
        node_id: 'speech__transcribe',
        node_type: 'transcribe',
        status: 'failed',
        display_status: 'held',
        display_reason: 'unit unknown response · 자동 재실행하지 않습니다.',
        options: {},
        inputs: {},
        result: { outputs: {} },
        error_code: 'literal_outcome_unknown',
      },
    ],
  };
  job.agent_workflow.definition = job.snapshot.definition;
  const apiPath = path.resolve('src/api.ts');
  const bundle = await build({
    stdin: {
      contents: `import React from 'react';import {createRoot} from 'react-dom/client';
        import {JobLedger} from './src/JobLedger';import {RenewalJobDetail} from './src/RenewalJobDetail';import {WorkflowInputs} from './src/WorkflowInputs';
        const job=${JSON.stringify(job)};const root=createRoot(document.getElementById('root'));let serial=0;
        window.__calls=[];window.__mode='ledger';
        window.__fixtures={
          '/renewal/jobs/unit-job':job,
          '/work-entry/catalog':{nodes:[{id:'transcription_agent',label:'전사 에이전트',inputs:{},outputs:{transcript:'transcript'},options:{}}]},
          '/renewal/jobs/unit-job/projection-recoveries':{can_manage:false,candidates:[],operations:[]},
          '/renewal/jobs/unit-job/runs/unit-run/logs':{run_id:'unit-run',node_id:'speech__transcribe',state:'failed',has_more:false,shown_calls:0,total_calls:0,entries:[],console:{available:false,truncated:false,lines:[]}}
        };
        window.__mount=(mode)=>{
          window.__mode=mode;serial++;
          const current=structuredClone(job);
          if(mode==='waiting'){current.status=current.display_status='waiting';current.runs=[];current.agent_workflow.nodes[0].state='waiting';current.agent_workflow.nodes[0].tools=[];}
          window.__fixtures['/renewal/jobs/unit-job']=current;
          const ledger={job_id:'unit-job',ticket_number:'32',status:'QUEUED',original_filename:job.snapshot.asset.original_filename,created_at:'2026-01-01T00:00:00Z',metadata:{raw_status:'waiting',display_status:'waiting',workflow:{name:'literal saved workflow name that remains unchanged'}}};
          root.render(<div data-unit-mode={mode} className="video-workspace renewed-workspace ui02-workspace"><main className="video-main">{mode==='ledger'?<JobLedger items={[ledger]} />:mode==='inputs'?<WorkflowInputs inputs={{transcript:'transcript',audio:'audio'}} value={{}} onChange={()=>{}} choices={[]} />:<RenewalJobDetail key={serial} id="unit-job" />}</main></div>);
        };window.__mount('ledger');`,
      resolveDir: process.cwd(),
      loader: 'tsx',
    },
    bundle: true,
    write: false,
    platform: 'browser',
    format: 'iife',
    define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
    loader: { '.css': 'empty' },
    plugins: [
      {
        name: 'offline-api',
        setup(plugin) {
          plugin.onResolve({ filter: /api$/ }, (args) =>
            path.resolve(path.dirname(args.importer), args.path + '.ts') === apiPath
              ? { path: 'api', namespace: 'offline' }
              : undefined,
          );
          plugin.onLoad({ filter: /.*/, namespace: 'offline' }, () => ({
            contents: `
        export const base='/api';export const mediaUrl=(path)=>'/api'+path;
        export class ApiError extends Error{}
        export const request=async(path,init={})=>{
          const method=init.method||'GET';window.__calls.push({path,method});
          if(method!=='GET')throw new Error('unit forbids execution/mutation');
          if(path.endsWith('/logs')&&window.__mode==='log-error')throw new Error('unit log query unavailable');
          const value=window.__fixtures[path];if(!value)throw new Error('unit missing GET '+path);
          const result=structuredClone(value);
          if(path.endsWith('/logs')&&window.__mode==='log-lines'){result.console={available:true,truncated:false,lines:[{at:'2026-01-01T00:00:00Z',stream:'stderr',text:'literal model/console 텍스트 unchanged'}]};}
          return result;
        };export const uploadRequest=request;export const resumeUpload=()=>{throw new Error('unit forbids upload')};`,
            loader: 'js',
          }));
        },
      },
    ],
  });
  const browser = await chromium.launch({
    channel: process.platform === 'win32' ? 'msedge' : undefined,
    headless: true,
  });
  try {
    const context = await browser.newContext({ offline: true });
    await context.route('**/*', (route) => route.abort());
    const page = await context.newPage();
    await page.route('https://pm-ui.invalid/', (route) =>
      route.fulfill({
        contentType: 'text/html',
        body: '<!doctype html><html lang="ko"><head></head><body><div id="root"></div></body></html>',
      }),
    );
    await page.goto('https://pm-ui.invalid/');
    // Include the installed design system's built utility CSS, then current source
    // rules. No replacement button/theme implementation is injected by the test.
    const utilityCss = fs
      .readdirSync('dist/assets')
      .filter((name) => name.endsWith('.css'))
      .map((name) => fs.readFileSync(path.join('dist/assets', name), 'utf8'))
      .join('\n');
    assert.ok(utilityCss, 'run the existing frontend build before offline geometry checks');
    const styles =
      utilityCss +
      '\n' +
      [
        'video-workspace.css',
        'workspace-polish.css',
        'workspace-shell.css',
        'workspace-layout.css',
        'workflow-canvas.css',
        'task-result-tabs.css',
        'job-execution.css',
        'renewal-runtime.css',
      ]
        .map((name) => fs.readFileSync(path.join('src', name), 'utf8'))
        .join('\n');
    await page.addStyleTag({
      content:
        styles +
        '\nbody{margin:0} :root{--m-row-pad:12px;--m-card-pad:16px;--m-list-height:48px;--g-line:#ddd;--g-ink:#222;--g-soft:#555;--g-muted:#eee}',
    });
    await page.addScriptTag({ content: bundle.outputFiles[0].text });
    for (const width of [390, 1440]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await page.evaluate(() => window.__mount('ledger'));
      await expect(page.locator('[data-unit-mode]')).toHaveAttribute('data-unit-mode', 'ledger');
      const row = page.locator('.job-ledger-row');
      await expect(row).toBeVisible();
      for (const selector of ['.job-filename-cell', '.job-status-cell']) {
        const box = await row.locator(selector).boundingBox();
        assert.ok(
          box &&
            box.x >= 0 &&
            box.x + box.width <= width &&
            box.y >= 0 &&
            box.y + box.height <= (width === 390 ? 844 : 1000),
          `${width}px ${selector} must fit: ${JSON.stringify(box)}`,
        );
      }
      await expect(row.locator('.job-status-cell')).toHaveText('준비 대기');
      await expect(row.locator('.job-filename-cell')).toHaveText(
        job.snapshot.asset.original_filename,
      );
      await expect(row.locator('.job-workflow-cell')).toContainText('literal saved workflow');
      await expect(row.locator('.job-ticket-link')).toHaveAttribute('href', '#/jobs/unit-job');
      await page.evaluate(() => window.__mount('waiting'));
      await expect(page.locator('[data-unit-mode]')).toHaveAttribute('data-unit-mode', 'waiting');
      await expect(page.locator('.job-detail-toolbar [role="status"]')).toHaveText('준비 대기');
      assert.equal(await page.getByRole('button', { name: '작업 시작', exact: true }).count(), 0);
      for (const mode of ['failed', 'log-lines', 'log-error']) {
        await page.evaluate((mode) => window.__mount(mode), mode);
        await expect(page.locator('[data-unit-mode]')).toHaveAttribute('data-unit-mode', mode);
        const logs = page.getByRole('button', { name: '로그 보기', exact: true });
        await expect(logs).toBeVisible();
        const buttonBox = await logs.boundingBox();
        assert.ok(
          buttonBox && buttonBox.width >= 44 && buttonBox.height >= 44,
          JSON.stringify(buttonBox),
        );
        await logs.click();
        await expect(page.getByRole('tab', { name: '로그', exact: true })).toHaveAttribute(
          'aria-selected',
          'true',
        );
        const panel = page.getByRole('tabpanel', { name: '로그', exact: true });
        if (mode === 'log-lines') {
          await expect(panel).toContainText('literal model/console 텍스트 unchanged');
        } else if (mode === 'log-error') {
          await expect(panel).toContainText('최근 처리 기록을 불러오지 못했습니다.');
          assert.equal(
            await panel.getByText('수집된 에이전트·툴 원본 로그가 없습니다.').count(),
            0,
          );
        } else {
          await expect(panel).toContainText('수집된 에이전트·툴 원본 로그가 없습니다.');
          await page.getByRole('tab', { name: '출력', exact: true }).click();
          await expect(page.getByRole('tabpanel', { name: '출력', exact: true })).toContainText(
            '아직 출력 결과가 없습니다.',
          );
          assert.equal(
            await page
              .locator('.renewal-node-results')
              .getByText(job.agent_workflow.nodes[0].reason, { exact: true })
              .count(),
            0,
          );
        }
      }
      await page.evaluate(() => window.__mount('inputs'));
      await expect(page.locator('[data-unit-mode]')).toHaveAttribute('data-unit-mode', 'inputs');
      await expect(page.getByLabel('SRT 파일', { exact: true })).toHaveAttribute(
        'aria-invalid',
        'true',
      );
      await expect(page.getByText('자막을 선택하세요.', { exact: true })).toBeVisible();
      await expect(page.getByLabel('재사용 추출 음성')).toHaveAttribute(
        'aria-describedby',
        /audio-required/,
      );
    }
    assert.ok((await page.evaluate(() => window.__calls)).every(({ method }) => method === 'GET'));
  } finally {
    await browser.close();
  }
});
