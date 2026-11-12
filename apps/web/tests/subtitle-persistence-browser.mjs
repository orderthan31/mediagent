// Actual authenticated shell/editor and production CSS; synthetic offline API only.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

const scratch = 'C:/Users/skygg/AppData/Local/hermes/cache/scratch/mediagent-5178-parity';
test('save → authoritative requery → list → full reload/reopen → independent copy at PC/390px', async () => {
  const directory = fs.mkdtempSync(path.join(scratch, 'subtitle-persistence-browser-'));
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
    downloadsPath: directory,
  });
  const saved = new Map(),
    writes = [],
    unexpected = [],
    errors = [];
  let rejectSave = false,
    rejectRead = false;
  const original = Buffer.from(
    '\ufeff  \r\n00:00:00,000 --> 00:00:00,800\r\n원래 문구\r\n둘째 줄\r\n',
  );
  const originalHash = createHash('sha256').update(original).digest('hex');
  const smiOriginal = Buffer.from(
    '<SAMI><BODY><SYNC Start=0><P>원래 문구<BR>둘째 줄<SYNC Start=800><P>&nbsp;</BODY></SAMI>',
  );
  const smiHash = createHash('sha256').update(smiOriginal).digest('hex');
  try {
    const context = await browser.newContext({ offline: true, acceptDownloads: true });
    await context.route('**/*', async (route) => {
      const request = route.request(),
        url = new URL(request.url());
      if (url.origin !== 'https://subtitle-persistence.invalid') {
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
      if (url.pathname === '/api/auth/session') {
        return json({
          enabled: true,
          user: { id: 'a'.repeat(32), username: 'ordinary', role: 'user' },
          csrf_token: 'csrf',
        });
      }
      if (url.pathname === '/api/capabilities') {
        return json({ features: [] });
      }
      if (url.pathname === '/api/subtitle-copies' && request.method() === 'POST') {
        assert.equal(request.headers()['x-csrf-token'], 'csrf');
        const body = request.postDataJSON();
        writes.push(body);
        if (rejectSave) {
          return json({ detail: 'AccessDenied: 자막 저장소 쓰기가 거부되었습니다.' }, 403);
        }
        assert.deepEqual(Object.keys(body).sort(), ['filename', 'id', 'srt', 'title']);
        saved.set(body.id, { ...body, created_at: '2026-11-12T01:02:03+00:00', cue_count: 1 });
        const { srt, ...metadata } = saved.get(body.id);
        return json(metadata, 201);
      }
      if (url.pathname === '/api/subtitle-copies') {
        return json({
          copies: [...saved.values()].map(({ srt, ...metadata }) => metadata),
          next_cursor: null,
        });
      }
      const id = url.pathname.match(/^\/api\/subtitle-copies\/([a-f0-9]{32})$/)?.[1];
      if (id && saved.has(id)) {
        return rejectRead
          ? json({ detail: '자막 저장 결과를 읽지 못했습니다.' }, 503)
          : json(saved.get(id));
      }
      unexpected.push(`${request.method()} ${url.pathname}`);
      return route.abort();
    });
    const mount = async (page, hash) => {
      await page.goto('https://subtitle-persistence.invalid/' + hash);
      await page.addStyleTag({ content: css });
      await page.addScriptTag({ content: bundle.outputFiles[0].text });
    };
    for (const width of [1440, 390]) {
      const page = await context.newPage();
      page.on('pageerror', (reason) => errors.push(reason.message));
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await mount(page, '#/subtitles');
      await page.getByLabel('자막 파일 선택', { exact: true }).setInputFiles({
        name: width === 390 ? '직접 원본.smi' : '직접 원본.srt',
        mimeType: 'text/plain',
        buffer: width === 390 ? smiOriginal : original,
      });
      const text = page.getByRole('textbox', { name: '자막 1 문구', exact: true });
      const caption = `편집 ${width} <script>window.__savedXss=1</script>\n줄바꿈`;
      await text.fill(caption);
      await page.getByRole('textbox', { name: '자막 1 시작', exact: true }).fill('00:00:00,125');
      await page.getByRole('textbox', { name: '자막 1 종료', exact: true }).fill('00:00:00,750');
      await page
        .getByRole('textbox', { name: '수정본 제목', exact: true })
        .fill(`저장 제목 ${width}`);
      const save = page.getByRole('button', { name: '수정본 저장', exact: true });
      await save.scrollIntoViewIfNeeded();
      await save.click({ trial: true });
      if (width === 1440) {
        rejectSave = true;
        await save.click();
        await expect(page.getByRole('alert')).toContainText('AccessDenied');
        await expect(page.getByText('수정본을 저장했습니다.', { exact: true })).toHaveCount(0);
        assert.equal(saved.size, 0);
        rejectSave = false;
        rejectRead = true;
        await save.click();
        await expect(page.getByRole('alert')).toContainText('읽지 못했습니다');
        await expect(page.getByText('수정본을 저장했습니다.', { exact: true })).toHaveCount(0);
        rejectRead = false;
      }
      await save.click();
      await expect(page.getByText('수정본을 저장했습니다.', { exact: true })).toBeVisible();
      const id = writes.at(-1).id,
        snapshot = saved.get(id).srt;
      if (width === 1440) {
        assert.equal(writes[0].id, writes[1].id);
        assert.equal(writes[1].id, writes[2].id);
      }
      assert.equal(
        snapshot,
        width === 390
          ? `1\n00:00:00,125 --> 00:00:00,750\n${caption}\n`
          : original
              .toString('utf8')
              .replace('원래 문구\r\n둘째 줄', caption.replace('\n', '\r\n'))
              .replace('00:00:00,000', '00:00:00,125')
              .replace('00:00:00,800', '00:00:00,750'),
      );
      await page.getByRole('link', { name: '저장된 자막', exact: true }).click();
      const reopen = page.getByRole('link', { name: `저장 제목 ${width}`, exact: true });
      await expect(reopen).toBeVisible();
      assert.ok((await reopen.boundingBox()).width <= width);
      assert.ok(
        (await reopen.evaluate((element) => parseFloat(getComputedStyle(element).fontSize))) >= 14,
      );
      await page.screenshot({
        path: path.join(directory, `${width}-saved-list.png`),
        fullPage: true,
      });
      await reopen.click();
      await expect(text).toHaveValue(caption);
      await page.reload();
      await page.addStyleTag({ content: css });
      await page.addScriptTag({ content: bundle.outputFiles[0].text });
      await expect(text).toHaveValue(caption);
      await expect(page.getByRole('textbox', { name: '자막 1 시작', exact: true })).toHaveValue(
        '00:00:00,125',
      );
      await expect(page.getByRole('textbox', { name: '자막 1 종료', exact: true })).toHaveValue(
        '00:00:00,750',
      );
      assert.equal(await page.getByLabel('자막 파일 선택', { exact: true }).inputValue(), '');
      await text.scrollIntoViewIfNeeded();
      assert.ok(
        (await text.evaluate((element) => parseFloat(getComputedStyle(element).fontSize))) >= 14,
      );
      await page.screenshot({
        path: path.join(directory, `${width}-reopened-editor.png`),
        fullPage: true,
      });
      for (const format of ['srt', 'smi']) {
        await page.getByRole('combobox', { name: '출력 형식', exact: true }).selectOption(format);
        const download = page.waitForEvent('download');
        await page
          .getByRole('button', { name: format.toUpperCase() + ' 받기', exact: true })
          .click();
        const received = await download;
        assert.equal(received.suggestedFilename(), `직접 원본-수정본.${format}`);
        const target = path.join(directory, `${width}.${format}`);
        await received.saveAs(target);
        const actual = fs.readFileSync(target, 'utf8');
        if (format === 'srt') {
          assert.equal(actual, snapshot);
        } else {
          assert.match(actual, /SYNC Start="125"/);
          assert.match(actual, /&lt;script&gt;/);
          assert.match(actual, /<BR>줄바꿈/);
        }
      }
      await text.fill('새 별도 수정본');
      await save.click();
      await expect(page.getByText('수정본을 저장했습니다.', { exact: true })).toBeVisible();
      assert.notEqual(writes.at(-1).id, id);
      assert.equal(saved.get(id).srt, snapshot);
      assert.equal(await page.evaluate(() => window.__savedXss), undefined);
      assert.equal(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
        true,
      );
      assert.ok((await page.evaluate(() => scrollY)) > 0);
      await page.close();
    }
    assert.equal(createHash('sha256').update(original).digest('hex'), originalHash);
    assert.equal(createHash('sha256').update(smiOriginal).digest('hex'), smiHash);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
  }
});
