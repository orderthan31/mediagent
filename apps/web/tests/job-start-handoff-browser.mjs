// OFFLINE production-route gate. All HTTP is intercepted; no operating service or inference.
// Run only after VITE_RENEWAL_BACKEND=1 npm run build. Evidence binds exact dist hashes.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { chromium, expect } from '@playwright/test';
const artifact =
  process.env.MIDEAGENT_START_TEST_ARTIFACT ||
  fs.mkdtempSync(path.join(process.env.TMPDIR || '/root/.hermes/cache/scratch', 'start-browser-'));
fs.mkdirSync(artifact, { recursive: true });
const dist = path.resolve('dist');
const html = fs.readFileSync(path.join(dist, 'index.html'), 'utf8');
const assets = [...html.matchAll(/(?:src|href)="(\/assets\/[^\"]+)"/g)].map((m) => m[1]);
assert.ok(assets.some((file) => file.endsWith('.js')));
const manifest = Object.fromEntries(
  ['index.html', ...assets.map((file) => file.slice(1))].map((file) => [
    file,
    createHash('sha256')
      .update(fs.readFileSync(path.join(dist, file)))
      .digest('hex'),
  ]),
);
fs.writeFileSync(
  path.join(artifact, 'routed-dist-manifest.json'),
  JSON.stringify(manifest, null, 2),
);
const id = '1'.repeat(32),
  receiptId = '2'.repeat(32),
  video = '3'.repeat(32),
  workflow = '4'.repeat(32);
