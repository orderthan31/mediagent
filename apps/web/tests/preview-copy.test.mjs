import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

for (const file of ['StorageVideo.tsx']) {
  test(`${file} keeps downloads without redundant WebM guide`, async () => {
    const source = await readFile(new URL('../src/' + file, import.meta.url), 'utf8');
    assert.doesNotMatch(source, /플레이어는 웹 전용 WebM을 재생|다운로드 원본은 처리 결과 그대로/);
    assert.match(source, /WebM 받기/);
    assert.match(source, /원본 받기/);
  });
}

test('job detail has one result/download owner and video fallback does not add another download', async () => {
  const detail = await readFile(new URL('../src/RenewalJobDetail.tsx', import.meta.url), 'utf8');
  const files = await readFile(new URL('../src/JobFiles.tsx', import.meta.url), 'utf8');
  assert.equal((detail.match(/<JobFiles\b/g) || []).length, 1);
  assert.doesNotMatch(
    detail,
    /작업 결과 원본 받기|이전 30초 WebM 받기|파일 보기|<SubtitleOutputs\b/,
  );
  assert.match(files, /showDownload=\{false\}/);
  assert.match(files, /\?download=true/);
});
