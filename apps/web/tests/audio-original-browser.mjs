// New audio-only path: real React/AuthGate/CSS with OFFLINE API fixtures.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';
const scratch = 'C:/Users/skygg/AppData/Local/hermes/cache/scratch/mediagent-5178-parity';
const id = 'd'.repeat(32),
  wid = 'f'.repeat(32),
  primary = { model_id: '1'.repeat(32), revision: 7 },
  fallback = { model_id: '2'.repeat(32), revision: 8 };
const asset = {
  asset_id: id,
  original_filename: '실제 이름 stereo.mp3',
  media_kind: 'audio',
  media_type: 'audio/mpeg',
  size_bytes: 1234,
  created_at: '2026-11-12T00:00:00Z',
  media: {
    kind: 'audio',
    duration: 12,
    format: 'mp3',
    codec: 'mp3',
    sample_rate: 44100,
    channels: 2,
  },
  provenance: { kind: 'upload' },
};
const node = {
  id: 'asr',
  type: 'transcription_agent',
  position: { x: 0, y: 0 },
  options: { source_language: 'ja', llm_options: '{"reasoning_effort":"high"}' },
  model_ref: primary,
  fallback_refs: [fallback],
};
const graph = {
  id: wid,
  name: '기존 전체 작업',
  revision: 3,
  catalog_version: 2,
  inputs: {},
  nodes: [node, { id: 'mt', type: 'translation_agent', position: { x: 300, y: 0 }, options: {} }],
  edges: [],
};
test('audio library to ASR-only preparation and reload PC1440/390 (OFFLINE)', async () => {
  const dir = fs.mkdtempSync(path.join(scratch, 'audio-browser-'));
  const bundle = await build({
    stdin: {
      resolveDir: process.cwd(),
      loader: 'tsx',
      contents: `import React from'react';import{createRoot}from'react-dom/client';import{AuthGate}from'./src/AuthGate';import{VideoWorkspace}from'./src/VideoWorkspace';import{PageTitleProvider}from'./src/PageTitle';createRoot(document.getElementById('root')).render(<AuthGate><PageTitleProvider><VideoWorkspace/></PageTitleProvider></AuthGate>);`,
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
  const unexpected = [],
    mutations = [],
    previews = [],
    errors = [],
    uploads = [];
  const uploadId = 'c'.repeat(32),
    payload = Buffer.from('synthetic only');
  let uploaded = 2;
  let reject = false,
    delay = false;
  try {
    const context = await browser.newContext({ offline: true });
    await context.route('**/*', async (route) => {
      const req = route.request(),
        url = new URL(req.url());
      const json = (v, status = 200) =>
        route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(v) });
      if (url.origin !== 'https://audio.invalid') {
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
      if (url.pathname === '/api/auth/session') {
        return json({
          enabled: true,
          user: { id: 'b'.repeat(32), username: 'ordinary', role: 'user' },
          csrf_token: 'csrf',
        });
      }
      if (url.pathname === '/api/capabilities') {
        return json({ features: ['verified_uploads', 'workflows', 'jobs'] });
      }
      if (url.pathname === '/api/jobs') {
        return json({ jobs: [] });
      }
      if (url.pathname === '/api/video-uploads') {
        if (req.method() === 'GET') {
          return json({ uploads: [] });
        }
        const b = req.postDataJSON();
        assert.equal(b.filename, 'new sound.mp3');
        assert.equal(b.size, payload.length);
        uploads.push('create');
        return json({ upload_id: uploadId });
      }
      if (url.pathname === '/api/video-uploads/' + uploadId) {
        return json({ uploaded_bytes: uploaded, expected_size: payload.length, resumable: true });
      }
      if (url.pathname === '/api/video-uploads/' + uploadId + '/verify') {
        const b = req.postDataJSON();
        assert.equal(b.sha256, createHash('sha256').update(payload.subarray(0, 2)).digest('hex'));
        uploads.push('verify');
        return json({});
      }
      if (url.pathname === '/api/video-uploads/' + uploadId + '/chunks') {
        assert.equal(url.searchParams.get('offset'), '2');
        assert.deepEqual(req.postDataBuffer(), payload.subarray(2));
        uploaded = payload.length;
        uploads.push('chunks');
        return json({ uploaded_bytes: uploaded });
      }
      if (url.pathname === '/api/video-uploads/' + uploadId + '/complete') {
        uploads.push('complete');
        return json({ asset_id: id });
      }

      if (url.pathname === '/api/videos/' + id + '/subtitles') {
        return json({ subtitles: [] });
      }
      if (url.pathname === '/api/videos') {
        return json({ videos: [asset] });
      }
      if (url.pathname === '/api/videos/' + id) {
        return json({ video: asset, jobs: [] });
      }
      if (url.pathname === '/api/work-entry/workflows') {
        return json({ definitions: [{ id: wid, revision: 3, name: graph.name }] });
      }
      if (url.pathname === '/api/work-entry/catalog') {
        return json({
          nodes: [
            {
              id: 'transcription_agent',
              label: '전사 에이전트',
              kind: 'agent',
              inputs: { media: 'media_task' },
              outputs: { media: 'media_task', transcript: 'transcript' },
              options: { source_language: ['auto', 'en', 'ja'], llm_options: [''] },
              model_role: 'transcription',
            },
          ],
        });
      }
      if (url.pathname === '/api/work-entry/workflows/' + wid) {
        return json(graph);
      }
      if (url.pathname === '/api/work-entry/inspect') {
        const selected = req.postDataJSON().options.audio_goal;
        assert.equal(selected.node_id, 'asr');
        const effective = {
          ...node,
          options: { ...node.options, ...selected.options },
          model_ref: selected.model_ref || primary,
        };
        return json({
          supported: true,
          model_ready: true,
          definition_revision: 3,
          reasons: [],
          summary: [
            {
              ...effective,
              model: { ...effective.model_ref, name: '등록 음성 모델', provider: '등록 공급자' },
            },
          ],
          agent_definition: {
            ...graph,
            input_profile: 'audio_file_v1',
            inputs: { audio: 'audio' },
            nodes: [effective],
            edges: [],
          },
        });
      }
      if (url.pathname === '/api/work-entry/preview') {
        const body = req.postDataJSON();
        previews.push(body);
        assert.equal(body.asset_id, id);
        assert.equal(body.options.audio_goal.node_id, 'asr');
        assert.equal('saved_subtitle' in body.options, false);
        assert.equal('accepted_inputs' in body.options, false);
        assert.equal(req.headers()['x-csrf-token'], 'csrf');
        const wait = delay;
        delay = false;
        if (wait) {
          await new Promise((r) => setTimeout(r, 450));
        }
        return reject
          ? json({ detail: '선택 음성 원본 접근 거부' }, 403)
          : json({
              token: '1'.repeat(64),
              paid_roles: ['transcription'],
              model_call_budgets: [{ role: 'transcribe', max_calls: 4 }],
            });
      }
      if (req.method() !== 'GET') {
        mutations.push(url.pathname);
        assert.equal(req.postDataJSON().paid_confirmed, true);
        assert.equal(req.postDataJSON().options.audio_goal.model_ref.model_id, fallback.model_id);
        return json({ detail: '합성 응답 불명' }, 409);
      }
      unexpected.push(req.method() + ' ' + url.pathname);
      return route.abort();
    });
    const mount = async (page, hash) => {
      await page.goto('https://audio.invalid/' + hash);
      await page.addStyleTag({ content: css });
      await page.addScriptTag({ content: bundle.outputFiles[0].text });
    };
    for (const width of [1440, 390]) {
      const page = await context.newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      await page.setViewportSize({ width, height: 950 });
      if (width === 1440) {
        await mount(page, '#/');
        await page
          .locator('input[type=file]')
          .first()
          .setInputFiles({ name: 'new sound.mp3', mimeType: 'audio/mpeg', buffer: payload });
        await expect.poll(() => uploads).toEqual(['create', 'verify', 'chunks', 'complete']);
      }
      await mount(page, '#/videos/' + id);
      await expect(page.getByRole('link', { name: '음성 전사 준비', exact: true })).toBeVisible();
      assert.equal(await page.locator('video').count(), 0);
      await page.getByRole('link', { name: '음성 전사 준비', exact: true }).click();
      await expect(page.getByLabel('원본 음성', { exact: true })).toHaveValue(id);
      await mount(page, '#/start/audio/' + id);
      const start = page.getByRole('button', { name: '새 작업 만들고 시작', exact: true });
      await expect(start).toBeDisabled();
      await page.getByLabel('저장된 워크플로우', { exact: true }).selectOption(wid);
      await page.getByLabel('전사 에이전트', { exact: true }).selectOption('asr');
      await expect(start).toBeEnabled();
      await page.getByLabel('원문 언어', { exact: true }).fill('en');
      await page.getByLabel('전사 모델', { exact: true }).selectOption(JSON.stringify(fallback));
      await page
        .getByLabel('모델 요청 옵션 (JSON)', { exact: true })
        .fill('{"reasoning_effort":"low"}');
      await expect(start).toBeEnabled();
      assert.equal(previews.at(-1).options.audio_goal.options.source_language, 'en');
      assert.deepEqual(previews.at(-1).options.audio_goal.model_ref, fallback);
      await expect(page.getByText(/최대 4회/)).toBeVisible();
      await expect(page.getByText(/금액은 미산정/)).toBeVisible();
      const validOptions = previews.length;
      await page.getByLabel('모델 요청 옵션 (JSON)', { exact: true }).fill('{');
      await expect(page.getByRole('alert')).toContainText('JSON 객체');
      await expect(start).toBeDisabled();
      await page.waitForTimeout(200);
      assert.equal(previews.length, validOptions);
      await page
        .getByLabel('모델 요청 옵션 (JSON)', { exact: true })
        .fill('{"reasoning_effort":"low"}');
      await expect(start).toBeEnabled();
      const prior = previews.length;
      await page.getByLabel('원문 언어', { exact: true }).fill('');
      await page.waitForTimeout(220);
      assert.equal(previews.length, prior);
      await expect(start).toBeDisabled();
      await page.getByLabel('원문 언어', { exact: true }).fill('en');
      await expect(start).toBeEnabled();
      delay = true;
      const before = previews.length;
      await page.getByLabel('원문 언어', { exact: true }).fill('ja');
      await expect.poll(() => previews.length).toBeGreaterThan(before);
      await page.getByLabel('원본 음성', { exact: true }).selectOption('');
      await page.waitForTimeout(650);
      await expect(start).toBeDisabled();
      await page.getByLabel('원본 음성', { exact: true }).selectOption(id);
      await expect(start).toBeEnabled();
      reject = true;
      await page.getByLabel('원문 언어', { exact: true }).fill('de');
      await expect(page.getByRole('alert')).toContainText('접근 거부');
      await expect(start).toBeDisabled();
      reject = false;
      await page.getByLabel('원문 언어', { exact: true }).fill('en');
      await expect(start).toBeEnabled();
      await start.scrollIntoViewIfNeeded();
      await start.click({ trial: true });
      const box = await start.boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= width);
      assert.equal(
        await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
        false,
      );
      const bounds = await page.locator('.workflow-graph').evaluate((el) => {
        const b = el.getBoundingClientRect(),
          t = el.querySelector('[aria-label="캔버스 배치"]').getBoundingClientRect();
        const n = el.querySelector('.workflow-graph-node').getBoundingClientRect();
        return { bottom: b.bottom, toolbar: t.bottom, toolbarTop: t.top, nodeBottom: n.bottom };
      });
      assert.ok(bounds.toolbar <= bounds.bottom + 1);
      assert.ok(bounds.nodeBottom + 4 <= bounds.toolbarTop, JSON.stringify(bounds));
      await page.screenshot({ path: path.join(dir, 'audio-' + width + '.png'), fullPage: true });
      assert.deepEqual(mutations, []);
      if (width === 390) {
        await start.click();
        await expect(page.getByRole('alert')).toContainText('합성 응답 불명');
        await expect(start).toBeDisabled();
        await page.waitForTimeout(350);
        assert.deepEqual(mutations, ['/api/work-entry/create']);
      }
      await page.close();
    }
    assert.deepEqual(uploads, ['create', 'verify', 'chunks', 'complete']);
    assert.deepEqual(mutations, ['/api/work-entry/create']);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(errors, []);
    fs.writeFileSync(
      path.join(dir, 'result.json'),
      JSON.stringify(
        { offline: true, previews: previews.length, uploads, mutations, unexpected, errors },
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
  }
});
