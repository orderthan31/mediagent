import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { buildSync } from 'esbuild';

const render = (props) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'renewal-waiting-unit-'));
  try {
    const file = path.join(root, 'render.cjs');
    buildSync({
      stdin: {
        contents: `import React from 'react';import {renderToStaticMarkup} from 'react-dom/server';import {WaitingContents} from './src/RenewalWaitingPanel';console.log(renderToStaticMarkup(<WaitingContents {...${JSON.stringify(props)}} onReload={()=>{}} />));`,
        resolveDir: process.cwd(),
        loader: 'tsx',
      },
      outfile: file,
      bundle: true,
      platform: 'node',
      format: 'cjs',
      define: { 'import.meta.env': '{}' },
      loader: { '.css': 'empty' },
    });
    const output = spawnSync(process.execPath, [file], { encoding: 'utf8' });
    assert.equal(output.status, 0, output.stderr);
    return output.stdout;
  } finally {
    assert.ok(path.resolve(root).startsWith(path.resolve(os.tmpdir()) + path.sep));
    fs.rmSync(root, { recursive: true, force: true });
  }
};
const snapshot = { jobs: [], has_more: false, limit: 100 };
const row = {
  job_id: 'unit-job',
  ticket_number: '42',
  status: 'waiting',
  original_filename: 'literal filename.mp4',
  workflow_name: 'literal saved workflow',
  queued_at: '2026-01-01T00:00:00Z',
  access: { can_manage: true },
  deliveries: [
    { phase: 'pending', run_status: 'waiting', count: 2 },
    { phase: 'sending', run_status: 'waiting', count: 1 },
    { phase: 'sent', run_status: 'waiting', count: 1 },
    { phase: 'received', run_status: 'running', count: 1 },
    { phase: 'unknown', run_status: 'failed', count: 1 },
  ],
};

test('loading, query error and stale empty are never a confirmed zero', () => {
  const loading = render({ state: null, loading: true, error: '' });
  assert.match(loading, /확인 중/);
  assert.doesNotMatch(loading, /0개|대기 중인 전달이 없습니다/);
  const error = render({ state: null, loading: false, error: 'unit query failed' });
  assert.match(error, /unit query failed/);
  assert.doesNotMatch(error, /0개|대기 중인 전달이 없습니다/);
  const stale = render({ state: snapshot, loading: false, error: 'unit query failed' });
  assert.match(stale, /마지막 확인/);
  assert.doesNotMatch(stale, /대기 중인 전달이 없습니다/);
  assert.match(render({ state: snapshot, loading: false, error: '' }), /대기 중인 전달이 없습니다/);
});

test('genuine phases are visible separately and existing detail is the only cancel path', () => {
  const html = render({ state: { ...snapshot, jobs: [row] }, loading: false, error: '' });
  for (const text of [
    '전송 대기',
    '전송 중',
    '수신 확인 대기',
    '처리 중',
    '전송 결과 확인 필요',
    'literal filename.mp4',
    'literal saved workflow',
    '상세 · 취소 확인',
  ]) {
    assert.ok(html.includes(text), text);
  }
  assert.match(html, /#\/jobs\/unit-job/);
  assert.match(html, /자동으로 다시 보내지 않습니다/);
  assert.doesNotMatch(html, /checkbox|일시정지|순서 변경|취소 실행|재시도|재전송 버튼/);
  const shared = render({
    state: { ...snapshot, jobs: [{ ...row, access: { can_manage: false } }] },
    loading: false,
    error: '',
  });
  assert.match(shared, /상세 보기/);
  assert.match(shared, /읽기 전용/);
  assert.doesNotMatch(shared, /상세 · 취소 확인/);
});

test('bounded display reports more entries honestly without claiming a total order', () => {
  const html = render({
    state: { ...snapshot, jobs: [row], has_more: true },
    loading: false,
    error: '',
  });
  assert.match(html, /추가 항목/);
  assert.doesNotMatch(html, /순서대로|가장 먼저|일시정지/);
});
