import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

const job = 'a'.repeat(32),
  run = 'b'.repeat(32),
  otherJob = 'c'.repeat(32),
  otherRun = 'd'.repeat(32);
const logs = (id = job, runId = run) => ({
  job_id: id,
  total_records: 5,
  has_more: false,
  truncated: false,
  sources: [
    {
      run_id: runId,
      node_id: 'speech',
      available: true,
      raw_available: false,
      policy: 'private_diagnostics_v1',
      truncated: false,
    },
  ],
  records: [
    {
      id: 'start',
      at: '2026-11-16T01:00:00+00:00',
      level: 'INFO',
      message: '구간 처리를 시작했습니다.',
      run_id: runId,
      node_id: 'speech',
      tool_id: 'speech.transcribe',
      source: 'diagnostic',
      provenance: 'captured',
    },
    {
      id: 'wait',
      at: '2026-11-16T01:00:01+00:00',
      level: 'WARNING',
      message: '결과 확인을 기다립니다.',
      run_id: runId,
      node_id: 'speech',
      source: 'diagnostic',
      provenance: 'captured',
    },
    {
      id: 'failure',
      at: '2026-11-16T01:00:02+00:00',
      level: 'ERROR',
      message: '<script>window.__unsafe=1</script> 형식 검사 실패',
      run_id: runId,
      node_id: 'speech',
      tool_id: 'speech.validate_chunk',
      unit_index: 7,
      error_code: 'invalid_response',
      error_type: 'ValueError',
      source: 'diagnostic',
      provenance: 'captured',
      raw: '<script>window.__unsafe=2</script>',
    },
    {
      id: 'raw',
      at: null,
      level: 'UNKNOWN',
      message: 'stderr 출력만으로 오류 등급을 만들지 않습니다.',
      run_id: runId,
      node_id: 'speech',
      source: 'console',
      provenance: 'captured',
    },
    {
      id: 'legacy',
      at: null,
      level: 'ERROR',
      message: '기존 저장된 실패 코드',
      run_id: runId,
      node_id: 'speech',
      error_code: 'invalid_response',
      unit_index: 7,
      source: 'stored_failure',
      provenance: 'recorded_state',
    },
  ],
});
const bundle = await build({
  stdin: {
    resolveDir: process.cwd(),
    loader: 'tsx',
    contents: `
import React from 'react';import{createRoot}from'react-dom/client';import{JobExecutionWorkspace}from'./src/JobExecutionWorkspace';import{JobLogExplorer}from'./src/JobLogExplorer';
const root=createRoot(document.getElementById('root'));window.issued=[];
function Harness({id=${JSON.stringify(job)},rid=${JSON.stringify(run)}}){const[tab,setTab]=React.useState('progress');const[scope,setScope]=React.useState('');return <JobExecutionWorkspace activeTab={tab} onTabChange={setTab} status="보류" stages={[{id:'agent',label:'전사 에이전트',state:'failed',runId:rid,completed:95,failed:1,planned:96}]} onStageSelect={()=>window.stageOpened=true} onStageLogs={()=>{setScope(rid);setTab('logs')}} progress={<button onClick={()=>setTab('logs')}>실패 로그로 이동</button>} data={<p>데이터 정본 하나</p>} logs={<JobLogExplorer jobId={id} enabled={tab==='logs'} runs={[{id:rid,node_id:'speech',label:'구간 전사',agentLabel:'전사 에이전트'}]} runId={scope} onRunChange={setScope} onOpenData={(rid)=>{window.dataRun=rid;setTab('data')}} onOpenStage={(rid)=>window.stageRun=rid}/>} />}
window.renderJob=(id,rid)=>root.render(<Harness id={id} rid={rid}/>);window.renderJob();`,
  },
  bundle: true,
  write: false,
  outdir: 'workspace-offline',
  platform: 'browser',
  format: 'iife',
  define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
  external: ['/fonts/*'],
});

for (const width of [390, 1280])
  test(`workspace separates progress/data/logs and correlates real records at ${width}px`, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
      const context = await browser.newContext({ offline: true, viewport: { width, height: 900 } });
      const calls = [],
        errors = [];
      await context.route('**/*', (route) => {
        const request = route.request(),
          url = new URL(request.url());
        if (url.origin !== 'https://workspace.invalid') return route.abort();
        if (url.pathname === '/')
          return route.fulfill({
            contentType: 'text/html',
            body: '<html lang="ko"><meta name="viewport" content="width=device-width, initial-scale=1"><div id="root"></div></html>',
          });
        calls.push({ path: url.pathname, method: request.method() });
        if (url.pathname === '/api/renewal/jobs/' + job + '/logs')
          return route.fulfill({ json: logs() });
        if (url.pathname === '/api/renewal/jobs/' + otherJob + '/logs')
          return route.fulfill({ json: logs(otherJob, otherRun) });
        return route.abort();
      });
      const page = await context.newPage();
      page.on('pageerror', (error) => errors.push(error.message));
      await page.goto('https://workspace.invalid/');
      await page.addStyleTag({
        content: bundle.outputFiles.find((file) => file.path.endsWith('.css')).text,
      });
      await page.addScriptTag({
        content: bundle.outputFiles.find((file) => file.path.endsWith('.js')).text,
      });
      await expect(page.getByRole('tab', { name: '진행', exact: true })).toHaveAttribute(
        'aria-selected',
        'true',
      );
      assert.deepEqual(calls, [], 'hidden logs must not create duplicate background polling');
      await page.getByRole('button', { name: '실패 로그로 이동' }).click();
      await expect(page.locator('[data-log-record]')).toHaveCount(5);
      await expect(page.getByText('구간 8', { exact: true })).toHaveCount(2);
      await expect(page.getByText('저장된 실패 정보', { exact: true })).toBeVisible();
      await expect(page.getByText('시각 미기록', { exact: true })).toHaveCount(2);
      await page.getByRole('combobox', { name: '로그 등급', exact: true }).selectOption('ERROR');
      await expect(page.locator('[data-log-record]')).toHaveCount(2);
      await page.locator('[data-log-record="failure"] summary').click();
      await expect(page.locator('[data-log-record="failure"] pre')).toHaveText(
        '<script>window.__unsafe=2</script>',
      );
      assert.equal(await page.evaluate(() => window.__unsafe), undefined);
      await page
        .locator('[data-log-record="failure"]')
        .getByRole('button', { name: '관련 데이터' })
        .click();
      await expect(page.getByRole('tab', { name: '데이터·결과', exact: true })).toHaveAttribute(
        'aria-selected',
        'true',
      );
      assert.equal(await page.evaluate(() => window.dataRun), run);
      await expect(page.getByText('데이터 정본 하나', { exact: true })).toBeVisible();
      await page.getByRole('tab', { name: '로그', exact: true }).click();
      await page.evaluate(({ id, rid }) => window.renderJob(id, rid), {
        id: otherJob,
        rid: otherRun,
      });
      await page.getByRole('combobox', { name: '로그 등급', exact: true }).selectOption('ALL');
      await expect(page.locator('[data-log-record]')).toHaveCount(5);
      await expect(page.getByRole('region', { name: '작업 로그' })).not.toContainText('undefined');
      assert.ok(calls.every((call) => call.method === 'GET'));
      assert.ok(calls.every((call) => !call.path.includes('/runs/')));
      assert.deepEqual(errors, []);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    } finally {
      await browser.close();
    }
  });
