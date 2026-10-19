import assert from 'node:assert/strict';
import { randomBytes, randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from '../../apps/web/node_modules/@playwright/test/index.mjs';
const base = process.env.MIDEAGENT_TEST_ORIGIN;
const evidence = process.env.MIDEAGENT_FLEET_EVIDENCE;
assert(base?.startsWith('http://127.0.0.1:') && evidence);
await mkdir(evidence, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.MIDEAGENT_TEST_CHROME ? { executablePath: process.env.MIDEAGENT_TEST_CHROME } : {}), args: ['--disable-gpu'] });
const errors = [];
const contexts = [];
const makeContext = async () => {
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  await context.route('**/*', route => new URL(route.request().url()).origin === base ? route.continue() : route.abort());
  contexts.push(context);
  return context;
};
const wait = async callback => {
  for (let attempt = 0; attempt < 120; attempt++) {
    const result = await callback();
    if (result) return result;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Expected persisted state did not arrive');
};
const password = randomBytes(24).toString('base64url');
try {
  const administrator = await makeContext();
  assert.equal((await administrator.request.post(base + '/api/auth/bootstrap', { data: { username: 'fleet-browser', password } })).status(), 201);
  const login = await administrator.request.post(base + '/api/auth/login', { data: { username: 'fleet-browser', password } });
  assert.equal(login.status(), 200);
  const csrf = (await login.json()).csrf_token;
  const post = (path, data) => administrator.request.post(base + '/api' + path, { data, headers: { 'X-CSRF-Token': csrf } });
  const page = await administrator.newPage();
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(base + '/#/agents/analyze');
  await page.getByRole('heading', { name: '운영 관리', exact: true }).waitFor();
  await page.getByLabel('에이전트 활성화', { exact: true }).check();
  await page.getByLabel('목표 실행 개수', { exact: true }).fill('2');
  await page.getByRole('button', { name: '설정 적용', exact: true }).click();
  const active = await wait(async () => {
    const state = await (await administrator.request.get(base + '/api/admin/agents/analyze')).json();
    return state.ready_replicas === 2 && state;
  });
  assert.equal(new Set(active.instances.filter(i => i.state === 'ready').map(i => i.pid)).size, 2);
  await page.getByText('목표 2개 · 준비 2개 · 마무리 중 0개', { exact: true }).waitFor();
  const viewportResults = [];
  for (const [name, width, height] of [['pc', 1920, 1080], ['cover', 416, 657], ['unfolded', 816, 616]]) {
    await page.setViewportSize({ width, height });
    await page.getByRole('heading', { name: '운영 관리', exact: true }).scrollIntoViewIfNeeded();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
    assert.equal(overflow, false, name + ' document overflow');
    await page.screenshot({ path: evidence + '/' + name + '-agent-operations.png', fullPage: true });
    viewportResults.push({ name, width, height, overflow });
  }
  await page.setViewportSize({ width: 1920, height: 1080 });
  const identity = randomUUID().replaceAll('-', '');
  const definition = { catalog_version: 1, revision: 0, name: '관리자 제공 분석', inputs: { video: 'video' }, nodes: [{ id: 'analyze', type: 'analyze', position: { x: 300, y: 50 }, options: {} }], edges: [{ id: 'source', source: { node: '$input', port: 'video' }, target: { node: 'analyze', port: 'video' } }] };
  const saved = await administrator.request.put(base + '/api/settings/workflow-definitions/' + identity, { data: definition, headers: { 'X-CSRF-Token': csrf } });
  assert.equal(saved.status(), 200);
  assert.equal((await post('/accounts', { username: 'fleet-ordinary', password })).status(), 201);
  const ordinary = await makeContext();
  const userLogin = await ordinary.request.post(base + '/api/auth/login', { data: { username: 'fleet-ordinary', password } });
  assert.equal(userLogin.status(), 200);
  const userPage = await ordinary.newPage();
  userPage.on('pageerror', error => errors.push(error.message));
  const requestedAdminPaths = [];
  userPage.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith('/api/admin/') || path.startsWith('/api/settings/')) requestedAdminPaths.push(path);
  });
  await userPage.goto(base + '/#/jobs');
  await userPage.getByRole('navigation', { name: '주 메뉴', exact: true }).waitFor();
  const menus = await userPage.getByRole('navigation', { name: '주 메뉴', exact: true }).getByRole('link').allTextContents();
  assert.deepEqual(menus, ['작업', '원본']);
  const blockedRoutes = ['agents/analyze', 'workflows', 'serving', 'settings', 'account'];
  for (const route of blockedRoutes) {
    await userPage.goto(base + '/#/' + route);
    await userPage.getByText('관리자만 이용할 수 있는 화면입니다.', { exact: true }).waitFor();
  }
  assert.deepEqual(requestedAdminPaths, []);
  assert.equal((await ordinary.request.get(base + '/api/admin/agents/analyze')).status(), 403);
  await userPage.goto(base + '/#/');
  await userPage.getByText('등록된 원본 영상이 없습니다.', { exact: true }).waitFor();
  await userPage.locator('input[type=file]').first().setInputFiles(process.env.MIDEAGENT_TEST_MOVIE);
  const source = await wait(async () => (await (await ordinary.request.get(base + '/api/videos')).json()).videos[0]);
  await userPage.goto(base + '/#/start');
  await userPage.getByLabel('원본', { exact: true }).selectOption(source.asset_id);
  await userPage.getByLabel('워크플로우', { exact: true }).selectOption(identity);
  await userPage.getByRole('button', { name: '실행 전 확인', exact: true }).click();
  await userPage.getByRole('button', { name: '작업 생성', exact: true }).click();
  await userPage.waitForURL(/#\/jobs\/[a-f0-9]{32}$/);
  const jobId = userPage.url().split('/jobs/')[1];
  await userPage.getByRole('button', { name: '실행 계획 확인', exact: true }).click();
  await userPage.getByRole('button', { name: '계획 동의 저장', exact: true }).click();
  await userPage.getByRole('button', { name: '실행 요청', exact: true }).click();
  const completed = await wait(async () => {
    const state = await (await ordinary.request.get(base + '/api/renewal/jobs/' + jobId)).json();
    return state.status === 'completed' && state;
  });
  assert.equal(completed.runs[0].result.status, 'completed');
  assert(completed.runs[0].agent_instance_id);
  assert.deepEqual(requestedAdminPaths, []);
  await page.reload();
  await page.getByLabel('에이전트 활성화', { exact: true }).uncheck();
  await page.getByRole('button', { name: '설정 적용', exact: true }).click();
  const stopped = await wait(async () => {
    const state = await (await administrator.request.get(base + '/api/admin/agents/analyze')).json();
    return state.state === 'stopped' && state;
  });
  assert.equal(stopped.ready_replicas, 0);
  assert(stopped.instances.every(instance => instance.state === 'stopped'));
  await page.goto(base + '/#/agents/faceswap');
  await page.getByRole('heading', { name: '운영 관리', exact: true }).waitFor();
  await wait(() => page.getByLabel('에이전트 활성화', { exact: true }).isDisabled());
  assert.deepEqual(errors, []);
  await writeFile(evidence + '/fleet-browser.json', JSON.stringify({ admin_instances: active.instances, ordinary_menus: menus, blocked_routes: blockedRoutes, admin_requests_from_user_page: requestedAdminPaths, job_status: completed.status, job_instance: completed.runs[0].agent_instance_id, stopped_state: stopped.state, viewports: viewportResults, browser_errors: errors }, null, 2));
  console.log('PASS: actual admin start/scale/stop, ordinary menus/route guards and persisted CPU job through production UI');
} finally {
  for (const context of contexts) await context.close();
  await browser.close();
}