const base = '/renewal/jobs/' + id;
const definition = {
  id: workflow,
  name: 'literal saved workflow',
  catalog_version: 2,
  revision: 7,
  inputs: { video: 'video' },
  nodes: [
    {
      id: 'speech',
      type: 'transcription_agent',
      position: { x: 280, y: 80 },
      options: { source_language: 'auto', max_model_calls: 'auto' },
    },
  ],
  edges: [],
};
const catalog = [
  {
    id: 'transcription_agent',
    label: '전사 에이전트',
    inputs: { video: 'video' },
    outputs: { transcript: 'transcript' },
    options: { source_language: ['auto', 'en'], max_model_calls: ['auto', '1', '128'] },
  },
];
const job = {
  id,
  ticket_number: 42,
  revision: 9,
  status: 'draft',
  parent_id: null,
  access: { can_manage: true },
  snapshot: { asset: { asset_id: video, original_filename: 'literal original.mp4' }, definition },
  runs: [],
  reviews: [],
};
let fixtureSerial = 0;
const fixture = async (
  browser,
  {
    width = 1440,
    direct = false,
    lost = false,
    savedLost = false,
    role = 'admin',
    canManage = true,
    dto = true,
    status404 = false,
    storageDenied = false,
    busy = false,
  } = {},
) => {
  const traceId = ++fixtureSerial;
  const context = await browser.newContext({ offline: true, viewport: { width, height: 900 } });
  if (storageDenied) {
    await context.addInitScript(() => {
      Object.defineProperty(window, 'sessionStorage', {
        get() {
          throw new Error('fixture storage denied');
        },
      });
    });
  }
  const calls = [],
    errors = [],
    gates = new Map();
  let accepted = false,
    realJob = false,
    state = 'queued',
    saved = null;
  let fault = '',
    foreign = false,
    postForeign = false,
    holdJob = false,
    holdStatus = false;
  const receipt = () => ({
    id: receiptId,
    job_id: realJob ? id : null,
    state,
    start_request: {
      id: receiptId,
      state,
      ...(['failed', 'blocked'].includes(state) ? { code: 'literal_source_failure' } : {}),
    },
  });
  await context.route('**/*', async (route) => {
    const req = route.request(),
      url = new URL(req.url());
    const reply = (value, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) });
    if (url.origin !== 'https://handoff.invalid') {
      errors.push('external ' + url.href);
      return route.abort();
    }
    if (url.pathname === '/') {
      return route.fulfill({ contentType: 'text/html', body: html });
    }
    if (assets.includes(url.pathname)) {
      return route.fulfill({
        contentType: url.pathname.endsWith('.js') ? 'text/javascript' : 'text/css',
        body: fs.readFileSync(path.join(dist, url.pathname.slice(1))),
      });
    }
    if (
      /^\/fonts\/hangyeol\/Pretendard-(?:Bold|Regular|SemiBold|Medium)\.woff2$/.test(url.pathname)
    ) {
      return route.fulfill({
        contentType: 'font/woff2',
        body: fs.readFileSync(path.join(dist, url.pathname.slice(1))),
      });
    }
    if (url.pathname === '/favicon.ico') {
      return route.fulfill({ status: 204 });
    }
    const p = url.pathname.replace(/^\/api/, '');
    calls.push({
      path: p,
      query: url.search,
      method: req.method(),
      body: req.postDataJSON(),
      headers: req.headers(),
    });
    if (p === '/auth/session') {
      return reply({
        enabled: true,
        user: { id: 'a'.repeat(32), username: 'offline', role },
        csrf_token: 'offline-csrf',
      });
    }
    if (p === '/capabilities') {
      return reply({ features: ['verified_uploads'] });
    }
    if (p === '/videos') {
      return reply({
        videos: [
          {
            asset_id: video,
            original_filename: 'literal original.mp4',
            size_bytes: 123,
            provenance: { kind: 'original' },
          },
        ],
      });
    }
    if (p === '/jobs') {
      return reply({ jobs: [] });
    }
    if (p === '/video-uploads') {
      return reply({ uploads: [] });
    }
    if (p === '/work-entry/workflows') {
      return reply({ definitions: [definition] });
    }
    if (p === '/work-entry/catalog') {
      if (fault === 'catalog') {
        return reply({ detail: 'catalog unavailable' }, 500);
      }
      return reply({ nodes: catalog });
    }
    if (p === '/work-entry/workflows/' + workflow) {
      return reply(definition);
    }
    if (p === '/work-entry/inspect') {
      return reply({
        supported: true,
        model_ready: true,
        definition_revision: 7,
        summary: [],
        reasons: [],
      });
    }
    if (p === '/work-entry/preview') {
      return reply({ token: 'immutable-preview', paid_roles: ['translate'], notice: '' });
    }
    if (p === '/work-entry/create-and-start') {
      gates.set('create', async () => {
        accepted = true;
        return busy
          ? reply({ code: 'job_busy', detail: 'literal_start_busy' }, 409)
          : lost
            ? route.abort('failed')
            : reply(receipt(), 202);
      });
      return;
    }
    if (p === '/work-entry/start-requests') {
      return reply({ requests: accepted ? [receipt()] : [] });
    }
    if (
      p === '/work-entry/start-requests/by-request' ||
      p === '/work-entry/start-requests/' + receiptId
    ) {
      if (!accepted) {
        return reply({ detail: 'not_found' }, 404);
      }
      if (p.endsWith('/by-request')) {
        assert.equal(
          url.searchParams.get('request_id'),
          calls.find((c) => c.path === '/work-entry/create-and-start')?.body.request_id,
        );
      }
      return reply(receipt());
    }
    if (p === base) {
      if (fault === 'job') {
        return reply({ detail: 'job unavailable' }, 500);
      }
      const payload = {
        ...job,
        id: foreign ? 'f'.repeat(32) : id,
        status: realJob ? 'running' : 'draft',
        access: { can_manage: canManage },
        ...(dto ? { start_request: saved } : {}),
      };
      if (holdJob) {
        holdJob = false;
        gates.set('job', () => reply(payload));
        return;
      }
      return reply(payload);
    }
    if (p === base + '/start-request') {
      if (req.method() === 'GET') {
        if (holdStatus) {
          holdStatus = false;
          const payload = { id, job_id: id, start_request: saved };
          gates.set('status', () => reply(payload));
          return;
        }
        return reply(
          status404 ? { detail: 'status unavailable' } : { id, job_id: id, start_request: saved },
          status404 ? 404 : 200,
        );
      }
      gates.set('saved', async () => {
        saved = { id: receiptId, state };
        return busy
          ? reply({ code: 'job_busy', detail: 'literal_start_busy' }, 409)
          : savedLost
            ? route.abort('failed')
            : reply({ id, job_id: postForeign ? 'f'.repeat(32) : id, start_request: saved }, 202);
      });
      return;
    }
    errors.push('unexpected ' + req.method() + ' ' + req.url());
    return route.abort();
  });
  const page = await context.newPage();
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(
    'https://handoff.invalid/' +
      (direct ? '#/jobs/' + id : '#/start?target=' + video + '&workflow=' + workflow),
  );
  const release = async (stage) => {
    await expect.poll(() => gates.has(stage)).toBe(true);
    const fn = gates.get(stage);
    gates.delete(stage);
    await fn();
  };
  const clickStart = async (target = page) => {
    const button = target.getByRole('button', { name: '작업 시작', exact: true });
    await expect(button).toBeEnabled();
    await button.evaluate((el) => {
      el.click();
      el.click();
    });
  };
  const mutations = () =>
    calls.filter(
      (c) =>
        c.method === 'POST' && !['/work-entry/inspect', '/work-entry/preview'].includes(c.path),
    );
  const verify = () => {
    fs.writeFileSync(
      path.join(artifact, `routed-trace-${traceId}-${width}.json`),
      JSON.stringify(
        { width, direct, lost, savedLost, role, dto, status404, storageDenied, calls, errors },
        null,
        2,
      ),
    );
    assert.ok(
      !calls.some((c) => /\/(prepare-start|plan|confirm|admit|run)$/.test(c.path)),
      'browser must never orchestrate server start',
    );
    assert.deepEqual(errors, []);
  };
  return {
    page,
    context,
    calls,
    errors,
    release,
    clickStart,
    mutations,
    verify,
    holdNextJob: () => {
      holdJob = true;
    },
    holdNextStatus: () => {
      holdStatus = true;
    },
    clearSaved: () => {
      saved = null;
    },
    hasGate: (name) => gates.has(name),
    setFault: (value) => {
      fault = value;
    },
    setForeign: () => {
      foreign = true;
    },
    setPostForeign: () => {
      postForeign = true;
    },
    setState: (value) => {
      state = value;
    },
    materialize: () => {
      realJob = true;
    },
    seed: (value = 'queued') => {
      accepted = true;
      state = value;
    },
    seedSaved: (value) => {
      saved = { id: receiptId, state: value };
    },
  };
};
for (const dto of [true, false]) {
  test(`authority regression: older ${dto ? 'inline' : 'wrapper'} presence after newer null`, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
      const f = await fixture(browser, { direct: true, dto });
      const start = f.page.getByRole('button', { name: '작업 시작', exact: true });
      await expect(start).toBeEnabled();
      f.seedSaved('queued');
      if (dto) {
        f.holdNextJob();
      } else {
        f.holdNextStatus();
      }
      const gate = dto ? 'job' : 'status';
      await expect.poll(() => f.hasGate(gate), { timeout: 6500 }).toBe(true);
      await expect(start).toBeDisabled();
      f.clearSaved();
      await f.page.getByRole('button', { name: '새로고침', exact: true }).click();
      await expect(start).toBeEnabled(); // Current explicit null is genuine positive authority.
      assert.equal(f.mutations().length, 0);
      await f.release(gate);
      await expect(f.page.locator('[data-start-stage]')).toHaveText('시작 대기');
      await expect(start).toBeDisabled();
      await start.evaluate((el) => el.click());
      await f.page.waitForTimeout(100);
      assert.equal(f.mutations().length, 0);
      f.verify();
      await f.context.close();
    } finally {
      await browser.close();
    }
  });
}
for (const scenario of [
  'refresh queued',
  'refresh null',
  'job failure',
  'catalog failure',
  'foreign job',
  'foreign poll',
  'refresh failure',
  'stale null',
  'foreign POST',
]) {
  test('authority regression: ' + scenario, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
      const f = await fixture(browser, { direct: true });
      const start = f.page.getByRole('button', { name: '작업 시작', exact: true });
      await expect(start).toBeEnabled();
      assert.equal(await f.page.evaluate(() => sessionStorage.length), 0);
      if (scenario === 'stale null') {
        f.holdNextJob();
        await expect.poll(() => f.hasGate('job'), { timeout: 6500 }).toBe(true);
        await expect(start).toBeDisabled();
        f.seedSaved('queued');
        await f.page.getByRole('button', { name: '새로고침', exact: true }).click();
        await expect(f.page.locator('[data-start-stage]')).toHaveText('시작 대기');
        await f.release('job');
        await f.page.waitForTimeout(200);
        await expect(f.page.locator('[data-start-stage]')).toHaveText('시작 대기');
        await expect(start).toBeDisabled();
        assert.equal(f.mutations().length, 0);
      } else if (scenario === 'foreign POST') {
        f.setPostForeign();
        await f.clickStart();
        await f.release('saved');
        await expect(
          f.page.getByRole('alert').filter({ hasText: '시작 접수 상태를 확인하지 못했습니다.' }),
        ).toBeVisible();
        await expect(start).toBeDisabled();
        await f.page.reload();
        await expect(start).toBeDisabled();
        assert.equal(f.mutations().length, 1);
      } else {
        if (scenario === 'refresh queued') {
          f.seedSaved('queued');
        }
        if (scenario === 'foreign job' || scenario === 'foreign poll') {
          f.setForeign();
        }
        if (scenario === 'refresh failure') {
          f.setFault('job');
          await f.page.getByRole('button', { name: '새로고침', exact: true }).click();
          await expect(f.page.getByRole('button', { name: '새로고침', exact: true })).toBeEnabled();
        } else if (scenario === 'foreign poll') {
          await expect(f.page.getByRole('alert')).toContainText(
            '시작 접수 상태를 확인하지 못했습니다.',
            { timeout: 6500 },
          );
        } else if (scenario.endsWith('failure')) {
          f.setFault(scenario.split(' ')[0]);
          await expect(f.page.getByRole('alert').filter({ hasText: 'unavailable' })).toBeVisible({
            timeout: 6500,
          });
        } else {
          await f.page.getByRole('button', { name: '새로고침', exact: true }).click();
          await expect(f.page.getByRole('button', { name: '새로고침', exact: true })).toBeEnabled();
        }
        if (scenario === 'refresh null') {
          await expect(start).toBeEnabled();
          await f.clickStart();
          await f.release('saved');
          await expect(f.page.locator('[data-start-stage]')).toHaveText('시작 대기');
          assert.equal(f.mutations().length, 1);
        } else {
          await expect(start).toBeDisabled({ timeout: 700 });
          if (scenario === 'refresh queued') {
            await expect(f.page.locator('[data-start-stage]')).toHaveText('시작 대기');
          }
          assert.equal(f.mutations().length, 0);
        }
      }
      f.verify();
      await f.context.close();
    } finally {
      await browser.close();
    }
  });
}
for (const width of [1440, 390]) {
  test(`routed ${width}: single intake, prompt pre-job route, exact body, new-tab discovery, real job only`, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
      const f = await fixture(browser, { width });
      await f.clickStart();
      await expect(f.page.locator('.start-request-progress')).toBeVisible();
      await expect.poll(() => f.calls.some((c) => c.path.endsWith('/by-request'))).toBe(true);
      await expect(f.page.locator('.job-detail')).toHaveCount(0);
      await expect(f.page.getByRole('alert')).toContainText('접수 확인 불가');
      assert.equal(f.mutations().length, 1);
      const body = f.mutations()[0].body;
      assert.deepEqual(body, {
        asset_id: video,
        recovery_enabled: false,
        definition_id: workflow,
        definition_revision: 7,
        options: { video_description: '', branch_choices: {} },
        request_id: body.request_id,
        token: 'immutable-preview',
        paid_confirmed: true,
      });
      assert.equal(f.mutations()[0].headers['x-csrf-token'], 'offline-csrf');
      await f.release('create');
      await expect(f.page).toHaveURL(new RegExp('#/start-requests/' + receiptId + '$'));
      await expect(f.page.locator('[data-request-state]')).toHaveText('시작 대기');
      await f.page.screenshot({
        path: path.join(artifact, `receipt-${width}.png`),
        fullPage: true,
      });
      assert.ok(
        await f.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      );
      const tab = await f.context.newPage();
      await tab.goto('https://handoff.invalid/#/jobs');
      await expect(tab.getByRole('link', { name: '시작 대기', exact: true })).toBeVisible();
      assert.equal(
        await tab.evaluate(() => sessionStorage.length),
        0,
        'discovery cannot depend on submitting tab storage',
      );
      await tab.screenshot({
        path: path.join(artifact, `requests-jobs-${width}.png`),
        fullPage: true,
      });
      await tab.getByRole('link', { name: '시작 대기', exact: true }).click();
      await expect(tab.locator('.start-request-progress')).toBeVisible();
      await f.page.close();
      f.materialize();
      await expect(tab.locator('.job-detail-toolbar')).toContainText('처리 중', { timeout: 5000 });
      await expect(tab).toHaveURL(new RegExp('#/jobs/' + id + '$'));
      await expect(tab.locator('.workflow-graph')).toBeVisible();
      await expect(tab.locator('[data-node-id="speech"]')).toBeVisible();
      assert.equal(definition.nodes[0].options.max_model_calls, 'auto');
      await tab.screenshot({ path: path.join(artifact, `real-job-${width}.png`), fullPage: true });
      await tab.goto('https://handoff.invalid/#/jobs');
      await expect(tab.locator('[aria-label="시작 요청"] a')).toHaveCount(0);
      assert.equal(f.mutations().length, 1);
      f.verify();
      await f.context.close();
    } finally {
      await browser.close();
    }
  });
  test(`routed ${width}: lost create acknowledgement uses original nonce, reload and selection change never repost`, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
      const f = await fixture(browser, { width, lost: true });
      await f.clickStart();
      await f.release('create');
      await expect(f.page.locator('[data-request-state]')).toHaveText('시작 대기', {
        timeout: 6000,
      });
      const nonce = f.mutations()[0].body.request_id;
      await f.page.reload();
      await expect(f.page.locator('[data-request-state]')).toHaveText('시작 대기');
      await f.page.goto(
        'https://handoff.invalid/#/start?target=' + 'b'.repeat(32) + '&workflow=' + workflow,
      );
      await expect(f.page.locator('.start-request-progress')).toBeVisible();
      assert.equal(f.mutations().length, 1);
      const lookups = f.calls.filter((c) => c.path.endsWith('/by-request'));
      assert.ok(lookups.length >= 2);
      assert.ok(lookups.every((c) => c.query === '?request_id=' + encodeURIComponent(nonce)));
      const stored = await f.page.evaluate(() => Object.values(sessionStorage).join(''));
      assert.doesNotMatch(stored, /asset_id|options|transcript|token|paid_confirmed/);
      f.verify();
      await f.context.close();
    } finally {
      await browser.close();
    }
  });
  test(`routed ${width}: saved Start is one POST; mount, reload, poll and uncertain response are read-only`, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
      const f = await fixture(browser, { width, direct: true, savedLost: true, dto: false });
      await expect(f.page.getByRole('button', { name: '작업 시작', exact: true })).toBeEnabled();
      await f.page.reload();
      await expect(f.page.getByRole('button', { name: '작업 시작', exact: true })).toBeEnabled();
      assert.equal(f.mutations().length, 0);
      await f.clickStart();
      await expect(f.page.locator('[data-start-stage]')).toHaveText('시작 중…');
      await f.release('saved');
      await expect(f.page.getByRole('button', { name: '작업 시작', exact: true })).toBeDisabled();
      await f.page.reload();
      await expect(f.page.locator('[data-start-stage]')).toHaveText('시작 대기');
      await f.page.getByRole('button', { name: '새로고침', exact: true }).click();
      await expect(f.page.getByRole('button', { name: '작업 시작', exact: true })).toBeDisabled();
      assert.equal(f.mutations().length, 1);
      assert.deepEqual(f.mutations()[0].body, {
        revision: 9,
        request_id: f.mutations()[0].body.request_id,
      });
      assert.equal(f.mutations()[0].path, base + '/start-request');
      f.verify();
      await f.context.close();
    } finally {
      await browser.close();
    }
  });
}
for (const state of ['failed', 'blocked', 'expired', 'cancelled', 'uncertain', 'unknown_state']) {
  test(
    'routed receipt: ' + state + ' never appears completed or automatically retries',
    async () => {
      const browser = await chromium.launch({ headless: true });
      try {
        const f = await fixture(browser, { role: 'user', direct: true });
        f.seed(state);
        await f.page.goto('https://handoff.invalid/#/start-requests/' + receiptId);
        await expect(f.page.locator('[data-request-state]')).toHaveAttribute(
          'data-request-state',
          state,
        );
        assert.doesNotMatch(
          await f.page.locator('.start-request-progress').innerText(),
          /완료|처리 중|접수됨/,
        );
        if (['failed', 'blocked'].includes(state)) {
          await expect(f.page.getByRole('alert')).toHaveText('literal_source_failure');
        }
        await f.page.getByRole('button', { name: '새로고침', exact: true }).click();
        await f.page.reload();
        await expect(f.page.locator('[data-request-state]')).toHaveAttribute(
          'data-request-state',
          state,
        );
        assert.equal(f.mutations().length, 0);
        f.seedSaved(state);
        await f.page.goto('https://handoff.invalid/#/jobs/' + id);
        await expect(f.page.getByRole('button', { name: '작업 시작', exact: true })).toBeDisabled();
        assert.equal(f.mutations().length, 0);
        f.verify();
        await f.context.close();
      } finally {
        await browser.close();
      }
    },
  );
}
for (const direct of [false, true]) {
  test(
    'HTTP busy response is not an automatic second start POST: ' + (direct ? 'saved' : 'generic'),
    async () => {
      const browser = await chromium.launch({ headless: true });
      try {
        const f = await fixture(browser, { direct, busy: true });
        await f.clickStart();
        await f.release(direct ? 'saved' : 'create');
        await f.page.waitForTimeout(1100);
        assert.equal(f.mutations().length, 1);
        if (direct) {
          await expect(
            f.page.getByRole('button', { name: '작업 시작', exact: true }),
          ).toBeDisabled();
        } else {
          await expect(f.page.locator('.start-request-progress')).toBeVisible();
        }
        f.verify();
        await f.context.close();
      } finally {
        await browser.close();
      }
    },
  );
}

