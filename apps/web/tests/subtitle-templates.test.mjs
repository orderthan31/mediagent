import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const text = readFileSync(new URL('../src/workflow-templates.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(text, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText;
const templates = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'));

test('new explicit multi-language draft has a real review before text exports, leaves old template intact', () => {
  assert.equal(typeof templates.createSubtitleReviewWorkflow, 'function');
  const doc = templates.createSubtitleReviewWorkflow({
    sourceLanguage: 'en',
    targetLanguage: 'ko',
    additionalLanguages: ['ja', 'fr', 'pt-BR', 'de'],
  });
  assert.equal(doc.nodes.filter((n) => n.type === 'translate').length, 5);
  assert.equal(
    doc.nodes.find((n) => n.id === 'review_subtitles').options.review_kind,
    'subtitle_tracks_v1',
  );
  assert.ok(
    doc.edges.some(
      (e) => e.source.node === 'review_subtitles' && e.target.node === 'subtitle_files',
    ),
  );
  assert.ok(doc.nodes.some((n) => n.type === 'encode'));
  assert.equal(
    templates.createLegacyWorkflow().nodes.find((n) => n.id === 'review_subtitles').options
      .data_type,
    'subtitle',
  );
  assert.throws(() =>
    templates.createSubtitleReviewWorkflow({
      sourceLanguage: 'en',
      targetLanguage: 'ko',
      additionalLanguages: ['ko'],
    }),
  );
});

test('review OFF rewires real human gates without losing model pins or language outputs', () => {
  const doc = templates.createSubtitleReviewWorkflow({
    sourceLanguage: 'en',
    targetLanguage: 'ko',
    videoTracks: true,
  });
  doc.nodes.find((n) => n.type === 'transcribe').model_ref = {
    model_id: 'a'.repeat(32),
    revision: 2,
  };
  const off = templates.withoutHumanReview(doc);
  assert.ok(doc.nodes.some((n) => n.type === 'review'));
  assert.equal(off.id, doc.id);
  assert.equal(off.revision, doc.revision);
  assert.equal(
    off.nodes.some((n) => n.type === 'review'),
    false,
  );
  assert.deepEqual(
    off.nodes.find((n) => n.type === 'transcribe').model_ref,
    doc.nodes.find((n) => n.type === 'transcribe').model_ref,
  );
  assert.equal(off.nodes.filter((n) => n.type === 'encode').length, 2);
  assert.ok(
    off.nodes
      .filter((n) => ['subtitle_outputs', 'subtitle_track'].includes(n.type))
      .every((n) => n.options.review_policy === 'off'),
  );
  const ids = new Set(['$input', ...off.nodes.map((n) => n.id)]);
  assert.ok(off.edges.every((e) => ids.has(e.source.node) && ids.has(e.target.node)));
  assert.ok(
    off.edges.some(
      (e) => e.source.node === 'subtitle_tracks' && e.target.node === 'subtitle_files',
    ),
  );
});
