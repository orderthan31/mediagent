import { test } from 'node:test';
import assert from 'node:assert/strict';
const mod = await import('../src/model-catalog-purpose.ts').catch((error) => {
  if (error.code === 'ERR_MODULE_NOT_FOUND') return {};
  throw error;
});
test('mapped role is labelled candidate, not inference success', () => {
  assert.equal(typeof mod.catalogPurposeLabel, 'function');
  assert.equal(
    mod.catalogPurposeLabel({
      runtime_uses: ['translation'],
      profile: {},
      classification_status: 'supported',
    }),
    '번역 후보',
  );
});
test('known unsupported and absent capability evidence are not the same state', () => {
  assert.equal(typeof mod.catalogPurposeLabel, 'function');
  assert.equal(
    mod.catalogPurposeLabel({
      runtime_uses: [],
      profile: null,
      classification_status: 'unsupported',
      provider_purpose: '음성 생성',
    }),
    '음성 생성 · 현재 제품 미지원',
  );
  assert.equal(
    mod.catalogPurposeLabel({ runtime_uses: [], profile: null, classification_status: 'unknown' }),
    '근거 미확인',
  );
});
test('legacy metadata-only registration and execution roles remain distinct', () => {
  assert.equal(typeof mod.catalogPurposeLabel, 'function');
  assert.equal(
    mod.catalogPurposeLabel({ runtime_uses: [], profile: {} }),
    '등록만 가능, 실행 어댑터 미지원',
  );
  assert.equal(
    mod.catalogPurposeLabel({ runtime_uses: ['transcription'], profile: {} }),
    '전사 후보',
  );
});
