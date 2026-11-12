import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { build } from 'esbuild';
const load = async (file) => {
  const result = await build({
    entryPoints: [file],
    bundle: true,
    write: false,
    format: 'esm',
    platform: 'node',
  });
  return import(
    'data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text).toString('base64')
  );
};
test('audio upload hints preserve videos and reject unadvertised codecs', async () => {
  const { isOriginalFile } = await load('src/video-file.ts');
  assert.equal(isOriginalFile({ name: 'literal.mp3', type: '' }), true);
  assert.equal(isOriginalFile({ name: 'sound.WAV', type: 'audio/wav' }), true);
  assert.equal(isOriginalFile({ name: 'clip.mp4', type: '' }), true);
  assert.equal(isOriginalFile({ name: 'sound.m4a', type: 'audio/mp4' }), true);
  assert.equal(isOriginalFile({ name: 'sound.aac', type: 'audio/aac' }), false);
  assert.equal(isOriginalFile({ name: 'a.flac', type: 'audio/flac' }), false);
});
test('editor audio-file profile and root input agree without shrinking a broader workflow', async () => {
  const m = await load('src/normal-inputs.ts');
  const d = {
    inputs: {},
    catalog_version: 2,
    nodes: [{ id: 'asr', type: 'transcription_agent', options: {} }],
  };
  const selected = m.setAudioSource(d, 'asr', 'audio_file_v1');
  assert.equal(selected.input_profile, 'audio_file_v1');
  assert.deepEqual(selected.inputs, { audio: 'audio' });
  assert.equal(m.normalInputReady(selected, {}), true);
  const legacy = m.setAudioSource(selected, 'asr', 'selected_audio');
  assert.equal(legacy.input_profile, undefined);
  assert.equal(m.normalInputReady(legacy, {}), false);
  const video = m.setAudioSource(selected, 'asr', 'video');
  assert.deepEqual(video.inputs, {});
  assert.throws(() =>
    m.setAudioSource(
      { ...d, nodes: [...d.nodes, { id: 'mt', type: 'translation_agent', options: {} }] },
      'asr',
      'audio_file_v1',
    ),
  );
  assert.deepEqual(d.inputs, {});
});

test('actual editor save payload carries only the explicit new audio profile (extracted production function)', async () => {
  const source = fs.readFileSync('src/WorkflowEditor.tsx', 'utf8');
  const code = source.slice(
    source.indexOf('const payload ='),
    source.indexOf('export const WorkflowEditor'),
  );
  const result = await build({
    stdin: { contents: code + '\nexport{payload};', loader: 'ts' },
    write: false,
    format: 'esm',
  });
  const { payload } = await import(
    'data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text).toString('base64')
  );
  const definition = {
    catalog_version: 2,
    revision: 0,
    name: 'source',
    inputs: { audio: 'audio' },
    nodes: [],
    edges: [],
    input_profile: 'audio_file_v1',
  };
  assert.equal(payload(definition).input_profile, 'audio_file_v1');
  const { input_profile, ...old } = definition;
  assert.equal('input_profile' in payload(old), false);
});
