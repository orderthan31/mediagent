import { test } from 'node:test';
import assert from 'node:assert/strict';
const purpose = await import('../src/model-catalog-purpose.ts');
test('explicit transcription choice carries its own profile and proof, leaving the text default untouched', () => {
  assert.equal(typeof purpose.selectCatalogPurpose, 'function');
  const audio = {
    profile: { capabilities: ['speech_recognition', 'text_generation'] },
    runtime_uses: ['transcription', 'translation'],
    registration_token: 'audio-profile-proof',
    reason: 'audio contract',
    evidence: ['official audio'],
  };
  const row = {
    id: 'gemini-2.5-flash',
    profile: { capabilities: ['text_generation'] },
    runtime_uses: ['translation'],
    registration_token: 'text-profile-proof',
    profile_variants: { transcription: audio },
  };
  const selected = purpose.selectCatalogPurpose(row, 'transcription');
  assert.deepEqual(selected.profile, audio.profile);
  assert.equal(selected.registration_token, 'audio-profile-proof');
  assert.equal(selected.id, row.id);
  assert.equal(row.registration_token, 'text-profile-proof');
  assert.equal(purpose.selectCatalogPurpose(row, 'all'), row);
});
