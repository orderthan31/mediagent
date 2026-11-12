// OFFLINE fixtures only: actual React/AuthGate/components and production CSS.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';
const scratch = 'C:/Users/skygg/AppData/Local/hermes/cache/scratch/mediagent-5178-parity';
const photo = 'a'.repeat(32),
  target = 'c'.repeat(32),
  workflow = 'd'.repeat(32),
  job = 'e'.repeat(32),
  reviewId = 'f'.repeat(32),
  sha = '1'.repeat(64);
const definition = {
  id: workflow,
  catalog_version: 2,
  revision: 2,
  name: '얼굴 합성',
  input_profile: 'face_workflow_v1',
  inputs: { photo: 'image' },
  nodes: [
    {
      id: 'face',
      type: 'faceswap_agent',
      position: { x: 0, y: 0 },
      options: { preset: 'fast', video_codec: 'h264' },
    },
  ],
  edges: [],
};
const descriptor = {
  id: 'faceswap_agent',
  label: '얼굴 합성 에이전트',
  kind: 'agent',
  inputs: {},
  outputs: { media: 'media_task', video: 'video', report: 'validation_report' },
  options: { preset: ['fast', 'balanced', 'quality'], video_codec: ['h264', 'hevc'] },
};
const photoAsset = {
  asset_id: photo,
  original_filename: 'synthetic nonpersonal photo long literal filename '.repeat(3) + '.png',
  media_kind: 'image',
  size_bytes: 80,
  media: { kind: 'image', format: 'png', width: 8, height: 4, orientation: 1 },
  created_at: '2026-11-13T00:00:00Z',
};
const targetAsset = {
  asset_id: target,
  original_filename: 'target unchanged.mp4',
  size_bytes: 123,
  media: { duration: 12, width: 640, height: 360 },
  created_at: photoAsset.created_at,
};
test('new face normal preparation + explicit review controls PC1440/390 (OFFLINE)', async () => {
  const dir = fs.mkdtempSync(path.join(scratch, 'face-workflow-browser-'));
  const bundle = await build({
    stdin: {
      resolveDir: process.cwd(),
      loader: 'tsx',
      contents: `import React from 'react';import {createRoot} from 'react-dom/client';import {AuthGate} from './src/AuthGate';import {PageTitleProvider} from './src/PageTitle';import {WorkflowStart} from './src/WorkflowStart';import {WorkflowEditor} from './src/WorkflowEditor';import {FaceWorkflowReview} from './src/FaceWorkflowReview';const mode=new URLSearchParams(location.search).get('mode');const selection={id:'${reviewId}',revision:1,status:'draft',draft:{source_position:null,face_position:null},contract:{kind:'face_select',source:{faces:[{position:0}]},reference:{faces:[{position:0}]}}};const confirm={id:'${reviewId}',revision:1,status:'draft',draft:{confirmed:false},contract:{kind:'face_confirm_preview'}};createRoot(document.getElementById('root')).render(<AuthGate><PageTitleProvider>{mode==='editor'?<WorkflowEditor initialId={new URLSearchParams(location.search).get('identity')||undefined}/>:mode==='select'||mode==='confirm'?<main className="serving-page"><FaceWorkflowReview initial={mode==='select'?selection:confirm} jobId="${job}" canManage={true} changed={async()=>{document.documentElement.dataset.confirmed='yes';}}/></main>:<WorkflowStart/>}</PageTitleProvider></AuthGate>);`,
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
  let supported = false,
    lostReply = false,
    forbidden = false,
    currentReview = null,
    savedDefinition = definition;
  const calls = [],
    unexpected = [],
    errors = [];
  try {
    const context = await browser.newContext({ offline: true });
    await context.route('**/*', async (route) => {
      const req = route.request(),
        url = new URL(req.url()),
        json = (v, status = 200) =>
          route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(v) });
      if (url.origin !== 'https://face-workflow.invalid') {
        unexpected.push(url.href);
        return route.abort();
      }
      if (url.pathname === '/') {
        return route.fulfill({
          contentType: 'text/html',
          body: '<!doctype html><html lang="ko"><body><div id="root"></div></body></html>',
        });
      }
      if (url.pathname.startsWith('/fonts/hangyeol/')) {
        return route.fulfill({
          body: fs.readFileSync(path.join('public', url.pathname)),
          contentType: 'font/woff2',
        });
      }
      if (req.method() !== 'GET') {
        calls.push({ method: req.method(), path: url.pathname, body: req.postDataJSON() });
      }
      if (url.pathname === '/api/auth/session') {
        return json({
          enabled: true,
          user: { id: 'b'.repeat(32), role: 'admin', username: 'offline' },
          csrf_token: 'offline-csrf',
        });
      }
      if (url.pathname === '/api/videos') {
        return forbidden
          ? json({ detail: '원본 접근 거부' }, 403)
          : json({ videos: [photoAsset, targetAsset] });
      }
      if (['/api/work-entry/catalog', '/api/settings/node-catalog'].includes(url.pathname)) {
        return json({ nodes: [descriptor] });
      }
      if (
        ['/api/work-entry/workflows', '/api/settings/workflow-definitions'].includes(url.pathname)
      ) {
        return json({ definitions: [{ id: workflow, name: definition.name, revision: 2 }] });
      }
      if (
        url.pathname === '/api/work-entry/workflows/' + workflow ||
        url.pathname === '/api/settings/workflow-definitions/' + workflow
      ) {
        return json(savedDefinition);
      }
      if (url.pathname === '/api/work-entry/inspect') {
        return json({
          supported,
          model_ready: supported,
          definition_revision: 2,
          summary: definition.nodes,
          reasons: supported
            ? []
            : [
                {
                  message: '단계별 얼굴 합성을 지원하는 실행기 버전이 필요합니다.',
                  node_id: 'face',
                },
              ],
        });
      }
      if (url.pathname === '/api/work-entry/faceswap-inputs') {
        return json({
          engines: [
            {
              role: 'faceswap',
              revision: 2,
              sha256: sha,
              engine: 'facefusion-3.9.0',
              face_protocol: supported ? 3 : 2,
            },
          ],
          reason: '',
        });
      }
      if (url.pathname === '/api/work-entry/preview') {
        return json({
          token: 'offline-plan',
          paid_roles: [],
          model_call_budgets: [],
          selected_inputs: [{ input: 'photo', kind: 'photo_original_v1' }],
          notice: '오프라인 입력 준비 fixture',
        });
      }
      if (url.pathname === '/api/settings/workflow-definitions/validate') {
        return json({ valid: true, issues: [] });
      }
      if (
        url.pathname.startsWith('/api/settings/workflow-definitions/') &&
        req.method() === 'PUT'
      ) {
        savedDefinition = { ...req.postDataJSON(), id: workflow, revision: 2 };
        return json(savedDefinition);
      }
      if (url.pathname.includes('/face-image/')) {
        return route.fulfill({
          contentType: 'image/png',
          body: Buffer.from(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN1cAAAAASUVORK5CYII=',
            'base64',
          ),
        });
      }
      if (url.pathname === `/api/renewal/reviews/${reviewId}/save`) {
        const body = req.postDataJSON();
        currentReview = { ...currentReview, revision: body.revision + 1, draft: body.draft };
        if (lostReply) {
          lostReply = false;
          return route.abort();
        }
        return json(currentReview);
      }
      if (url.pathname === `/api/renewal/reviews/${reviewId}/confirm`) {
        currentReview = { ...currentReview, status: 'confirmed' };
        return json({ id: job, reviews: [currentReview] });
      }
      if (url.pathname === `/api/renewal/jobs/${job}`) {
        return json({ id: job, reviews: [currentReview] });
      }
      unexpected.push(req.method() + ' ' + url.pathname);
      return route.abort();
    });
    const mount = async (page, mode, hash = '#/start') => {
      await page.goto(`https://face-workflow.invalid/?mode=${mode}${hash}`);
      await page.addStyleTag({ content: css });
      await page.addScriptTag({ content: bundle.outputFiles[0].text });
    };
    for (const width of [1440, 390]) {
      supported = false;
      const page = await context.newPage();
      await page.setViewportSize({ width, height: 950 });
      page.on('pageerror', (e) => errors.push(e.message));
      await mount(page, 'start', `#/start?photo=${photo}&target=${target}`);
      await page.getByLabel('워크플로우', { exact: true }).selectOption(workflow);
      await expect(page.getByLabel('원본 사진', { exact: true })).toHaveValue(photo);
      await page.getByLabel('얼굴 합성 실행기', { exact: true }).selectOption(`2:${sha}`);
      await expect(
        page.getByText('이 실행기는 단계별 얼굴 합성을 지원하지 않습니다.', { exact: false }),
      ).toBeVisible();
      await expect(page.getByRole('button', { name: '작업 시작', exact: true })).toBeDisabled();
      assert.equal(await page.locator('[data-node-kind="agent"]').count(), 1);
      assert.equal(await page.locator('[data-node-kind="input"]').count(), 0);
      supported = true;
      await mount(page, 'start', `#/start?photo=${photo}&target=${target}&workflow=${workflow}`);
      await expect(page.getByLabel('원본 사진', { exact: true })).toHaveValue(photo);
      await page.getByLabel('얼굴 합성 실행기', { exact: true }).selectOption(`2:${sha}`);
      await expect(page.getByText('선택 사진 원본', { exact: true })).toBeVisible();
      const preview = calls.filter((c) => c.path === '/api/work-entry/preview').at(-1);
      assert.equal(preview.body.options.face_input.photo_asset_id, photo);
      assert.equal(preview.body.options.face_input.reference_frame, 1);
      for (const label of ['원본 사진', '얼굴 합성 실행기', '영상 기준 프레임']) {
        const control = page.getByLabel(label, { exact: true });
        await control.scrollIntoViewIfNeeded();
        const rect = await control.boundingBox();
        assert.ok(rect.x >= 0 && rect.x + rect.width <= width + 1, label);
      }
      const beforeEditor = calls.length;
      await mount(page, 'editor');
      await page.getByRole('button', { name: '얼굴 합성 작업 만들기', exact: true }).click();
      assert.equal(calls.length, beforeEditor);
      await page.locator('[data-node-id="face"] .workflow-node-heading').click();
      await page.getByLabel('합성 품질', { exact: true }).selectOption('quality');
      await page.getByLabel('영상 형식', { exact: true }).selectOption('hevc');
      const settingsControl = page.getByLabel('합성 품질', { exact: true });
      await settingsControl.scrollIntoViewIfNeeded();
      const settingsRect = await settingsControl.boundingBox();
      assert.ok(settingsRect.x >= 0 && settingsRect.x + settingsRect.width <= width + 1);
      await page.getByRole('button', { name: '저장', exact: true }).click();
      await expect(page.getByRole('button', { name: '이력', exact: true })).toBeVisible();
      const saved = calls.filter((c) => c.method === 'PUT').at(-1).body;
      assert.equal(saved.input_profile, 'face_workflow_v1');
      assert.deepEqual(saved.inputs, { photo: 'image' });
      assert.equal(saved.nodes[0].type, 'faceswap_agent');
      assert.equal(saved.nodes[0].options.preset, 'quality');
      assert.equal(saved.nodes[0].options.video_codec, 'hevc');
      await mount(page, 'editor&identity=' + workflow);
      await page.locator('[data-node-id="face"] .workflow-node-heading').click();
      await expect(page.getByLabel('합성 품질', { exact: true })).toHaveValue('quality');
      await expect(page.getByLabel('영상 형식', { exact: true })).toHaveValue('hevc');
      currentReview = {
        id: reviewId,
        revision: 1,
        status: 'draft',
        draft: { source_position: null, face_position: null },
        contract: {
          kind: 'face_select',
          source: { faces: [{ position: 0 }] },
          reference: { faces: [{ position: 0 }] },
        },
      };
      const before = calls.length;
      await mount(page, 'select');
      await expect(
        page.getByRole('heading', { name: '사진과 영상의 인물을 각각 선택하세요' }),
      ).toBeVisible();
      assert.equal(calls.length, before);
      await expect(
        page.getByRole('button', { name: '인물 선택 확정', exact: true }),
      ).toBeDisabled();
      await page.getByRole('radio').nth(0).check();
      await page.getByRole('radio').nth(1).check();
      await page.getByRole('button', { name: '선택 저장', exact: true }).click();
      await expect(page.getByRole('button', { name: '인물 선택 확정', exact: true })).toBeEnabled();
      await page.getByRole('button', { name: '인물 선택 확정', exact: true }).click();
      await expect(page.locator('html')).toHaveAttribute('data-confirmed', 'yes');
      assert.deepEqual(calls.filter((c) => c.path.endsWith('/save')).at(-1).body.draft, {
        source_position: 0,
        face_position: 0,
      });
      currentReview = {
        id: reviewId,
        revision: 1,
        status: 'draft',
        draft: { confirmed: false },
        contract: { kind: 'face_confirm_preview' },
      };
      await mount(page, 'confirm');
      await expect(page.getByAltText('합성 미리보기', { exact: true })).toBeVisible();
      await page.getByRole('checkbox').check();
      lostReply = true;
      const mutations = calls.length;
      await page.getByRole('button', { name: '선택 저장', exact: true }).click();
      await expect(page.getByRole('alert')).toBeVisible();
      await expect(
        page.getByRole('button', { name: '미리보기 확인 확정', exact: true }),
      ).toBeDisabled();
      assert.equal(calls.length, mutations + 1);
      await page.getByRole('button', { name: '상태 다시 불러오기', exact: true }).click();
      await expect(
        page.getByRole('button', { name: '미리보기 확인 확정', exact: true }),
      ).toBeEnabled();
      const button = page.getByRole('button', { name: '미리보기 확인 확정', exact: true });
      await button.scrollIntoViewIfNeeded();
      const rect = await button.boundingBox();
      assert.ok(rect.x >= 0 && rect.x + rect.width <= width + 1 && rect.height >= 32);
      await page.screenshot({
        path: path.join(dir, `OFFLINE-face-review-${width}.png`),
        fullPage: true,
      });
      await page.close();
    }
    assert.equal(
      calls.filter(
        (c) =>
          /create|admit|run|analyze|render|start|preview.*confirm/.test(c.path) &&
          c.path !== '/api/work-entry/preview',
      ).length,
      0,
    );
    assert.deepEqual(unexpected, []);
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(dir, 'OFFLINE-requests.json'), JSON.stringify(calls, null, 2));
  } catch (error) {
    const pages = browser.contexts().flatMap((c) => c.pages());
    fs.writeFileSync(
      path.join(dir, 'OFFLINE-failure.json'),
      JSON.stringify(
        {
          calls,
          unexpected,
          errors,
          pages: await Promise.all(
            pages.map((p) =>
              p
                .locator('body')
                .innerText()
                .catch(() => ''),
            ),
          ),
        },
        null,
        2,
      ),
    );
    console.error(
      'OFFLINE failure evidence',
      dir,
      JSON.stringify({
        calls: calls.slice(-3),
        unexpected,
        errors,
        alerts: await Promise.all(pages.map((p) => p.getByRole('alert').allTextContents())),
      }),
    );
    throw error;
  } finally {
    await browser.close();
  }
});
