import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { buildSync } from 'esbuild';
import { spawnSync } from 'node:child_process';

test('bounded SRT file selection preserves bytes and required input state', async () => {
  const { readSrtFile, normalInputReady } = await import('../src/normal-inputs.ts');
  const raw = '007\n00:00:00,250 --> 00:00:01,125\n literal text \n';
  const file = {
    name: 'chosen.srt',
    size: Buffer.byteLength(raw),
    arrayBuffer: async () => new TextEncoder().encode(raw).buffer,
  };
  assert.equal(await readSrtFile(file), raw);
  await assert.rejects(readSrtFile({ ...file, name: 'audio.mp3' }));
  const ordinary = raw.repeat(500);
  assert.ok(Buffer.byteLength(ordinary) > 20000);
  assert.equal(
    await readSrtFile({
      ...file,
      size: Buffer.byteLength(ordinary),
      arrayBuffer: async () => new TextEncoder().encode(ordinary).buffer,
    }),
    ordinary,
  );
  await assert.rejects(readSrtFile({ ...file, size: 16 * 1024 * 1024 + 1 }));
  const graph = { catalog_version: 2, inputs: { transcript: 'transcript' } };
  assert.equal(normalInputReady(graph, {}), false);
  assert.equal(normalInputReady(graph, { subtitle_srt: raw, input_language: 'ja' }), true);
  assert.equal(
    normalInputReady(graph, {
      accepted_inputs: { transcript: { job_id: 'j', run_id: 'r', port: 'transcript' } },
    }),
    true,
  );
  assert.equal(normalInputReady({ catalog_version: 2, inputs: { audio: 'audio' } }, {}), false);
});

test('PM login and processing copy keeps actions and removes implementation prose', () => {
  const auth = fs.readFileSync(new URL('../src/AuthGate.tsx', import.meta.url), 'utf8');
  assert.match(auth, /id="auth-title"[^>]*>\s*로그인\s*<\/h1>/);
  assert.doesNotMatch(
    auth,
    /다시 이어가는 작업|작업 공간에 로그인|영상과 자막 작업을 이어가세요|영상 보관 · 작업 관리 · 자막 검수|등록된 계정으로 로그인/,
  );
  const serving = fs.readFileSync(new URL('../src/ServingPage.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(serving, /역할 \{node.worker_role\}|포함 동작:|실행 연결/);
  const review = fs.readFileSync(
    new URL('../src/JobProcessingReview.tsx', import.meta.url),
    'utf8',
  );
  assert.match(review, /확인 내역 새로고침/);
  assert.match(review, /새 작업은 자동으로 시작되지 않습니다\./);
  assert.doesNotMatch(review, /판단 원장|별도 원장/);
});

test('accepted selections preserve the whole job/run/port identity and clear inline data', async () => {
  const { inputChoiceKey, selectAcceptedInput, normalInputReady } =
    await import('../src/normal-inputs.ts');
  const a = { job_id: 'one', run_id: 'same-run', port: 'transcript' };
  const b = { job_id: 'two', run_id: 'same-run', port: 'transcript' };
  assert.notEqual(inputChoiceKey(a), inputChoiceKey(b));
  const next = selectAcceptedInput({ subtitle_srt: 'old', input_language: 'en' }, 'transcript', b);
  assert.deepEqual(next, { accepted_inputs: { transcript: b } });
  assert.equal(
    normalInputReady(
      { catalog_version: 2, inputs: { transcript: 'transcript' } },
      { ...next, subtitle_srt: 'ambiguous' },
    ),
    false,
  );
});

test('choosing or replacing an SRT preserves explicitly selected source language', async () => {
  const { withSrtInput } = await import('../src/normal-inputs.ts');
  const previous = {
    input_language: 'ja',
    subtitle_srt: 'old',
    accepted_inputs: { audio: { job_id: 'a', run_id: 'b', port: 'audio' } },
  };
  const reading = withSrtInput(previous);
  assert.equal(reading.input_language, 'ja');
  assert.equal(reading.subtitle_srt, undefined);
  const selected = withSrtInput(reading, 'replacement SRT');
  assert.equal(selected.input_language, 'ja');
  assert.deepEqual(selected.accepted_inputs.audio, previous.accepted_inputs.audio);
});

test('editor input profile survives save/reopen without changing models or absent defaults', async () => {
  const { setWorkflowInput } = await import('../src/normal-inputs.ts');
  const original = {
    inputs: {},
    nodes: [
      {
        id: 'asr',
        type: 'transcription_agent',
        options: { source_language: 'ja' },
        model_ref: { model_id: 'chosen', revision: 9 },
      },
    ],
  };
  const changed = setWorkflowInput(original, 'audio', true);
  const saved = JSON.parse(JSON.stringify(changed));
  assert.deepEqual(saved.inputs, { audio: 'audio' });
  assert.equal(saved.nodes[0].options.audio_source, 'selected_audio');
  assert.deepEqual(saved.nodes[0].model_ref, original.nodes[0].model_ref);
  assert.deepEqual(original.inputs, {});
  assert.deepEqual(setWorkflowInput(saved, 'audio', false).inputs, {});
});

test('normal input chooser renders file, prior result, loading and errors without JSON-only workflow', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'normal-input-ui-unit-'));
  const outfile = path.join(root, 'render.cjs');
  buildSync({
    stdin: {
      resolveDir: process.cwd(),
      loader: 'tsx',
      contents: `import React from 'react';import {renderToStaticMarkup} from 'react-dom/server';
    import {WorkflowInputs} from './src/WorkflowInputs';
    import {DecisionPanel} from './src/DecisionPanel';
    console.log(renderToStaticMarkup(<><WorkflowInputs inputs={{transcript:'transcript',audio:'audio'}} value={{}} onChange={()=>{}} loading error="unit unavailable" choices={[{job_id:'j',run_id:'r',port:'audio',label:'#1 WAV'}]}/>
      <DecisionPanel status="failed" evidence={{status:'unknown',code:'unit_unknown',error_type:'unit raw error'}} />
      <DecisionPanel status="failed" />
      <DecisionPanel status="running" />
      <DecisionPanel status="completed" evidence={{status:'succeeded',selected_port:'route-a',judgment:{version:1,label:'chosen',confidence:0.9,reason:'literal reason'},input_sha256:'hidden-sha'}} />
    </>));`,
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
  assert.match(result.stdout, /type="file"/);
  assert.match(result.stdout, /SRT/);
  assert.match(result.stdout, /완료 입력 확인 중/);
  assert.match(result.stdout, /unit unavailable/);
  assert.match(result.stdout, /16kHz 모노/);
  assert.doesNotMatch(result.stdout, /textarea|storage_key|JSON/);
  assert.match(result.stdout, /unit_unknown/);
  assert.match(result.stdout, /unit raw error/);
  assert.match(result.stdout, /현재 상태: failed/);
  assert.match(result.stdout, /판단 결과를 기다리고 있습니다/);
  assert.match(result.stdout, /literal reason/);
  assert.doesNotMatch(result.stdout, /hidden-sha|adapter/);
});