test('initial receipt 404 reconciliation is bounded, visible and GET-only', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const f = await fixture(browser, { direct: true });
    await f.page.clock.install();
    await f.page.goto('https://handoff.invalid/#/start-requests?request_id=original%2Dnonce');
    await expect(f.page.getByRole('alert')).toContainText('접수 확인 불가');
    const lookups = () => f.calls.filter((c) => c.path.endsWith('/by-request')).length;
    for (let count = 2; count <= 6; count++) {
      await f.page.clock.runFor(2100);
      await expect.poll(lookups).toBe(count);
      await expect(f.page.getByRole('alert')).toContainText('접수 확인 불가');
    }
    await f.page.clock.runFor(20000);
    assert.equal(lookups(), 6);
    assert.equal(f.mutations().length, 0);
    f.verify();
    await f.context.close();
  } finally {
    await browser.close();
  }
});

test('storage denied: saved submission fence survives reload before acknowledgement without inventing success', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const f = await fixture(browser, { direct: true, storageDenied: true });
    await f.clickStart();
    await expect.poll(() => f.mutations().length).toBe(1);
    const nonce = f.mutations()[0].body.request_id;
    const stored = await f.page.evaluate(() => history.state);
    assert.deepEqual(stored['mideagent.pending-start.job.' + id], { request_id: nonce });
    await f.page.reload();
    await expect(f.page.locator('[data-start-stage]')).toHaveText('접수 확인 불가');
    await expect(f.page.getByRole('button', { name: '작업 시작', exact: true })).toBeDisabled();
    assert.equal(f.mutations().length, 1);
    f.verify();
    await f.context.close();
  } finally {
    await browser.close();
  }
});

test('saved status 404 is not an acknowledgement; read-only access has no Start', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const f = await fixture(browser, { direct: true, dto: false, status404: true });
    await expect(f.page.getByRole('alert')).toHaveText('status unavailable');
    await expect(f.page.getByRole('button', { name: '작업 시작', exact: true })).toBeDisabled();
    assert.equal(f.mutations().length, 0);
    f.verify();
    await f.context.close();
    const reader = await fixture(browser, { direct: true, canManage: false });
    await expect(reader.page.locator('.job-detail-toolbar')).toBeVisible();
    await expect(reader.page.getByRole('button', { name: '작업 시작', exact: true })).toHaveCount(
      0,
    );
    assert.equal(reader.mutations().length, 0);
    reader.verify();
    await reader.context.close();
  } finally {
    await browser.close();
  }
});
