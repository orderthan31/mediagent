import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

for (const file of ['StorageVideo.tsx', 'RenewalJobDetail.tsx']) {
  test(`${file} keeps downloads without redundant WebM guide`, async () => {
    const source = await readFile(new URL('../src/' + file, import.meta.url), 'utf8');
    assert.doesNotMatch(source, /플레이어는 웹 전용 WebM을 재생|다운로드 원본은 처리 결과 그대로/);
    assert.match(source, /WebM 받기/);
    assert.match(source, /원본 받기/);
  });
}
