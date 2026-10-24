import { test } from 'node:test';
import assert from 'node:assert/strict';
const templates = await import('../src/workflow-templates.ts').catch((error) => {
  if (error.code === 'ERR_MODULE_NOT_FOUND') return {};
  throw error;
});
test('legacy-equivalent editable workflow preserves the audio/timeline producer and both subtitle branches without face swap', () => {
  assert.equal(typeof templates.createLegacyWorkflow, 'function');
  const workflow = templates.createLegacyWorkflow();
  assert.equal(workflow.revision, 0);
  assert.equal(workflow.catalog_version, 1);
  assert.match(workflow.id, /^[a-f0-9]{32}$/);
  assert.equal(
    workflow.nodes.some((node) => node.type === 'faceswap'),
    false,
  );
  for (const type of [
    'analyze',
    'extract_audio',
    'preprocess_audio',
    'transcribe',
    'translate',
    'generate_subtitle',
    'review',
    'encode',
    'validate_video',
  ])
    assert(
      workflow.nodes.some((node) => node.type === type),
      type,
    );
  const asr = workflow.nodes.find((node) => node.type === 'transcribe'),
    prep = workflow.nodes.find((node) => node.type === 'preprocess_audio');
  assert.deepEqual(
    workflow.edges
      .filter((edge) => edge.target.node === asr.id)
      .map((edge) => [edge.source.node, edge.source.port, edge.target.port])
      .sort(),
    [
      [prep.id, 'audio', 'audio'],
      [prep.id, 'timeline', 'timeline'],
    ].sort(),
  );
  const subtitleNodes = workflow.nodes.filter((node) => node.type === 'generate_subtitle');
  assert.equal(subtitleNodes.length, 2);
  const producers = subtitleNodes.map(
    (node) => workflow.edges.find((edge) => edge.target.node === node.id).source.node,
  );
  assert(producers.includes(asr.id));
  assert(producers.includes(workflow.nodes.find((node) => node.type === 'translate').id));
  assert.equal(prep.options.vad_mode, 'off');
  assert.equal(prep.options.audio_filter, 'off');
  assert(
    workflow.edges.some(
      (edge) =>
        edge.target.node === workflow.nodes.find((node) => node.type === 'encode').id &&
        edge.target.port === 'subtitles',
    ),
  );
});

test('optional review is an explicit template choice while model batching is frozen in the new draft', () => {
  const workflow = templates.createLegacyWorkflow({ review: false });
  assert.equal(workflow.nodes.some(node => node.type === 'review'), false);
  assert.equal(workflow.nodes.find(node => node.type === 'transcribe').options.batch_policy, 'bounded_60s_v1');
  assert.equal(workflow.nodes.find(node => node.type === 'translate').options.batch_policy, 'bounded_100x16k_v1');
  const encode=workflow.nodes.find(node=>node.type==='encode');
  const subtitles=workflow.nodes.find(node=>node.id==='translated_subtitles');
  assert(workflow.edges.some(edge=>edge.source.node===subtitles.id&&edge.target.node===encode.id&&edge.target.port==='subtitles'));
  assert.equal(templates.createLegacyWorkflow().nodes.some(node=>node.type==='review'),true);
});
