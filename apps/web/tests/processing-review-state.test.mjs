import { test } from 'node:test';
import assert from 'node:assert/strict';

test('persistent processing case takes precedence without changing raw status', async () => {
  const { processingLabel } = await import('../src/processing-review-state.ts');
  assert.equal(processingLabel(null), null);
  assert.equal(processingLabel({ case_id: 'a', state: 'needs_review' }), '처리 여부 확인 필요');
  assert.equal(processingLabel({ case_id: 'a', state: 'held' }), '관리자 확인 보류');
  assert.equal(processingLabel({ case_id: 'a', state: 'child_created' }), '새 복구 작업 연결됨');
});
