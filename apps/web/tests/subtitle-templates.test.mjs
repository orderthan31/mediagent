import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const text = readFileSync(new URL('../src/workflow-templates.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(text, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const templates = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'));

test('new explicit multi-language draft has a real review before text exports, leaves old template intact', () => {
  assert.equal(typeof templates.createSubtitleReviewWorkflow, 'function');
  const doc = templates.createSubtitleReviewWorkflow({ sourceLanguage: 'en', targetLanguage: 'ko', additionalLanguages: ['ja', 'fr', 'pt-BR', 'de'] });
  assert.equal(doc.nodes.filter((n) => n.type === 'translate').length, 5);
  assert.equal(doc.nodes.find((n) => n.id === 'review_subtitles').options.review_kind, 'subtitle_tracks_v1');
  assert.ok(doc.edges.some((e) => e.source.node === 'review_subtitles' && e.target.node === 'subtitle_files'));
  assert.ok(doc.nodes.some((n) => n.type === 'encode'));
  assert.equal(templates.createLegacyWorkflow().nodes.find((n) => n.id === 'review_subtitles').options.data_type, 'subtitle');
  assert.throws(() => templates.createSubtitleReviewWorkflow({ sourceLanguage: 'en', targetLanguage: 'ko', additionalLanguages: ['ko'] }));
});
