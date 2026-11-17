import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseStartRequestRoute } from '../src/start-receipts.mjs';

// Keep the contract test independent of React/browser dependencies.
const source = readFileSync(new URL('../src/workspace-access.ts', import.meta.url), 'utf8');
const ordinary = new Function(
  'parseStartRequestRoute',
  source
    .replace(/^import .*;\n/m, '')
    .replace('export const', 'const')
    .replace(': string', '')
    .replace(': boolean', '') + '\nreturn isOrdinaryRoute;',
)(parseStartRequestRoute);
test('ordinary routes are originals, jobs and local subtitle editing; management stays closed', () => {
  for (const route of [
    '#/',
    '#/jobs',
    '#/start',
    '#/subtitles',
    '#/videos/' + 'a'.repeat(32),
    '#/start-requests/' + 'a'.repeat(32),
    '#/start-requests?request_id=original%2Dnonce',
    '#/jobs/' + '1'.repeat(32),
  ]) {
    assert.equal(ordinary(route), true, route);
  }
  for (const route of [
    '#/agents',
    '#/agents/analyze',
    '#/workflows',
    '#/serving',
    '#/settings',
    '#/account',
    '#/jobs/../../settings',
    '#/start/admin',
    '#/start-requests',
    '#/start-requests?request_id=x&admin=1',
    '#/start-requests/' + 'a'.repeat(32) + '/edit',
    '#/subtitles/admin',
    '#/unknown',
  ]) {
    assert.equal(ordinary(route), false, route);
  }
});
test('runtime families separate CPU/GPU dependencies without legacy compatibility', () => {
  const root = new URL('../../../', import.meta.url);
  const api = readFileSync(new URL('Dockerfile', root), 'utf8');
  const cpu = readFileSync(new URL('tools/media/Dockerfile', root), 'utf8');
  const media = readFileSync(new URL('tools/gpu/Dockerfile', root), 'utf8');
  const apiStage = api;
  assert.doesNotMatch(api, /legacy-api|agents\/media/);
  assert.doesNotMatch(
    apiStage,
    /COPY tools\/gpu|WITH_FACEFUSION|WITH_NVIDIA_VAD|pip install.*torch/,
  );
  assert.match(cpu, /COPY tools\/media/);
  assert.doesNotMatch(cpu, /COPY apps\/api|COPY agents\/media|pip install.*torch|google-genai/);
  assert.match(media, /ARG WITH_FACEFUSION=0/);
  assert.match(media, /ARG WITH_NVIDIA_VAD=0/);
  const compose = readFileSync(new URL('tools/media/compose.yaml', root), 'utf8');
  assert.match(compose, /profiles: \[analyze\]/);
  assert.match(compose, /network_mode: none/);
  assert.doesNotMatch(compose, /container_name:|docker\.sock/);
});
