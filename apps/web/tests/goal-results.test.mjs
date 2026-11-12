import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { buildSync } from 'esbuild';
import { publicAgentGraph } from '../src/job-graphs.ts';
import { resolvePorts } from '../src/workflow-spec.ts';

test('independent media goals reopen as public agents', () => {
  for (const type of ['audio_extraction_agent', 'subtitle_file_agent', 'video_conversion_agent']) {
    const graph = { catalog_version: 2, nodes: [{ type }] };
    assert.equal(publicAgentGraph({ snapshot: { definition: graph } }), graph);
  }
});

test('SAMI appears only for the declared conditional subtitle format', () => {
  const spec = {
    inputs: {},
    outputs: { subtitles: 'subtitle' },
    options: { format: ['srt', 'srt_smi'] },
    conditional_outputs: { format: { srt_smi: { sami: 'subtitle' } } },
  };
  assert.deepEqual(resolvePorts(spec, { format: 'srt' }).outputs, { subtitles: 'subtitle' });
  assert.deepEqual(resolvePorts(spec, { format: 'srt_smi' }).outputs, {
    subtitles: 'subtitle',
    sami: 'subtitle',
  });
  assert.deepEqual(
    resolvePorts(
      { ...spec, option_roles: { format: 'generate_subtitle' } },
      {},
      { generate_subtitle: { format: 'srt_smi' } },
    ).outputs,
    { subtitles: 'subtitle', sami: 'subtitle' },
  );
});

test('requested results link to exact accepted runs without an internal tool selection', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'goal-results-unit-'));
  const outfile = path.join(root, 'render.cjs');
  buildSync({
    stdin: {
      contents: `import React from 'react'; import {renderToStaticMarkup} from 'react-dom/server';
    import {GoalResults} from './src/GoalResults';
    console.log(renderToStaticMarkup(<GoalResults base="/renewal/jobs/unit-job" agents={[
      {id:'subtitle',label:'자막 파일',outputs:[{name:'subtitles',run_id:'accepted-srt',node_id:'generate',port:'subtitles',type:'subtitle'},
      {name:'sami',run_id:'accepted-srt',node_id:'generate',port:'sami',type:'subtitle'}]},
      {id:'audio',label:'음성 추출',outputs:[{name:'audio',run_id:'accepted-wav',node_id:'extract',port:'audio',type:'audio'}]},
      {id:'pending',label:'미완료',outputs:[]}]}/>));`,
      resolveDir: process.cwd(),
      loader: 'tsx',
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
  assert.match(result.stdout, /요청한 결과/);
  assert.match(result.stdout, /accepted-srt\/subtitles\?download=true/);
  assert.match(result.stdout, /accepted-srt\/sami\?download=true/);
  assert.match(result.stdout, /accepted-wav\/audio\?download=true/);
  assert.match(result.stdout, /16kHz 모노 WAV/);
  assert.doesNotMatch(result.stdout, /미완료|storage_key|selected_tool/);
});

test('saved agent languages are read-only and irrelevant language controls are hidden', async () => {
  const { frozenGoalLanguages } = await import('../src/goal-languages.ts');
  const graph = {
    catalog_version: 2,
    nodes: [
      { id: 'asr', type: 'transcription_agent', options: { source_language: 'ja' } },
      { id: 'mt', type: 'translation_agent', options: { target_language: 'pt-BR' } },
      { id: 'file', type: 'subtitle_file_agent', options: { language: 'from_transcript' } },
    ],
  };
  assert.deepEqual(frozenGoalLanguages(graph), [
    { id: 'asr', label: '원문 언어', value: 'ja' },
    { id: 'mt', label: '대상 언어', value: 'pt-BR' },
  ]);
  assert.deepEqual(
    frozenGoalLanguages({
      catalog_version: 2,
      nodes: [{ type: 'video_conversion_agent', options: {} }],
    }),
    [],
  );
  assert.deepEqual(
    frozenGoalLanguages({
      catalog_version: 2,
      nodes: [
        {
          id: 'saved',
          type: 'translation_agent',
          options: {},
          tool_settings: { translate: { target_language: 'en-GB' } },
        },
      ],
    }),
    [{ id: 'saved', label: '대상 언어', value: 'en-GB' }],
  );
  const start = fs.readFileSync(new URL('../src/WorkflowStart.tsx', import.meta.url), 'utf8');
  assert.match(start, /frozenGoalLanguages\(definition\)/);
  assert.match(start, /definition\?\.catalog_version !== 2/);
  assert.match(start, /저장된 워크플로우/);
});

test('reopened goal options use explicit tool-role mapping without changing saved data', async () => {
  const { savedGoalOption } = await import('../src/goal-languages.ts');
  const node = {
    options: { format: 'srt_smi' },
    tool_settings: { generate_subtitle: { language: 'ja' }, encode: { video_codec: 'hevc' } },
  };
  const before = structuredClone(node);
  const spec = {
    option_roles: {
      language: 'generate_subtitle',
      format: 'generate_subtitle',
      video_codec: 'encode',
    },
  };
  assert.equal(savedGoalOption(node, spec, 'language', 'und'), 'ja');
  assert.equal(savedGoalOption(node, spec, 'format', 'srt'), 'srt_smi');
  assert.equal(savedGoalOption(node, spec, 'video_codec', 'h264'), 'hevc');
  assert.deepEqual(node, before);
});

test('native open translation languages survive edit, save and read-only start display', async () => {
  const { savedGoalOption, frozenGoalLanguages } = await import('../src/goal-languages.ts');
  const spec = {
    options: { target_language: [''] },
    option_roles: { target_language: 'translate' },
    option_defaults: { target_language: 'ko' },
  };
  assert.equal(savedGoalOption({ options: {} }, spec, 'target_language', ''), 'ko');
  for (const target of ['pt-BR', 'pl', 'en', 'ja', 'ko']) {
    const edited = {
      id: 'mt',
      type: 'translation_agent',
      options: { target_language: target },
      model_ref: { model_id: 'unit-model', revision: 7 },
    };
    const saved = JSON.parse(JSON.stringify(edited));
    assert.equal(savedGoalOption(saved, spec, 'target_language', ''), target);
    assert.equal(
      savedGoalOption(
        { options: {}, tool_settings: { translate: { target_language: target } } },
        spec,
        'target_language',
        '',
      ),
      target,
    );
    assert.deepEqual(frozenGoalLanguages({ catalog_version: 2, nodes: [saved] }), [
      { id: 'mt', label: '대상 언어', value: target },
    ]);
    assert.deepEqual(saved, edited);
  }
  const canvas = fs.readFileSync(new URL('../src/WorkflowCanvas.tsx', import.meta.url), 'utf8');
  assert.match(canvas, /spec\.option_defaults\?\.\[key\]/);
  const editor = fs.readFileSync(new URL('../src/WorkflowEditor.tsx', import.meta.url), 'utf8');
  assert.match(editor, /values\.length === 1[\s\S]*values\[0\] === ''/);
  assert.match(editor, /value=\{selectedValue\}/);
});
