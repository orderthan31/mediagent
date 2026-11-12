// Actual ordinary shell/React/production CSS. Offline response fixtures, no real queue.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

test('ordinary new-start pause/resume/order in existing execution popover at PC/390px', async () => {
  const scratch = 'C:/Users/skygg/AppData/Local/hermes/cache/scratch/mediagent-5178-parity';
  const directory = fs.mkdtempSync(path.join(scratch, 'start-queue-browser-'));
  const bundle = await build({
    stdin: {
      resolveDir: process.cwd(),
      loader: 'tsx',
      contents: `import React from 'react';import{createRoot}from'react-dom/client';import{AuthGate}from'./src/AuthGate';import{VideoWorkspace}from'./src/VideoWorkspace';import{PageTitleProvider}from'./src/PageTitle';createRoot(document.getElementById('root')).render(<AuthGate><PageTitleProvider><VideoWorkspace/></PageTitleProvider></AuthGate>);`,
    },
    bundle: true,
    write: false,
    platform: 'browser',
    format: 'iife',
    define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
    loader: { '.css': 'empty' },
  });
  const css = fs
    .readdirSync('dist/assets')
    .filter((name) => name.endsWith('.css'))
    .map((name) => fs.readFileSync(path.join('dist/assets', name), 'utf8'))
    .join('\n');
  const browser = await chromium.launch({
    channel: process.platform === 'win32' ? 'msedge' : undefined,
    headless: true,
  });
  const ids = ['1'.repeat(32), '2'.repeat(32)],
    deliveryId = '3'.repeat(32);
  const names = ['첫째 원본 literal filename.mp4', '둘째 원본 긴 파일명과 공백 preserved.mp4'];
  let state,
    getError = false,
    conflict = false,
    lost = false;
  const writes = [],
    unexpected = [],
    errors = [];
  const projection = () => ({
    ...state,
    details: state.jobs.map((id) => ({
      job_id: id,
      ticket_number: id === ids[0] ? '140' : '141',
      original_filename: names[ids.indexOf(id)],
      workflow_name: '합성 대기 작업',
      status: 'QUEUED',
      access: { can_manage: true },
    })),
    progression: 'ready',
  });
  try {
    const context = await browser.newContext({ offline: true });
    await context.route('**/*', async (route) => {
      const req = route.request(),
        url = new URL(req.url());
      if (url.origin !== 'https://start-queue.invalid') {
        unexpected.push(url.href);
        return route.abort();
      }
      if (url.pathname === '/') {
        return route.fulfill({
          contentType: 'text/html',
          body: '<!doctype html><html lang="ko"><body><div id="root"></div></body></html>',
        });
      }
      const font = url.pathname.match(
        /^\/fonts\/hangyeol\/(Pretendard-(?:Bold|Regular|SemiBold|Medium)\.woff2)$/,
      )?.[1];
      if (font) {
        return route.fulfill({
          contentType: 'font/woff2',
          body: fs.readFileSync(path.join('public/fonts/hangyeol', font)),
        });
      }
      const json = (value, status = 200) =>
        route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) });
      if (req.method() === 'GET') {
        if (url.pathname === '/api/auth/session') {
          return json({
            enabled: true,
            user: { id: 'a'.repeat(32), username: 'ordinary', role: 'user' },
            csrf_token: 'csrf',
          });
        }
        if (url.pathname === '/api/capabilities') {
          return json({ features: ['verified_uploads'] });
        }
        if (url.pathname === '/api/videos') {
          return json({ videos: [] });
        }
        if (url.pathname === '/api/jobs') {
          return json({ jobs: [] });
        }
        if (url.pathname === '/api/video-uploads') {
          return json({ uploads: [] });
        }
        if (url.pathname === '/api/queue') {
          return getError ? json({ detail: '합성 대기열 조회 실패' }, 503) : json(projection());
        }
        if (url.pathname === '/api/renewal/execution-waiting') {
          return json({
            jobs: [
              {
                job_id: deliveryId,
                ticket_number: '142',
                status: 'waiting',
                original_filename: '이미 승인된 전달.mp4',
                workflow_name: '전달 작업',
                access: { can_manage: false },
                deliveries: [{ phase: 'unknown', run_status: 'waiting', count: 1 }],
              },
            ],
            has_more: false,
            limit: 100,
          });
        }
      }
      if (url.pathname === '/api/queue' && req.method() === 'PATCH') {
        assert.equal(req.headers()['x-csrf-token'], 'csrf');
        const body = req.postDataJSON();
        writes.push(body);
        assert.ok(Object.keys(body).every((key) => ['revision', 'paused', 'order'].includes(key)));
        assert.equal(body.revision, state.revision);
        if (conflict) {
          conflict = false;
          state.revision++;
          return json({ detail: '대기열이 바뀌었습니다. 다시 확인하세요.' }, 409);
        }
        state = { ...state, ...body, revision: state.revision + 1 };
        if (body.order) {
          state.jobs = [...body.order, ...state.jobs.filter((id) => !body.order.includes(id))];
        }
        if (lost) {
          lost = false;
          return route.abort('connectionreset');
        }
        return json(projection());
      }
      unexpected.push(`${req.method()} ${url.pathname}`);
      return route.abort();
    });
    for (const width of [1440, 390]) {
      state = { revision: 0, paused: false, order: [], jobs: [...ids] };
      getError = false;
      const page = await context.newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await page.goto('https://start-queue.invalid/#/jobs');
      await page.addStyleTag({ content: css });
      await page.addScriptTag({ content: bundle.outputFiles[0].text });
      await page.getByRole('button', { name: '실행 관리', exact: true }).click();
      const pause = page.getByRole('button', { name: '새 작업 시작 일시정지', exact: true });
      await expect(pause).toBeVisible();
      const queue = page.getByRole('region', { name: '새 작업 시작 대기열', exact: true });
      await expect(queue.getByRole('link', { name: names[0], exact: true })).toBeVisible();
      await expect(queue).not.toContainText('이미 승인된 전달.mp4');
      const delivery = page.getByRole('region', { name: '전달 현황', exact: true });
      await expect(delivery).toContainText('전송 결과 확인 필요');
      await pause.click({ trial: true });
      await pause.click();
      await expect(
        queue.getByRole('button', { name: '작업 시작 재개', exact: true }),
      ).toBeEnabled();
      await expect(queue).toContainText('진행 중인 작업은 계속 처리됩니다.');
      await queue.getByRole('button', { name: '작업 141 맨 앞으로', exact: true }).click();
      await expect(queue.locator('.start-queue-items > li').first()).toContainText(names[1]);
      await queue.getByRole('button', { name: '작업 141 아래로 이동', exact: true }).click();
      await expect(queue.locator('.start-queue-items > li').first()).toContainText(names[0]);
      await queue.getByRole('button', { name: '작업 141 위로 이동', exact: true }).click();
      await expect(queue.locator('.start-queue-items > li').first()).toContainText(names[1]);
      const before = writes.length;
      conflict = true;
      await queue.getByRole('button', { name: '작업 시작 재개', exact: true }).click();
      await expect(queue.getByRole('alert')).toContainText('대기열이 바뀌었습니다');
      assert.equal(writes.length, before + 1);
      await queue.getByRole('button', { name: '대기열 다시 확인', exact: true }).click();
      await expect(queue.getByRole('alert')).toHaveCount(0);
      lost = true;
      const lostBefore = writes.length;
      await queue.getByRole('button', { name: '작업 시작 재개', exact: true }).click();
      await expect(queue.getByRole('alert')).toBeVisible();
      await expect(pause).toBeDisabled();
      assert.equal(writes.length, lostBefore + 1);
      assert.equal(state.paused, false);
      await queue.getByRole('button', { name: '대기열 다시 확인', exact: true }).click();
      await expect(pause).toBeEnabled();
      getError = true;
      await queue.getByRole('button', { name: '대기열 다시 확인', exact: true }).click();
      await expect(queue.getByRole('alert')).toContainText('조회 실패');
      await expect(queue).toContainText('마지막 확인');
      await expect(queue.getByText('시작 대기 중인 작업이 없습니다.', { exact: true })).toHaveCount(
        0,
      );
      await expect(pause).toBeDisabled();
      getError = false;
      await queue.getByRole('button', { name: '대기열 다시 확인', exact: true }).click();
      await expect(pause).toBeEnabled();
      const box = await queue.boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= width);
      const file = queue.getByRole('link', { name: names[1], exact: true });
      assert.ok((await file.evaluate((el) => parseFloat(getComputedStyle(el).fontSize))) >= 14);
      await page.screenshot({ path: path.join(directory, `${width}-queue.png`) });
      await expect(delivery).toContainText('이미 승인된 전달.mp4');
      await delivery.scrollIntoViewIfNeeded();
      await expect(delivery.getByRole('link', { name: '상세 보기', exact: true })).toBeVisible();
      await delivery.getByRole('link', { name: '상세 보기', exact: true }).click({ trial: true });
      assert.ok(
        (await page.locator('#execution-controls').evaluate((element) => element.scrollTop)) > 0,
      );
      await page.screenshot({ path: path.join(directory, `${width}-delivery.png`) });
      await page.getByRole('button', { name: '실행 관리 닫기', exact: true }).click();
      await page.getByRole('button', { name: '실행 관리', exact: true }).click();
      await expect(queue).toContainText(names[1]);
      await page.close();
    }
    assert.deepEqual(unexpected, []);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});
