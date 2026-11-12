// New MT-only preparation: real authenticated React/CSS, fully offline API fixtures.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

const scratch = 'C:/Users/skygg/AppData/Local/hermes/cache/scratch/mediagent-5178-parity';
const copyId = '9'.repeat(32),
  videoId = 'd'.repeat(32),
  workflowId = 'f'.repeat(32);
const primary = { model_id: '1'.repeat(32), revision: 7 },
  fallback = { model_id: '2'.repeat(32), revision: 8 };
const srt = '  \n00:00:00,125 --> 00:00:00,750\n literal text \nsecond line\n';
const copy = {
  id: copyId,
  filename: 'actual saved.smi',
  title: '저장한 수정본',
  created_at: '2026-11-12T00:00:00Z',
  cue_count: 1,
  srt,
  srt_sha256: createHash('sha256').update(srt).digest('hex'),
};
const node = {
  id: 'translation',
  type: 'translation_agent',
  position: { x: 290, y: 0 },
  options: { target_language: 'ko', llm_options: '{"reasoning_effort":"high"}' },
  model_ref: primary,
  fallback_refs: [fallback],
};
const graph = {
  id: workflowId,
  name: '기존 저장 흐름',
  revision: 3,
  catalog_version: 2,
  inputs: {},
  nodes: [
    { id: 'asr', type: 'transcription_agent', options: {}, position: { x: 0, y: 0 } },
    node,
    { id: 'subtitle_video', type: 'subtitle_video_agent', options: {}, position: { x: 580, y: 0 } },
  ],
  edges: [
    {
      id: 'source',
      source: { node: 'asr', port: 'media' },
      target: { node: 'translation', port: 'media' },
    },
    {
      id: 'video-input',
      source: { node: 'translation', port: 'media' },
      target: { node: 'subtitle_video', port: 'media' },
    },
  ],
};

