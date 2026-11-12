// OFFLINE accepted-receipt fixtures; actual RenewalJobDetail poll + AuthGate + CSS.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';
const scratch = 'C:/Users/skygg/AppData/Local/hermes/cache/scratch/mediagent-5178-parity';
const jobId = 'a'.repeat(32),
  reviewId = 'b'.repeat(32),
  runId = 'c'.repeat(32),
  targetId = 'd'.repeat(32);
const graph = {
  id: 'fixture-face',
  catalog_version: 2,
  revision: 1,
  name: 'OFFLINE 얼굴 합성',
  input_profile: 'face_workflow_v1',
  inputs: { photo: 'image' },
  nodes: [{ id: 'face', type: 'faceswap_agent', position: { x: 0, y: 0 }, options: {} }],
  edges: [],
};
const spec = {
  id: 'faceswap_agent',
  label: '얼굴 합성 에이전트',
  kind: 'agent',
  inputs: {},
  outputs: { media: 'media_task', video: 'video', report: 'validation_report' },
  options: {},
};
const initial = {
  id: reviewId,
  node_run_id: runId,
  revision: 1,
  status: 'draft',
  draft: { source_position: null, face_position: null },
  contract: {
    kind: 'face_select',
    source: { faces: [{ position: 0 }, { position: 1 }] },
    reference: { faces: [{ position: 0 }, { position: 1 }] },
  },
};
const png = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN1cAAAAASUVORK5CYII=',
  'base64',
);
const clone = (v) => JSON.parse(JSON.stringify(v));
test('actual JobDetail polling preserves a new unsaved face choice after local save PC1440/390 (OFFLINE)', async () => {
  const dir = fs.mkdtempSync(path.join(scratch, 'face-review-job-fix-'));
  const js = await build({
    stdin: {
      resolveDir: process.cwd(),
      loader: 'tsx',
      contents: `import React from 'react';import{createRoot}from'react-dom/client';import{AuthGate}from'./src/AuthGate';import{PageTitleProvider}from'./src/PageTitle';import{RenewalJobDetail}from'./src/RenewalJobDetail';import{Theme}from'./src/hangyeol/foundation/theme';createRoot(document.getElementById('root')).render(<AuthGate><PageTitleProvider><Theme mode="light" palette="Indigo" className="workspace-theme"><div className="video-workspace renewed-workspace ui02-workspace"><RenewalJobDetail id="${jobId}"/></div></Theme></PageTitleProvider></AuthGate>);`,
    },
    bundle: true,
    write: false,
    format: 'iife',
    platform: 'browser',
    define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
    loader: { '.css': 'empty' },
  });
  const css = fs
    .readdirSync('dist/assets')
    .filter((n) => n.endsWith('.css'))
    .map((n) => fs.readFileSync(path.join('dist/assets', n), 'utf8'))
    .join('\n');
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const posts = [],
    gets = [],
    images = [],
    unexpected = [],
    errors = [];
  let server = clone(initial),
    polled = clone(initial),
    pollLabel = 1,
    manage = true,
    jobStatus = 'review_required',
    lostReply = false,
    phase = 'select';
  const roles = [
    'face_analyze_source',
    'face_analyze_reference',
    'face_select',
    'face_preview',
    'face_confirm_preview',
    'face_render',
    'validate_video',
  ];
  const labels = [
    '사진 인물 분석',
    '영상 인물 분석',
    '합성할 인물 선택',
    '합성 미리보기',
    '미리보기 확인',
    '얼굴 합성',
    '영상 확인',
  ];
  const state = () => {
    const frontier = phase === 'select' ? 2 : 4;
    const tools = roles.map((role, i) => ({
      node_id: 'face__' + role,
      role,
      label: labels[i],
      state: i < frontier ? 'completed' : i === frontier ? 'review_required' : 'waiting',
      reason: '',
      run_id: i === frontier ? runId : i < frontier ? String(i + 1).repeat(32) : null,
    }));
    const runs = tools
      .filter((t) => t.run_id)
      .map((tool, i) => ({
        id: tool.run_id,
        node_id: tool.node_id,
        node_type: tool.role,
        status: tool.state,
        inputs: {},
        options: {},
        result:
          tool.state === 'completed'
            ? {
                outputs: {
                  [i < 2 ? 'analysis' : i === 2 ? 'session' : 'preview']: {
                    storage_key: 'blobs/' + String(i + 1).repeat(64),
                    sha256: String(i + 1).repeat(64),
                    bytes: 80,
                    type: i < 2 ? 'face_analysis' : i === 2 ? 'face_session' : 'face_preview',
                  },
                },
              }
            : null,
      }));
    return {
      id: jobId,
      ticket_number: 91,
      revision: pollLabel,
      status: jobStatus,
      parent_id: null,
      access: { can_manage: manage },
      executed_by: 'f'.repeat(32),
      snapshot: {
        asset: {
          asset_id: targetId,
          original_filename: 'OFFLINE target unchanged.mp4',
          uploaded_by: 'e'.repeat(32),
        },
        definition: graph,
        tool_definition: {
          ...graph,
          catalog_version: 1,
          nodes: roles.map((role, i) => ({
            id: 'face__' + role,
            type: role,
            position: { x: i * 100, y: 0 },
            options: {},
          })),
        },
        options: {},
      },
      runs,
      reviews: [clone(polled)],
      agent_workflow: {
        definition: graph,
        legacy_projection: false,
        edges: {},
        nodes: [
          {
            id: 'face',
            type: 'faceswap_agent',
            label: '얼굴 합성 에이전트',
            state: 'review_required',
            status_label: phase === 'select' ? '인물 선택 대기' : '미리보기 확인 대기',
            reason: 'OFFLINE parent poll ' + pollLabel,
            selected_tool_id: 'face__' + roles[frontier],
            tools,
            outputs: [],
          },
        ],
      },
    };
  };
  try {
    const context = await browser.newContext({ offline: true });
    await context.addInitScript(() => {
      const nativeSet = window.setTimeout.bind(window),
        nativeClear = window.clearTimeout.bind(window);
      let number = -1;
      const scheduled = new Map();
      window.setTimeout = (fn, delay, ...args) => {
        if (delay === 4000) {
          const id = number--;
          scheduled.set(id, () => fn(...args));
          return id;
        }
        return nativeSet(fn, delay, ...args);
      };
      window.clearTimeout = (id) => {
        if (!scheduled.delete(id)) {
          nativeClear(id);
        }
      };
      window.__faceJobPoll = async () => {
        const next = scheduled.entries().next().value;
        if (!next) {
          throw new Error('no production job poll scheduled');
        }
        scheduled.delete(next[0]);
        await next[1]();
      };
    });
    await context.route('**/*', async (route) => {
      const request = route.request(),
        url = new URL(request.url()),
        json = (data, status = 200) =>
          route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
      if (url.origin !== 'https://face-review-job.invalid') {
        unexpected.push(url.href);
        return route.abort();
      }
      if (url.pathname === '/') {
        return route.fulfill({
          contentType: 'text/html',
          body: '<!doctype html><html lang="ko"><head><meta name="viewport" content="width=device-width, initial-scale=1"/></head><body><div id="root"></div></body></html>',
        });
      }
      if (url.pathname.startsWith('/fonts/hangyeol/')) {
        return route.fulfill({
          contentType: 'font/woff2',
          body: fs.readFileSync(path.join('public', url.pathname)),
        });
      }
      if (request.method() === 'GET') {
        gets.push(url.pathname);
      } else {
        posts.push({ path: url.pathname, body: request.postDataJSON() });
      }
      if (url.pathname === '/api/auth/session') {
        return json({
          enabled: true,
          user: { id: (manage ? 'f' : '8').repeat(32), username: 'OFFLINE viewer', role: 'user' },
          csrf_token: 'fixture-csrf',
        });
      }
      if (url.pathname === '/api/work-entry/catalog') {
        return json({ nodes: [spec] });
      }
      if (url.pathname === `/api/renewal/jobs/${jobId}`) {
        return json(state());
      }
      if (url.pathname === `/api/renewal/jobs/${jobId}/runs/${runId}/logs`) {
        return json({
          run_id: runId,
          node_id: 'face__face_select',
          state: 'review_required',
          has_more: false,
          shown_calls: 0,
          total_calls: 0,
          entries: [],
          console: { available: false, truncated: false, lines: [] },
        });
      }
      if (url.pathname.includes(`/reviews/${reviewId}/face-image/`)) {
        images.push(url.pathname);
        const valid =
          phase === 'preview'
            ? url.pathname.endsWith('/preview/0')
            : /\/(source|reference)\/[01]$/.test(url.pathname);
        return valid
          ? route.fulfill({ contentType: 'image/png', body: png })
          : json({ detail: 'not found' }, 404);
      }
      if (url.pathname === `/api/renewal/reviews/${reviewId}/save`) {
        const body = request.postDataJSON();
        if (!manage) {
          return json({ detail: 'not found' }, 404);
        }
        if (body.revision !== server.revision) {
          return json({ detail: 'revision conflict' }, 409);
        }
        server = { ...server, revision: server.revision + 1, draft: body.draft };
        if (lostReply) {
          lostReply = false;
          return route.abort();
        }
        return json(server);
      }
      if (url.pathname === `/api/renewal/reviews/${reviewId}/confirm`) {
        server = { ...server, status: 'confirmed' };
        polled = clone(server);
        return json(state());
      }
      unexpected.push(request.method() + ' ' + url.pathname);
      return route.abort();
    });
    const mount = async (page) => {
      await page.goto('https://face-review-job.invalid/#/jobs/' + jobId);
      await page.addStyleTag({ content: css });
      await page.addScriptTag({ content: js.outputFiles[0].text });
    };
    for (const width of [1440, 390]) {
      server = clone(initial);
      polled = clone(initial);
      pollLabel = 1;
      manage = true;
      jobStatus = 'review_required';
      phase = 'select';
      const page = await context.newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      await page.setViewportSize({ width, height: 950 });
      await mount(page);
      await expect(page.locator('[data-node-id="face"]')).toBeVisible({ timeout: 2000 });
      await page.locator('[data-node-id="face"] .workflow-node-heading').click();
      const source = page.getByRole('group', { name: '사진 인물', exact: true }),
        reference = page.getByRole('group', { name: '영상 인물', exact: true });
      await source.getByRole('radio').nth(0).check();
      await reference.getByRole('radio').nth(0).check();
      await page.getByRole('button', { name: '선택 저장', exact: true }).click();
      await expect(page.getByRole('button', { name: '인물 선택 확정', exact: true })).toBeEnabled();
      await source.getByRole('radio').nth(1).check();
      polled = clone(server);
      pollLabel = 2;
      await page.evaluate(() => window.__faceJobPoll());
      await expect(page.locator('[data-node-id="face"]')).toContainText('OFFLINE parent poll 2');
      await expect(source.getByRole('radio').nth(1)).toBeChecked();
      await expect(
        page.getByRole('button', { name: '인물 선택 확정', exact: true }),
      ).toBeDisabled();
      await expect(page.getByRole('button', { name: '선택 저장', exact: true })).toBeEnabled();
      // An older poll must not replace the acknowledged local revision 2.
      polled = clone(initial);
      pollLabel = 3;
      await page.evaluate(() => window.__faceJobPoll());
      await expect(page.locator('[data-node-id="face"]')).toContainText('OFFLINE parent poll 3');
      lostReply = true;
      const count = posts.length;
      await page.getByRole('button', { name: '선택 저장', exact: true }).click();
      await expect(page.getByRole('alert')).toBeVisible();
      assert.equal(posts.length, count + 1);
      assert.equal(posts.at(-1).body.revision, 2);
      assert.equal(posts.at(-1).body.draft.source_position, 1);
      polled = clone(server);
      await page.getByRole('button', { name: '상태 다시 불러오기', exact: true }).click();
      await expect(page.getByRole('button', { name: '인물 선택 확정', exact: true })).toBeEnabled();
      // A distinct newer server edit updates the CAS base without erasing our edit.
      await reference.getByRole('radio').nth(1).check();
      server = {
        ...server,
        revision: server.revision + 1,
        draft: { source_position: 0, face_position: 0 },
      };
      polled = clone(server);
      pollLabel = 31;
      await page.evaluate(() => window.__faceJobPoll());
      await expect(page.locator('[data-node-id="face"]')).toContainText('OFFLINE parent poll 31');
      await expect(source.getByRole('radio').nth(1)).toBeChecked();
      await expect(reference.getByRole('radio').nth(1)).toBeChecked();
      await expect(page.getByRole('alert')).toContainText('편집은 보존');
      await expect(
        page.getByRole('button', { name: '인물 선택 확정', exact: true }),
      ).toBeDisabled();
      await page.getByRole('button', { name: '선택 저장', exact: true }).click();
      assert.equal(posts.at(-1).body.revision, 4);
      await page.getByRole('button', { name: '인물 선택 확정', exact: true }).click();
      await expect(page.getByText('확정됨', { exact: true })).toBeVisible();
      await expect(source.getByRole('radio').nth(1)).toBeDisabled();
      polled = { ...clone(initial), revision: 2 };
      pollLabel = 4;
      await page.evaluate(() => window.__faceJobPoll());
      await expect(page.locator('[data-node-id="face"]')).toContainText('OFFLINE parent poll 4');
      await expect(page.getByText('확정됨', { exact: true })).toBeVisible();
      const confirmButton = page.getByRole('button', { name: '인물 선택 확정', exact: true });
      await confirmButton.scrollIntoViewIfNeeded();
      const bounds = await confirmButton.boundingBox();
      assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width + 1 && bounds.height >= 32);
      assert.ok(bounds.y >= 0 && bounds.y + bounds.height <= 951);
      assert.equal(
        await confirmButton.evaluate((button) => {
          const r = button.getBoundingClientRect();
          return button.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2));
        }),
        true,
      );
      await page.screenshot({
        path: path.join(dir, `OFFLINE-job-review-${width}.png`),
        fullPage: true,
      });
      await page.close();
      // Shared readers use the same accepted image routes, without action POSTs.
      manage = false;
      jobStatus = 'review_required';
      polled = { ...clone(initial), draft: { source_position: 0, face_position: 0 } };
      const readPage = await context.newPage();
      await readPage.setViewportSize({ width, height: 950 });
      readPage.on('pageerror', (e) => errors.push(e.message));
      const beforeRead = posts.length;
      await mount(readPage);
      await readPage.locator('[data-node-id="face"] .workflow-node-heading').click();
      const candidates = readPage.locator('.face-candidates img');
      await expect(candidates).toHaveCount(4);
      await expect
        .poll(() =>
          candidates.evaluateAll((imgs) =>
            imgs.every((img) => img.complete && img.naturalWidth > 0),
          ),
        )
        .toBe(true);
      await expect(readPage.getByRole('button', { name: '선택 저장', exact: true })).toBeDisabled();
      assert.equal(posts.length, beforeRead);
      await readPage.close();
      phase = 'preview';
      polled = {
        ...clone(initial),
        contract: { kind: 'face_confirm_preview' },
        draft: { confirmed: false },
      };
      const previewPage = await context.newPage();
      await previewPage.setViewportSize({ width, height: 950 });
      previewPage.on('pageerror', (e) => errors.push(e.message));
      await mount(previewPage);
      await previewPage.locator('[data-node-id="face"] .workflow-node-heading').click();
      const preview = previewPage.getByAltText('합성 미리보기', { exact: true });
      await expect
        .poll(() => preview.evaluate((img) => img.complete && img.naturalWidth > 0))
        .toBe(true);
      await expect(previewPage.getByRole('checkbox')).toBeDisabled();
      await expect(
        previewPage.getByRole('button', { name: '미리보기 확인 확정', exact: true }),
      ).toBeDisabled();
      assert.equal(posts.length, beforeRead);
      await previewPage.close();
      // Owner rights do not make a cancelled job editable.
      phase = 'select';
      manage = true;
      jobStatus = 'cancelled';
      polled = { ...clone(initial), draft: { source_position: 0, face_position: 0 } };
      const cancelled = await context.newPage();
      await cancelled.setViewportSize({ width, height: 950 });
      await mount(cancelled);
      await cancelled.locator('[data-node-id="face"] .workflow-node-heading').click();
      await expect(
        cancelled.getByRole('button', { name: '인물 선택 확정', exact: true }),
      ).toBeDisabled();
      await expect(
        cancelled.getByText('현재 작업 상태에서는 검수 내용을 변경할 수 없습니다.'),
      ).toBeVisible();
      assert.equal(posts.length, beforeRead);
      await cancelled.close();
    }
    assert.ok(images.length > 0);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(errors, []);
    assert.ok(posts.every((row) => row.path.endsWith('/save') || row.path.endsWith('/confirm')));
    fs.writeFileSync(
      path.join(dir, 'OFFLINE-poll-requests.json'),
      JSON.stringify({ posts, gets, images }, null, 2),
    );
  } catch (error) {
    fs.writeFileSync(
      path.join(dir, 'OFFLINE-failure.json'),
      JSON.stringify(
        {
          posts,
          gets,
          images,
          unexpected,
          errors,
          pages: await Promise.all(
            browser
              .contexts()
              .flatMap((c) => c.pages())
              .map((p) => p.locator('body').innerText()),
          ),
        },
        null,
        2,
      ),
    );
    console.error('OFFLINE failure evidence', dir);
    throw error;
  } finally {
    await browser.close();
  }
});
