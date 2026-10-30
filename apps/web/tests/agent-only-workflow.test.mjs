import test from 'node:test';
import assert from 'node:assert/strict';
import * as templates from '../src/workflow-templates.ts';
test('public draft is the three-agent Korean burn-in flow, not standalone tools', () => {
  assert.equal(
    typeof templates.createAgentWorkflow,
    'function',
    'agent-only editable template is missing',
  );
  const doc = templates.createAgentWorkflow();
  assert.equal(doc.catalog_version, 2);
  assert.deepEqual(doc.inputs, {});
  assert.deepEqual(
    doc.nodes.map((n) => n.type),
    ['transcription_agent', 'translation_agent', 'subtitle_video_agent'],
  );
  assert.equal(doc.edges.length, 2);
  assert.equal(doc.nodes[0].options.source_language, 'auto');
  assert.equal(doc.nodes[1].options.target_language, 'ko');
});

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { buildSync } from 'esbuild';
const render = (failed = false) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'agent-canvas-'));
  const file = path.join(root, 'render.cjs');
  buildSync({
    stdin: {
      contents: `import React from 'react'; import {renderToStaticMarkup} from 'react-dom/server'; import {WorkflowCanvas} from './src/WorkflowCanvas'; import {createAgentWorkflow} from './src/workflow-templates';
    const doc=createAgentWorkflow();const catalog=doc.nodes.map((n,i)=>({id:n.type,label:['전사 에이전트','한국어 번역 에이전트','자막 영상 제작 에이전트'][i],inputs:i?{media:'media_task'}:{},outputs:i===2?{video:'video'}:{media:'media_task'},options:{}}));
    console.log(renderToStaticMarkup(<WorkflowCanvas definition={doc} catalog={catalog} nodeStates={{translation:{state:${failed ? "'failed'" : "'preparing'"},label:${failed ? "'오류'" : "'준비 중'"},reason:${failed ? "'모델 연결 실패'" : "''"}}}} edgeStates={{[doc.edges[0].id]:{state:${failed ? "'failed'" : "'preparing'"},label:${failed ? "'실행 오류'" : "'다음 단계 준비 중'"}}}}/>));`,
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
  const result = spawnSync(process.execPath, [file], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  return result.stdout;
};
test('observed coldboot is visible on the connecting edge and target, including reduced motion', () => {
  const html = render();
  assert.match(html, /data-edge-preparation=/);
  assert.match(html, /다음 단계 준비 중/);
  assert.match(html, /data-state="preparing"/);
  assert.equal((html.match(/data-node-kind="agent"/g) || []).length, 3);
  const css = fs.readFileSync(new URL('../src/workflow-canvas.css', import.meta.url), 'utf8');
  assert.match(css, /@media[^}]*prefers-reduced-motion[\s\S]*workflow-preparation-spinner/);
});
test('failed agent visibly includes an error icon and short reason instead of a live spinner', () => {
  const html = render(true);
  assert.match(html, /aria-label="오류"/);
  assert.match(html, /모델 연결 실패/);
  assert.doesNotMatch(html, /data-edge-preparation=/);
});

test('console data from another tool is never rendered during a selection change', async () => {
  const scope = await import('../src/task-log-scope.mjs').catch(() => ({}));
  assert.equal(typeof scope.taskLogForRun, 'function', 'console scope guard is missing');
  const previous = {
    run_id: 'old-tool',
    console: { lines: [{ text: 'previous tool private console' }] },
  };
  assert.equal(scope.taskLogForRun(previous, 'next-tool'), null);
  assert.equal(scope.taskLogForRun(previous, undefined), null);
  assert.equal(scope.taskLogForRun(previous, 'old-tool'), previous);
});
