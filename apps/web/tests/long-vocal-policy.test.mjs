import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
test('long vocal settings distinguish original length from provider clip and total calls', () => {
  const text = readFileSync(new URL('../src/WorkflowEditor.tsx', import.meta.url), 'utf8');
  for (const value of [
    'streamed_vocalization_v2',
    '장문 분할 판정',
    '최대 6시간',
    '요청 한 번',
    '최대 모델 호출 수',
  ])
    assert.ok(text.includes(value), value);
});
