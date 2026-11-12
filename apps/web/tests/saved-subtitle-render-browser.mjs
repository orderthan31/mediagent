// New render preparation only. Real authenticated React/CSS, synthetic offline API.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

const scratch = 'C:/Users/skygg/AppData/Local/hermes/cache/scratch/mediagent-5178-parity';
const copyId = 'c'.repeat(32),
  videoId = 'd'.repeat(32),
  workflowId = 'f'.repeat(32);
const srt = 'cue A\n00:00:00,125 --> 00:00:01,750\n literal text \nsecond line\n';
const sha = createHash('sha256').update(srt).digest('hex');
const copy = {
  id: copyId,
  filename: 'actual original.smi',
  title: '저장 수정본',
  created_at: '2026-11-12T00:00:00Z',
  cue_count: 1,
  srt,
  srt_sha256: sha,
};
const node = { id: 'caption', type: 'subtitle_video_agent', position: { x: 0, y: 0 }, options: {} };
const graph = {
  id: workflowId,
  name: '기존 저장 흐름',
  revision: 3,
  catalog_version: 2,
  inputs: {},
  nodes: [{ id: 'asr', type: 'transcription_agent', options: {}, position: { x: 0, y: 0 } }, node],
  edges: [
    {
      id: 'caption-input',
      source: { node: 'asr', port: 'media' },
      target: { node: 'caption', port: 'media' },
    },
  ],
};
const options = {
  format: ['srt', 'srt_smi'],
  language: ['from_transcript', 'und', 'en', 'ko'],
  video_codec: ['h264', 'hevc'],
  subtitle_mode: ['burn', 'soft'],
  resolution: ['original', '720p', '1080p'],
  quality_profile: ['balanced', 'high', 'compact'],
  transcript_source: ['current', 'original', 'translated'],
};

