import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('Docker copies local Hangyeol vendor dependency before npm ci', async () => {
  const dockerfile = await readFile(new URL('../Dockerfile', import.meta.url), 'utf8');
  const copy = dockerfile.indexOf('COPY apps/web/vendor ./vendor');
  assert.ok(copy >= 0 && copy < dockerfile.indexOf('RUN npm ci'));
});
