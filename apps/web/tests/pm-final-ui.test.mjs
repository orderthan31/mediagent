import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { buildSync } from 'esbuild';

const render = (contents) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pm-ui-source-'));
  const outfile = path.join(root, 'render.cjs');
  try {
    buildSync({
      stdin: {
        contents: `import React from 'react'; import {renderToStaticMarkup} from 'react-dom/server'; ${contents}`,
        loader: 'tsx',
        resolveDir: process.cwd(),
      },
      outfile,
      bundle: true,
      platform: 'node',
      format: 'cjs',
      define: { 'import.meta.env': '{}' },
      loader: { '.css': 'empty' },
    });
    const result = spawnSync(process.execPath, [outfile], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    return result.stdout;
  } finally {
    assert.ok(path.resolve(root).startsWith(path.resolve(os.tmpdir()) + path.sep));
    fs.rmSync(root, { recursive: true, force: true });
  }
};

test('language names are display-only and preserve regional distinctions', async () => {
  const { languageLabel } = await import('../src/language-label.ts');
  assert.equal(languageLabel('ko'), '한국어');
  assert.equal(languageLabel('auto'), '자동 감지');
  assert.notEqual(languageLabel('pt-BR'), languageLabel('pt-PT'));
  assert.match(languageLabel('pt-BR'), /브라질/);
  assert.equal(languageLabel('unit_invalid_code'), 'unit_invalid_code');
});

test('admitted waiting, dispatch, uncertainty and untouched draft have shared truthful labels', async () => {
  const source = buildSync({
    entryPoints: ['src/job-display.ts'],
    bundle: true,
    write: false,
    format: 'esm',
    platform: 'node',
  }).outputFiles[0].text;
  const { jobStateLabel } = await import(
    'data:text/javascript;base64,' + Buffer.from(source).toString('base64')
  );
  assert.equal(jobStateLabel({ status: 'draft' }), '시작 전');
  assert.equal(jobStateLabel({ status: 'waiting', runs: [] }), '준비 대기');
  assert.equal(jobStateLabel({ status: 'waiting', execution_state: 'preparing' }), '준비 중');
  for (const [phase, label] of [
    ['pending', '전송 대기'],
    ['sending', '전송 중'],
    ['sent', '수신 확인 대기'],
    ['received', '처리 중'],
    ['unknown', '전송 결과 확인 필요'],
  ]) {
    assert.equal(
      jobStateLabel({ status: 'waiting', runs: [{ status: 'running', dispatch: { phase } }] }),
      label,
    );
    assert.equal(jobStateLabel({ status: 'waiting', dispatch_phase: phase }), label);
  }
  assert.equal(jobStateLabel({ status: 'failed' }), '실패');
  assert.equal(
    jobStateLabel({ status: 'running', display_status: 'held' }),
    '보류 · 응답 확인 필요',
  );
});

test('actual ledger cells expose filename/status and retain ticket/workflow/date', () => {
  const html = render(
    `import {JobLedger} from './src/JobLedger'; console.log(renderToStaticMarkup(<JobLedger items={[{job_id:'synthetic-job',ticket_number:'32',status:'QUEUED',original_filename:'literal long filename.mp4',created_at:'2026-01-01T00:00:00Z',metadata:{raw_status:'waiting',workflow:{name:'literal saved workflow'}}}]} />));`,
  );
  assert.match(html, /class="job-filename-cell"/);
  assert.match(html, /class="job-status-cell"/);
  assert.match(html, /준비 대기/);
  assert.match(html, /literal long filename.mp4/);
  assert.match(html, /literal saved workflow/);
  assert.match(html, /#\/jobs\/synthetic-job/);
  assert.match(html, /2026-01-01T00:00:00Z/);
});

test('results distinguish empty, stale, individual files and JSON manifest', () => {
  const empty = render(
    `import {JobFiles} from './src/JobFiles'; console.log(renderToStaticMarkup(<JobFiles base="/renewal/jobs/unit" runs={[]} manifest={{entry_count:0}} />));`,
  );
  assert.match(empty, /아직 출력 결과가 없습니다/);
  assert.doesNotMatch(empty, /download|파일 목록|받기/);
  const stale = render(
    `import {JobFiles} from './src/JobFiles'; console.log(renderToStaticMarkup(<JobFiles base="/renewal/jobs/unit" runs={[]} stale />));`,
  );
  assert.match(stale, /다시 확인하지 못했습니다/);
  assert.doesNotMatch(stale, /출력 결과가 없습니다/);
  const files = render(
    `import {JobFiles} from './src/JobFiles'; console.log(renderToStaticMarkup(<JobFiles base="/renewal/jobs/unit" manifest={{entry_count:2}} runs={[{id:'accepted',node_id:'step',status:'completed',result:{outputs:{transcript:{type:'transcript'},video:{type:'video'}}}}]} />));`,
  );
  assert.match(files, /전사문\(JSON\)/);
  assert.match(files, /파일 목록\(JSON\)/);
  assert.match(files, /accepted\/video\?download=true/);
  assert.match(files, /accepted\/transcript\?download=true/);
});

test('external failure selection opens actual canvas detail and logs tab', () => {
  const html = render(
    `import {WorkflowCanvas} from './src/WorkflowCanvas';import {TaskResultTabs} from './src/TaskResultTabs';console.log(renderToStaticMarkup(<WorkflowCanvas selectedNodeId="speech" definition={{id:'unit',catalog_version:2,nodes:[{id:'speech',type:'transcription_agent',position:{x:0,y:0},options:{}}],edges:[]}} catalog={[{id:'transcription_agent',label:'전사',inputs:{},outputs:{},options:{}}]} details={<TaskResultTabs jobId="unit" initialState="failed" initialTab="logs"><p>OUTPUT SENTINEL</p></TaskResultTabs>} />));`,
  );
  assert.match(html, /workflow-node-settings/);
  assert.match(html, /aria-selected="true"[^>]*>로그/);
  assert.match(html, /수집된 에이전트·툴 원본 로그가 없습니다/);
});

test('required timed input has an accessible field-linked marker and settings are single links', () => {
  const html = render(
    `import {WorkflowInputs} from './src/WorkflowInputs'; import {SystemSettings} from './src/SystemSettings'; console.log(renderToStaticMarkup(<><WorkflowInputs inputs={{transcript:'transcript',audio:'audio'}} value={{}} choices={[]} onChange={()=>{}} /><SystemSettings /></>));`,
  );
  assert.match(html, /aria-invalid="true"/);
  assert.match(html, /aria-describedby=/);
  assert.match(html, /자막을 선택하세요/);
  assert.match(html, /추출 음성을 선택하세요/);
  assert.doesNotMatch(html, />작업 설정</);
  assert.equal((html.match(/워크플로우 설정/g) || []).length, 1);
  const language = render(
    `import {WorkflowInputs} from './src/WorkflowInputs';console.log(renderToStaticMarkup(<WorkflowInputs inputs={{transcript:'transcript'}} value={{subtitle_srt:'unit selected SRT',input_language:''}} choices={[]} onChange={()=>{}} />));`,
  );
  assert.match(language, /원문 언어를 입력하세요/);
  assert.match(language, /language-required/);
});