test('saved list/detail → normal render preparation survives reload at PC1440/390 (offline specimens)', async () => {
  const directory = fs.mkdtempSync(path.join(scratch, 'saved-render-browser-'));
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
    mutations = [],
    previews = [];
  let copyError = false,
    previewError = false,
    delayNext = false;
  try {
    const context = await browser.newContext({ offline: true });
    await context.route('**/*', async (route) => {
      const req = route.request(),
        url = new URL(req.url());
      if (url.origin !== 'https://saved-render.invalid') {
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
        return json({
          features: ['verified_uploads', 'workflows', 'jobs'],
          execution_enabled: true,
        });
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
        return copyError ? json({ detail: '저장 자막 읽기 실패' }, 503) : json(copy);
      }
      if (url.pathname === '/api/videos') {
        return json({
          videos: [
            {
              asset_id: videoId,
              original_filename: 'selected English.mp4',
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
              id: node.type,
              label: '자막 영상',
              kind: 'agent',
              inputs: { media: 'media_task' },
              outputs: { media: 'media_task', video: 'video', subtitles: 'subtitle' },
              options,
              option_labels: {},
            },
          ],
        });
      }
      if (url.pathname === '/api/work-entry/workflows/' + workflowId) {
        return json(graph);
      }
      if (url.pathname === '/api/work-entry/inspect') {
        const selected = req.postDataJSON().options.render_goal;
        assert.equal(selected.node_id, 'caption');
        const effective = {
          ...node,
          options: {
            ...Object.fromEntries(Object.entries(options).map(([k, v]) => [k, v[0]])),
            ...selected.options,
            transcript_source: 'original',
          },
        };
        return json({
          supported: true,
          model_ready: true,
          definition_revision: 3,
          reasons: [],
          summary: [effective],
          agent_definition: {
            ...graph,
            inputs: { transcript: 'transcript' },
            nodes: [effective],
            edges: [],
          },
        });
      }
      if (url.pathname === '/api/work-entry/preview') {
        assert.equal(req.headers()['x-csrf-token'], 'csrf');
        const body = req.postDataJSON();
        previews.push(body);
        assert.deepEqual(body.options.saved_subtitle, { copy_id: copyId, srt_sha256: sha });
        assert.equal(body.asset_id, videoId);
        assert.equal(body.definition_revision, 3);
        assert.equal(body.options.render_goal.node_id, 'caption');
        assert.equal('subtitle_srt' in body.options, false);
        const delay = delayNext;
        delayNext = false;
        if (delay) {
          await new Promise((resolve) => setTimeout(resolve, 500));
        }
        return previewError
          ? json({ detail: '자막 종료 시각이 영상 길이를 초과합니다.' }, 422)
          : json({
              token: '1'.repeat(64),
              paid_roles: [],
              model_call_budgets: [],
              notice: '',
              selected_inputs: [
                { input: 'transcript', kind: 'saved_subtitle', copy_id: copyId, segments: 1 },
              ],
            });
      }
      if (req.method() !== 'GET') {
        mutations.push({ path: url.pathname, body: req.postDataJSON() });
        return json(
          { code: 'job_busy', detail: '합성 생성 응답 유실: 작업 목록을 확인하세요.' },
          409,
        );
      }
      unexpected.push(`${req.method()} ${url.pathname}`);
      return route.abort();
    });
    const mount = async (page, hash) => {
      await page.goto('https://saved-render.invalid/' + hash);
      await page.addStyleTag({ content: css });
      await page.addScriptTag({ content: bundle.outputFiles[0].text });
    };
    for (const width of [1440, 390]) {
      const page = await context.newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      await page.setViewportSize({ width, height: 950 });
      await mount(page, '#/subtitles/saved');
      await page.getByRole('link', { name: '영상 작업 준비', exact: true }).click();
      await expect(page.getByText('actual original.smi', { exact: true })).toBeVisible();
      assert.equal(page.url().endsWith('#/start/subtitles/' + copyId), true);
      await mount(page, '#/start/subtitles/' + copyId); // full reload: server requery, no browser authority
      await expect(page.getByText('actual original.smi', { exact: true })).toBeVisible();
      const start = page.getByRole('button', { name: '새 작업 만들고 시작', exact: true });
      await expect(start).toBeDisabled();
      await page.getByLabel('원본 영상', { exact: true }).selectOption(videoId);
      await page.getByLabel('저장된 워크플로우', { exact: true }).selectOption(workflowId);
      await page.getByLabel('자막 영상 에이전트', { exact: true }).selectOption('caption');
      await expect(start).toBeEnabled();
      await page.getByLabel('자막 언어', { exact: true }).fill('en');
      await expect(start).toBeEnabled();
      assert.equal(previews.at(-1).options.input_language, 'en');
      if (width === 1440) {
        const prior = previews.length;
        delayNext = true;
        await page.getByLabel('화질', { exact: true }).selectOption('high');
        await expect.poll(() => previews.length).toBeGreaterThan(prior);
        await page.getByLabel('원본 영상', { exact: true }).selectOption('');
        await page.waitForTimeout(650);
        await expect(start).toBeDisabled(); // late old response cannot enable new selection
        await page.getByLabel('원본 영상', { exact: true }).selectOption(videoId);
        await expect(start).toBeEnabled();
      }
      previewError = true;
      await page.getByLabel('영상 코덱', { exact: true }).selectOption('hevc');
      await expect(page.getByRole('alert')).toContainText('영상 길이');
      await expect(start).toBeDisabled();
      previewError = false;
      await page.getByLabel('자막 방식', { exact: true }).selectOption('soft');
      await expect(start).toBeEnabled();
      await start.scrollIntoViewIfNeeded();
      await start.click({ trial: true });
      assert.ok(
        (await page.locator('.saved-subtitle-render .workflow-graph-viewport').boundingBox())
          .height <= 420,
      );
      const box = await start.boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= width);
      assert.equal(
        await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
        false,
      );
      await page.screenshot({
        path: path.join(directory, `preparation-${width}.png`),
        fullPage: true,
      });
      assert.equal(mutations.length, 0); // all reads/inspection/preview are non-operating
      if (width === 390) {
        await start.click();
        await expect(page.getByRole('alert')).toContainText('응답 유실');
        await expect(start).toBeDisabled();
        await page.waitForTimeout(350);
        assert.equal(mutations.length, 1);
        assert.equal(mutations[0].path, '/api/work-entry/create');
        assert.equal(mutations[0].body.options.saved_subtitle.copy_id, copyId);
      }
      await mount(page, '#/subtitles/saved/' + copyId);
      await expect(page.getByRole('link', { name: '영상 작업 준비', exact: true })).toHaveAttribute(
        'href',
        '#/start/subtitles/' + copyId,
      );
      copyError = true;
      await mount(page, '#/start/subtitles/' + copyId);
      await expect(page.getByRole('alert')).toContainText('읽기 실패');
      await expect(
        page.getByRole('button', { name: '새 작업 만들고 시작', exact: true }),
      ).toBeDisabled();
      copyError = false;
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
