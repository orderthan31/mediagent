import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { createRequire } from 'node:module';
import Module from 'node:module';
const bundle = await build({
  stdin: {
    resolveDir: process.cwd(),
    loader: 'tsx',
    contents: `
  import React from 'react';import {renderToStaticMarkup}from'react-dom/server';
  import {JobFiles,collectJobFiles}from'./src/JobFiles';
  export const collect=collectJobFiles;export const render=(props)=>renderToStaticMarkup(<JobFiles {...props}/>);`,
  },
  bundle: true,
  write: false,
  platform: 'node',
  format: 'cjs',
  external: ['react', 'react-dom/server'],
  loader: { '.css': 'empty' },
  define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
});
const mod = new Module(process.cwd() + '/tests/result-owner-offline.cjs');
mod.filename = process.cwd() + '/tests/result-owner-offline.cjs';
mod.paths = Module._nodeModulePaths(process.cwd());
mod.require = createRequire(mod.filename);
mod._compile(bundle.outputFiles[0].text, mod.filename);
const { collect, render } = mod.exports;
const ref = (type, hash = 'a') => ({ type, sha256: hash.repeat(64), bytes: 100 });
const run = (id, outputs, status = 'completed') => ({
  id,
  node_id: 'step-' + id,
  status,
  result: { outputs },
});

test('goal output is listed once; intermediate aliases with equal bytes stay out of main results', () => {
  const runs = [
    run('source', { audio: ref('audio') }),
    run('processed', { audio: ref('audio'), meta: ref('media_metadata', 'b') }),
  ];
  const agents = [
    {
      id: 'audio',
      label: '음성 추출',
      outputs: [
        { name: 'audio', run_id: 'source', node_id: 'step-source', port: 'audio', type: 'audio' },
        { name: 'audio', run_id: 'source', node_id: 'step-source', port: 'audio', type: 'audio' },
      ],
    },
  ];
  const result = collect(runs, agents);
  assert.equal(result.main.length, 1);
  assert.equal(result.main[0].run.id, 'source');
  assert.equal(result.intermediate.length, 1);
  assert.equal(result.intermediate[0].port, 'meta');
  const html = render({
    base: '/renewal/jobs/offline',
    runs,
    agents,
    manifest: { entry_count: 99 },
  });
  assert.equal((html.match(/download=""/g) || []).length, 2);
  assert.doesNotMatch(html, /요청한 결과|파일 목록\(JSON\) 받기|파일 받기/);
  assert.match(html, /중간 파일 1개/);
});
test('distinct requested outputs survive even when two language tracks have equal bytes', () => {
  const runs = [
    run('original', { subtitles: ref('subtitle') }),
    run('translated', { subtitles: ref('subtitle') }),
  ];
  const agents = [
    {
      outputs: [
        {
          name: 'subtitles',
          run_id: 'original',
          node_id: 'step-original',
          port: 'subtitles',
          type: 'subtitle',
        },
        {
          name: 'subtitles',
          run_id: 'translated',
          node_id: 'step-translated',
          port: 'subtitles',
          type: 'subtitle',
        },
      ],
    },
  ];
  const result = collect(runs, agents);
  assert.equal(result.main.length, 2);
  assert.equal(result.intermediate.length, 0);
});
test('failed/incomplete tasks are never published as final files; no-goal-yet keeps intermediate files secondary', () => {
  const runs = [
    run('prep', { audio: ref('audio') }),
    run('not-finished', { video: ref('video') }, 'running'),
  ];
  const result = collect(runs, [{ outputs: [] }]);
  assert.equal(result.main.length, 0);
  assert.equal(result.intermediate.length, 1);
  const html = render({
    base: '/renewal/jobs/offline',
    runs,
    agents: [{ id: 'speech', label: '전사', outputs: [] }],
  });
  assert.doesNotMatch(html, /아직 출력 결과가 없습니다/);
  assert.match(html, /파일 1 \/ 1개/);
  assert.match(html, /중간 파일 1개/);
  assert.match(html, /data-stage-run="not-finished"/);
  assert.doesNotMatch(html, /artifacts\/not-finished/);
});

test('unified table uses verified input/original routes, real timestamps and no fabricated failed output', () => {
  const source = 'f'.repeat(32);
  const runs = [
    {
      ...run('done', { transcript: ref('transcript') }),
      started_at: '2026-01-01T00:00:00Z',
      completed_at: '2026-01-01T00:00:02.500Z',
    },
    { ...run('failed', {}, 'failed'), inputs: { audio: ref('audio', 'b') } },
    { ...run('waiting', {}, 'waiting'), inputs: { audio: ref('audio', 'b') } },
  ];
  const html = render({
    base: '/renewal/jobs/offline',
    runs,
    originalSource: { asset_id: source, original_filename: 'original.mp4' },
    stageLabels: { 'step-done': '전사 단계' },
    onOpenLogs: () => {},
  });
  assert.match(html, /<table/);
  assert.doesNotMatch(html, /<details/);
  assert.match(html, /전사 단계/);
  assert.match(html, /2.5초/);
  assert.match(html, /파일 3 \/ 3개/);
  assert.equal((html.match(/download=""/g) || []).length, 3);
  assert.match(html, new RegExp(`/api/videos/${source}/download`));
  assert.match(html, /\/inputs\/failed\/audio/);
  assert.doesNotMatch(html, /\/inputs\/waiting\/audio|\/artifacts\/failed|\/artifacts\/waiting/);
  assert.match(html, /data-stage-run="failed"/);
  assert.match(html, /data-stage-run="waiting"/);
  assert.match(html, /생성된 파일 없음/);
});

test('subtitle format is semantic identity even if producer hashes are identical', () => {
  const runs = [run('sub', { subtitles: ref('subtitle'), sami: ref('subtitle') })];
  const result = collect(runs, [
    {
      outputs: [
        {
          name: 'subtitles',
          node_id: 'step-sub',
          run_id: 'sub',
          port: 'subtitles',
          type: 'subtitle',
        },
      ],
    },
  ]);
  assert.equal(result.main.length, 1);
  assert.equal(result.intermediate.length, 1);
  assert.equal(result.intermediate[0].port, 'sami');
});