test('saved copy → MT-only metadata preparation at PC1440/390, paid scope and no automatic Create (offline)', async () => {
  const directory = fs.mkdtempSync(path.join(scratch, 'saved-mt-browser-'));
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
    .filter((n) => n.endsWith('.css'))
    .map((n) => fs.readFileSync(path.join('dist/assets', n), 'utf8'))
    .join('\n');
  const browser = await chromium.launch({
    channel: process.platform === 'win32' ? 'msedge' : undefined,
    headless: true,
  });
  const unexpected = [],
    errors = [],
    previews = [],
    mutations = [];
  let reject = false,
    copyError = false,
    delay = false;
  try {
    const context = await browser.newContext({ offline: true });
    await context.route('**/*', async (route) => {
      const req = route.request(),
        url = new URL(req.url());
      if (url.origin !== 'https://saved-mt.invalid') {
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
      const json = (v, status = 200) =>
        route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(v) });
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
        return json({ uploads: [] });
      }
      if (url.pathname === '/api/subtitle-copies') {
        return json({ copies: [copy], next_cursor: null });
      }
      if (url.pathname === '/api/subtitle-copies/' + copyId) {
        return copyError ? json({ detail: '저장 자막 접근 거부' }, 403) : json(copy);
      }
      if (url.pathname === '/api/videos') {
        return json({
          videos: [
            {
              asset_id: videoId,
              original_filename: 'related original.mp4',
              size_bytes: 123,
              created_at: copy.created_at,
              media: { duration: 12, width: 1280, height: 720, has_audio: true },
            },
          ],
        });
      }
      if (url.pathname === '/api/work-entry/workflows') {
        return json({ definitions: [{ id: workflowId, revision: 3, name: graph.name }] });
      }
      if (url.pathname === '/api/work-entry/catalog') {
        return json({
          nodes: [
            {
              id: 'translation_agent',
              label: '번역 에이전트',
              kind: 'agent',
              inputs: { media: 'media_task' },
              outputs: { media: 'media_task', transcript: 'transcript' },
              options: { target_language: ['ko'], llm_options: [''] },
              model_role: 'translation',
            },
          ],
        });
      }
      if (url.pathname === '/api/work-entry/workflows/' + workflowId) {
        return json(graph);
      }
      if (url.pathname === '/api/work-entry/inspect') {
        const body = req.postDataJSON(),
          selected = body.options.translation_goal;
        assert.equal('render_goal' in body.options, false);
        assert.equal(selected.node_id, 'translation');
        const effective = {
          ...node,
          options: { ...node.options, ...selected.options },
          model_ref: selected.model_ref || primary,
        };
        return json({
          supported: true,
          model_ready: true,
          definition_revision: 3,
          paid_roles: ['translation'],
          reasons: [],
          summary: [
            {
              ...effective,
              model: {
                ...effective.model_ref,
                name:
                  effective.model_ref.model_id === primary.model_id ? '등록 모델 A' : '등록 모델 B',
                provider: '등록 공급자',
                model: 'fixture',
              },
            },
          ],
          agent_definition: {
            ...graph,
            inputs: { transcript: 'transcript' },
            nodes: [effective],
            edges: [],
          },
        });
      }
      if (url.pathname === '/api/work-entry/preview') {
        const body = req.postDataJSON();
        previews.push(body);
        assert.equal(req.headers()['x-csrf-token'], 'csrf');
        assert.deepEqual(body.options.saved_subtitle, {
          copy_id: copyId,
          srt_sha256: copy.srt_sha256,
        });
        assert.equal(body.asset_id, videoId);
        assert.equal('render_goal' in body.options, false);
        const shouldDelay = delay;
        delay = false;
        if (shouldDelay) {
          await new Promise((r) => setTimeout(r, 500));
        }
        return reject
          ? json({ detail: '선택 모델을 확인할 수 없습니다.' }, 403)
          : json({
              token: '1'.repeat(64),
              paid_roles: ['translation'],
              model_call_budgets: [
                {
                  node_id: 'translation__translate',
                  role: 'translate',
                  max_calls: 4,
                  minimum_audio_calls: null,
                },
              ],
              notice: '',
            });
      }
      if (req.method() !== 'GET') {
        mutations.push({ path: url.pathname, body: req.postDataJSON() });
        return json({ code: 'job_busy', detail: '합성 응답 불명: 작업 목록을 확인하세요.' }, 409);
      }
      unexpected.push(`${req.method()} ${url.pathname}`);
      return route.abort();
    });
    const mount = async (page, hash) => {
      await page.goto('https://saved-mt.invalid/' + hash);
      await page.addStyleTag({ content: css });
      await page.addScriptTag({ content: bundle.outputFiles[0].text });
    };
    for (const width of [1440, 390]) {
      const page = await context.newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      await page.setViewportSize({ width, height: 950 });
      await mount(page, '#/subtitles/saved');
      await page.getByRole('link', { name: '자막 번역 준비', exact: true }).click();
      await expect(page.getByText(copy.filename, { exact: true })).toBeVisible();
      assert.equal(page.url().endsWith('#/start/subtitles/' + copyId + '/translate'), true);
      await mount(page, '#/start/subtitles/' + copyId + '/translate');
      await expect(page.getByText(copy.filename, { exact: true })).toBeVisible();
      const start = page.getByRole('button', { name: '새 작업 만들고 시작', exact: true });
      await expect(start).toBeDisabled();
      await page.getByLabel('원본 영상', { exact: true }).selectOption(videoId);
      await page.getByLabel('저장된 워크플로우', { exact: true }).selectOption(workflowId);
      await page.getByLabel('번역 에이전트', { exact: true }).selectOption('translation');
      await expect(start).toBeEnabled();
      await expect(page.getByLabel('번역할 언어', { exact: true })).toHaveValue('ko');
      await page.getByLabel('자막 언어', { exact: true }).fill('ja');
      await page.getByLabel('번역할 언어', { exact: true }).fill('pt-BR');
      await page.getByLabel('번역 모델', { exact: true }).selectOption(JSON.stringify(fallback));
      await expect(page.getByText('등록 모델 B', { exact: false })).toBeVisible();
      await expect(start).toBeEnabled();
      assert.equal(previews.at(-1).options.input_language, 'ja');
      assert.equal(previews.at(-1).options.translation_goal.options.target_language, 'pt-BR');
      await page
        .getByLabel('모델 요청 옵션 (JSON)', { exact: true })
        .fill('{"reasoning_effort":"low","max_tokens":512}');
      await expect(start).toBeEnabled();
      assert.equal(
        previews.at(-1).options.translation_goal.options.llm_options,
        '{"reasoning_effort":"low","max_tokens":512}',
      );
      await expect(page.getByText(/최대 4회/)).toBeVisible();
      await expect(page.getByText(/금액은 미산정/)).toBeVisible();
      if (width === 1440) {
        delay = true;
        const prior = previews.length;
        await page.getByLabel('번역할 언어', { exact: true }).fill('en');
        await expect.poll(() => previews.length).toBeGreaterThan(prior);
        await page.getByLabel('원본 영상', { exact: true }).selectOption('');
        await page.waitForTimeout(650);
        await expect(start).toBeDisabled();
        await page.getByLabel('원본 영상', { exact: true }).selectOption(videoId);
        await expect(start).toBeEnabled();
      }
      reject = true;
      await page.getByLabel('번역할 언어', { exact: true }).fill('pl');
      await expect(page.getByRole('alert')).toContainText('선택 모델');
      await expect(start).toBeDisabled();
      reject = false;
      await page.getByLabel('번역할 언어', { exact: true }).fill('de');
      await expect(start).toBeEnabled();
      assert.equal(mutations.length, 0);
      await start.scrollIntoViewIfNeeded();
      await start.click({ trial: true });
      const box = await start.boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= width);
      assert.equal(
        await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
        false,
      );
      await page.screenshot({
        path: path.join(directory, `mt-preparation-${width}.png`),
        fullPage: true,
      });
      if (width === 390) {
        await start.click();
        await expect(page.getByRole('alert')).toContainText('응답 불명');
        await expect(start).toBeDisabled();
        await page.waitForTimeout(350);
        assert.equal(mutations.length, 1);
        assert.equal(mutations[0].path, '/api/work-entry/create');
        assert.equal(mutations[0].body.paid_confirmed, true);
        assert.equal(
          mutations[0].body.options.translation_goal.model_ref.model_id,
          fallback.model_id,
        );
      }
      await mount(page, '#/subtitles/saved/' + copyId);
      await expect(page.getByRole('link', { name: '자막 번역 준비', exact: true })).toHaveAttribute(
        'href',
        '#/start/subtitles/' + copyId + '/translate',
      );
      copyError = true;
      await mount(page, '#/start/subtitles/' + copyId + '/translate');
      await expect(page.getByRole('alert')).toContainText('접근 거부');
      await expect(
        page.getByRole('button', { name: '새 작업 만들고 시작', exact: true }),
      ).toBeDisabled();
      copyError = false;
      if (width === 1440) {
        // Only the changed legacy DISPLAY label, not the accepted video journey.
        await mount(page, '#/start/subtitles/' + copyId);
        await page.getByLabel('저장된 워크플로우', { exact: true }).selectOption(workflowId);
        await expect(
          page
            .getByLabel('자막 영상 에이전트', { exact: true })
            .locator('option[value="subtitle_video"]'),
        ).toHaveText('자막 영상 에이전트');
        assert.equal(mutations.length, 0);
      }
      await page.close();
    }
    assert.deepEqual(unexpected, []);
    assert.deepEqual(errors, []);
    fs.writeFileSync(
      path.join(directory, 'result.json'),
      JSON.stringify(
        {
          synthetic: true,
          widths: [1440, 390],
          previews: previews.length,
          createFixtures: mutations.length,
          unexpected,
          errors,
        },
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
  }
});
