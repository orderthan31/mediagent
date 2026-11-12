// Photo input preparation only: production React/AuthGate/CSS, OFFLINE response fixtures.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';
const scratch = 'C:/Users/skygg/AppData/Local/hermes/cache/scratch/mediagent-5178-parity';
const photoId = 'd'.repeat(32),
  targetId = 'e'.repeat(32),
  sha = 'a'.repeat(64);
const photo = {
  asset_id: photoId,
  original_filename: 'synthetic nonpersonal long-name '.repeat(3) + '.png',
  media_kind: 'image',
  media_type: 'image/png',
  size_bytes: 80,
  created_at: '2026-11-13T00:00:00Z',
  media: { kind: 'image', format: 'png', width: 8, height: 4, orientation: 1 },
  provenance: { kind: 'verified_upload' },
};
const target = {
  asset_id: targetId,
  original_filename: 'existing target.mp4',
  size_bytes: 123,
  created_at: photo.created_at,
  media: { duration: 12, width: 640, height: 360 },
  provenance: { kind: 'verified_upload' },
};
test('photo + existing video input checks hold execution PC1440/390 (OFFLINE)', async () => {
  const dir = fs.mkdtempSync(path.join(scratch, 'face-input-browser-'));
  const js = await build({
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
  let missing = false,
    forbidden = false,
    delay = false;
  const posts = [],
    unexpected = [],
    errors = [];
  try {
    const context = await browser.newContext({ offline: true });
    await context.route('**/*', async (route) => {
      const req = route.request(),
        url = new URL(req.url());
      const json = (v, status = 200) =>
        route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(v) });
      if (url.origin !== 'https://face-input.invalid') {
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
          user: { id: 'b'.repeat(32), role: 'user', username: 'ordinary' },
          csrf_token: 'csrf',
        });
      }
      if (url.pathname === '/api/capabilities') {
        return json({ features: ['verified_uploads', 'workflows', 'jobs'] });
      }
      if (url.pathname === '/api/videos') {
        return forbidden
          ? json({ detail: '원본 목록 접근 거부' }, 403)
          : json({ videos: [photo, target] });
      }
      if (url.pathname === '/api/videos/' + photoId) {
        return json({ video: photo, jobs: [] });
      }
      if (url.pathname === '/api/videos/' + photoId + '/subtitles') {
        return json({ subtitles: [] });
      }
      if (url.pathname === '/api/jobs') {
        return json({ jobs: [] });
      }
      if (url.pathname === '/api/video-uploads') {
        return json({ uploads: [] });
      }
      if (url.pathname === '/api/work-entry/faceswap-inputs') {
        return json({
          engines: missing
            ? []
            : [{ role: 'faceswap', revision: 3, sha256: sha, engine: 'facefusion-3.9.0' }],
          reason: missing ? '등록 실행기가 없습니다.' : '',
          options: { preset: ['fast', 'balanced', 'quality'], video_codec: ['h264', 'hevc'] },
          execution_ready: false,
          execution_reasons: ['인물 선택과 승인 미리보기가 없습니다.'],
        });
      }
      if (url.pathname === '/api/work-entry/faceswap-inputs/inspect') {
        const body = req.postDataJSON();
        posts.push(body);
        assert.equal(req.headers()['x-csrf-token'], 'csrf');
        assert.equal(body.photo_asset_id, photoId);
        assert.equal(body.target_asset_id, targetId);
        assert.equal('approved' in body, false);
        assert.equal('source_owner_id' in body, false);
        const wait = delay;
        delay = false;
        if (wait) {
          await new Promise((r) => setTimeout(r, 450));
        }
        return json({
          profile: 'faceswap_inputs_v1',
          token: '1'.repeat(64),
          input_ready: body.engine_revision === 3,
          execution_ready: false,
          input_reasons: body.engine_revision === 3 ? [] : ['등록 실행기를 선택하세요.'],
          execution_reasons: ['인물 선택과 승인 미리보기가 없습니다.'],
        });
      }
      unexpected.push(req.method() + ' ' + url.pathname);
      return route.abort();
    });
    const mount = async (page, hash) => {
      await page.goto('https://face-input.invalid/' + hash);
      await page.addStyleTag({ content: css });
      await page.addScriptTag({ content: js.outputFiles[0].text });
    };
    for (const width of [1440, 390]) {
      const page = await context.newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      await page.setViewportSize({ width, height: 950 });
      await mount(page, '#/videos/' + photoId);
      await expect(page.getByRole('heading', { name: '사진 정보', exact: true })).toBeVisible();
      assert.equal(await page.locator('video,audio').count(), 0);
      await page.getByRole('link', { name: '얼굴 합성 입력 준비', exact: true }).click();
      await expect(page.getByLabel('원본 사진', { exact: true })).toHaveValue(photoId);
      const count = posts.length;
      for (const label of ['원본 사진', '대상 영상', '등록 실행기', '품질', '영상 형식']) {
        const control = page.getByLabel(label, { exact: true });
        await control.scrollIntoViewIfNeeded();
        await control.click({ trial: true });
      }
      await page.getByLabel('대상 영상', { exact: true }).selectOption(targetId);
      await page.getByLabel('등록 실행기', { exact: true }).selectOption('3:' + sha);
      await page.getByLabel('품질', { exact: true }).selectOption('balanced');
      await page.getByLabel('영상 형식', { exact: true }).selectOption('h264');
      assert.equal(posts.length, count);
      const check = page.getByRole('button', { name: '입력 확인', exact: true }),
        start = page.getByRole('button', { name: '작업 시작', exact: true });
      await check.click();
      await expect(page.getByText('원본·설정 입력을 확인했습니다.', { exact: true })).toBeVisible();
      await expect(start).toBeDisabled();
      await expect(
        page.getByText('인물 선택과 승인 미리보기가 없습니다.', { exact: true }),
      ).toBeVisible();
      const before = posts.length;
      await page.getByLabel('품질', { exact: true }).selectOption('quality');
      assert.equal(posts.length, before);
      await expect(page.getByText('원본·설정 입력을 확인했습니다.', { exact: true })).toHaveCount(
        0,
      );
      delay = true;
      await check.click();
      await expect.poll(() => posts.length).toBeGreaterThan(before);
      await page.getByLabel('대상 영상', { exact: true }).selectOption('');
      await page.waitForTimeout(550);
      await expect(page.getByText('원본·설정 입력을 확인했습니다.', { exact: true })).toHaveCount(
        0,
      );
      await expect(check).toBeDisabled();
      await page.getByLabel('대상 영상', { exact: true }).selectOption(targetId);
      await check.click();
      await expect(page.getByText('원본·설정 입력을 확인했습니다.', { exact: true })).toBeVisible();
      await check.scrollIntoViewIfNeeded();
      await check.click({ trial: true });
      assert.equal(
        await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
        false,
      );
      await page.screenshot({ path: path.join(dir, 'input-' + width + '.png'), fullPage: true });
      await mount(page, '#/start/faceswap?photo=' + photoId + '&target=' + targetId);
      await expect(page.getByLabel('원본 사진', { exact: true })).toHaveValue(photoId);
      await expect(page.getByLabel('대상 영상', { exact: true })).toHaveValue(targetId);
      await expect(start).toBeDisabled();
      missing = true;
      await mount(page, '#/start/faceswap?photo=' + photoId + '&target=' + targetId);
      await expect(page.getByText('등록 실행기가 없습니다.', { exact: true })).toBeVisible();
      await page.getByLabel('품질', { exact: true }).selectOption('fast');
      await page.getByLabel('영상 형식', { exact: true }).selectOption('h264');
      await check.click();
      await expect(page.getByText('등록 실행기를 선택하세요.', { exact: true })).toBeVisible();
      await expect(start).toBeDisabled();
      missing = false;
      forbidden = true;
      await mount(page, '#/start/faceswap?photo=' + photoId);
      await expect(page.getByRole('alert')).toContainText('접근 거부');
      await expect(check).toBeDisabled();
      forbidden = false;
      await page.close();
    }
    assert.deepEqual(unexpected, []);
    assert.deepEqual(errors, []);
    fs.writeFileSync(
      path.join(dir, 'result.json'),
      JSON.stringify(
        { offline: true, widths: [1440, 390], inputCheckPosts: posts.length, unexpected, errors },
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
  }
});
