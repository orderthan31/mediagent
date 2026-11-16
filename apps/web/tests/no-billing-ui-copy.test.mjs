import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

test('app-owned UI omits unsolicited billing notices without changing runtime data', () => {
  // Covers synonyms as a class, not just the word that first exposed the issue.
  // Runtime user/model/provider/error values are not read or rewritten here.
  const billing = /유료|비용|과금|환불|금액|가격|청구|결제|요금|무료/u;
  const root = path.resolve('src');
  const failures = [];
  for (const file of fs.readdirSync(root, { recursive: true })) {
    if (!/\.(ts|tsx)$/.test(file)) continue;
    const lines = fs.readFileSync(path.join(root, file), 'utf8').split('\n');
    lines.forEach((line, index) => {
      if (billing.test(line)) failures.push(`${file}:${index + 1}`);
    });
  }
  assert.deepEqual(failures, []);
});
