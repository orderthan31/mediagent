import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createSubtitleReviewWorkflow } from '../src/workflow-templates.ts';
test('explicit long multilingual video draft keeps review and adds one CPU output per exact track', () => {
  const doc = createSubtitleReviewWorkflow({
    sourceLanguage: 'en',
    targetLanguage: 'ko',
    additionalLanguages: ['ja', 'fr', 'pt-BR', 'de'],
    videoTracks: true,
    longInput: true,
  });
  const selectors = doc.nodes.filter((n) => n.type === 'subtitle_track');
  assert.equal(selectors.length, 6);
  assert.deepEqual(
    selectors.map((n) => n.options.track),
    [
      'original',
      'translated',
      'translated.ja',
      'translated.fr',
      'translated.pt-BR',
      'translated.de',
    ],
  );
  assert.equal(doc.nodes.filter((n) => n.type === 'encode').length, 6);
  assert.equal(doc.nodes.filter((n) => n.type === 'validate_video').length, 6);
  assert.equal(
    doc.nodes.find((n) => n.type === 'review').options.review_kind,
    'subtitle_tracks_v1',
  );
  for (const n of doc.nodes.filter((n) =>
    ['extract_audio', 'preprocess_audio', 'transcribe', 'translate'].includes(n.type),
  ))
    assert.equal(n.options.media_budget, 'audio_long_v5');
  assert.equal(
    doc.nodes.find((n) => n.type === 'transcribe').options.clock_policy,
    'packed_projection_v5',
  );
  assert.ok(doc.nodes.every((n) => n.position.x <= 4000 && n.position.y <= 3000));
});
