// Real shell/file input/editor/downloads; offline synthetic HTTPS only.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

const scratch = 'C:/Users/skygg/AppData/Local/hermes/cache/scratch/mediagent-5178-parity';
test('ordinary user can open direct subtitle editing without a job, video or runtime capability', async () => {
  const directory = fs.mkdtempSync(path.join(scratch, 'direct-subtitle-downloads-'));
  const approvedPath = path.join(scratch, 'normal-flow-fixture/normal-input.srt');
  const approved = fs.readFileSync(approvedPath);
  assert.equal(approved.length, 102);
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
  const browser = await chromium.launch({
    channel: process.platform === 'win32' ? 'msedge' : undefined,
    headless: true,
    downloadsPath: directory,
  });
  const calls = [],
    unexpected = [],
    errors = [];
  try {
    const context = await browser.newContext({ offline: true, acceptDownloads: true });
    await context.route('**/*', async (route) => {
      const request = route.request(),
        url = new URL(request.url());
      if (url.origin !== 'https://direct-subtitle.invalid') {
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
      calls.push({ path: url.pathname, method: request.method() });
      const json = (value) =>
        route.fulfill({ contentType: 'application/json', body: JSON.stringify(value) });
      if (url.pathname === '/api/auth/session') {
        return json({
          enabled: true,
          user: { id: 'unit-reader', username: 'unit-reader', role: 'user' },
        });
      }
      if (url.pathname === '/api/capabilities') {
        return json({ features: [] });
      }
      unexpected.push(url.pathname);
      return route.abort();
    });
    const css = fs
      .readdirSync('dist/assets')
      .filter((name) => name.endsWith('.css'))
      .map((name) => fs.readFileSync(path.join('dist/assets', name), 'utf8'))
      .join('\n');
    for (const width of [1440, 390]) {
      const page = await context.newPage();
      page.on('pageerror', (error) => errors.push(error.message));
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await page.goto('https://direct-subtitle.invalid/#/jobs');
      await page.addStyleTag({ content: css });
      await page.addScriptTag({ content: bundle.outputFiles[0].text });
      if (width === 390) {
        await page.getByRole('button', { name: '메뉴 열기', exact: true }).click();
      }
      await expect(page.getByRole('link', { name: '자막 파일 편집', exact: true })).toBeVisible();
      await page.getByRole('link', { name: '자막 파일 편집', exact: true }).click();
      await expect(
        page.getByRole('heading', { name: '자막 파일 편집', exact: true }),
      ).toBeVisible();
      await expect(page.getByLabel('SRT 파일 선택', { exact: true })).toHaveAttribute(
        'accept',
        '.srt',
      );
      await expect(page.getByRole('button', { name: 'SRT 받기', exact: true })).toBeDisabled();
      const chooser = page.getByLabel('SRT 파일 선택', { exact: true });
      await chooser.setInputFiles(approvedPath);
      const firstText = page.getByRole('textbox', { name: '자막 1 문구', exact: true });
      const firstStart = page.getByRole('textbox', { name: '자막 1 시작', exact: true });
      const firstEnd = page.getByRole('textbox', { name: '자막 1 종료', exact: true });
      const format = page.getByRole('combobox', { name: '출력 형식', exact: true });
      await expect(firstText).toHaveValue('입력 자막 첫 줄');
      await expect(firstStart).toHaveValue('00:00:00,000');
      await expect(firstEnd).toHaveValue('00:00:00,800');
      await expect(page.locator('.direct-subtitle-filename')).toHaveText('normal-input.srt');
      const receive = async (extension, filename) => {
        const waiting = page.waitForEvent('download');
        await page
          .getByRole('button', { name: extension.toUpperCase() + ' 받기', exact: true })
          .click();
        const download = await waiting;
        assert.equal(download.suggestedFilename(), filename);
        const target = path.join(directory, `${width}-${Date.now()}-${filename}`);
        await download.saveAs(target);
        return fs.readFileSync(target);
      };
      assert.deepEqual(await receive('srt', 'normal-input-수정본.srt'), approved);
      const caption = '직접 <script>window.__directXss=1</script> & 문구\n둘째 줄';
      await firstText.fill(caption);
      await firstStart.fill('00:00:00,125');
      await firstEnd.fill('00:00:00,750');
      const expected = approved
        .toString('utf8')
        .replace('입력 자막 첫 줄', caption)
        .replace('00:00:00,000', '00:00:00,125')
        .replace('00:00:00,800', '00:00:00,750');
      assert.deepEqual(await receive('srt', 'normal-input-수정본.srt'), Buffer.from(expected));
      await format.selectOption('smi');
      const smi = (await receive('smi', 'normal-input-수정본.smi')).toString('utf8');
      assert.match(smi, /SYNC Start="125"/);
      assert.match(smi, /SYNC Start="750"/);
      assert.match(smi, /SYNC Start="1000"/);
      assert.match(smi, /SYNC Start="1800"/);
      assert.match(smi, /&lt;script&gt;/);
      assert.match(smi, /&amp; 문구<BR>둘째 줄/);
      assert.equal(await page.evaluate(() => window.__directXss), undefined);
      for (const value of ['NaN', 'Infinity', '-00:00:00,100']) {
        await firstStart.fill(value);
        await expect(firstStart).toHaveAttribute('aria-invalid', 'true');
        await expect(page.getByRole('button', { name: 'SMI 받기', exact: true })).toBeDisabled();
      }
      await firstStart.fill('00:00:00,125');
      await firstEnd.fill('00:00:00,100');
      await expect(firstEnd).toHaveAttribute('aria-invalid', 'true');
      await firstEnd.fill('00:00:01,500');
      await expect(page.getByRole('button', { name: 'SMI 받기', exact: true })).toBeDisabled();
      await expect(page.getByRole('alert')).toContainText('SMI는 겹치거나');
      await format.selectOption('srt');
      await expect(page.getByRole('button', { name: 'SRT 받기', exact: true })).toBeEnabled();
      await expect(firstEnd).toHaveValue('00:00:01,500');
      await expect(page.getByRole('textbox', { name: '자막 2 시작', exact: true })).toHaveValue(
        '00:00:01,000',
      );
      await firstText.fill('');
      await expect(firstText).toHaveAttribute('aria-invalid', 'true');
      await expect(page.getByRole('button', { name: 'SRT 받기', exact: true })).toBeDisabled();

      const long =
        '\ufeff' +
        Array.from(
          { length: 121 },
          (_, i) =>
            `${i === 0 ? 'cue-a' : i === 1 ? ' ' : i + 1}\r\n00:00:00,000 --> 00:00:01,000\r\n${'합성 문구'.repeat(80)} ${i + 1}\r\n`,
        ).join('\r\n');
      await chooser.setInputFiles({
        name: 'long.srt',
        mimeType: 'application/x-subrip',
        buffer: Buffer.from(long),
      });
      await expect(firstText).toHaveValue(/합성 문구/);
      await expect(firstStart).toHaveValue('00:00:00,000'); // New source resets both text and times.
      await page.getByRole('combobox', { name: '페이지 선택', exact: true }).selectOption('7');
      await expect(page.getByRole('textbox', { name: '자막 121 문구', exact: true })).toHaveValue(
        /121$/,
      );
      await page.getByRole('combobox', { name: '페이지 선택', exact: true }).selectOption('1');
      const twentieth = page.getByRole('textbox', { name: '자막 20 문구', exact: true });
      await twentieth.scrollIntoViewIfNeeded();
      await twentieth.click();
      const scroll = await twentieth.evaluate((node) => {
        let top = window.scrollY;
        for (let element = node; element; element = element.parentElement) {
          top = Math.max(top, element.scrollTop);
        }
        return top;
      });
      assert.ok(scroll > 0, 'production page really scrolled');
      for (const control of [
        twentieth,
        page.getByRole('textbox', { name: '자막 20 시작', exact: true }),
        page.getByRole('textbox', { name: '자막 20 종료', exact: true }),
        format,
        page.getByRole('button', { name: 'SRT 받기', exact: true }),
      ]) {
        if ((await control.getAttribute('type')) === 'button') {
          await control.click({ trial: true });
        } else {
          await control.scrollIntoViewIfNeeded();
        }
        const box = await control.boundingBox();
        assert.ok(
          (await control.evaluate((node) => Number.parseFloat(getComputedStyle(node).fontSize))) >=
            14,
        );
        assert.ok(
          box &&
            box.x >= 0 &&
            box.x + box.width <= width &&
            box.y >= 0 &&
            box.y + box.height <= (width === 390 ? 844 : 1000),
          JSON.stringify(box),
        );
      }
      assert.equal(await page.locator('.direct-subtitle-page header').count(), 0);
      assert.deepEqual(await receive('srt', 'long-수정본.srt'), Buffer.from(long));

      // Native File reads cannot be cancelled; source sequence must reject a late old read.
      await page.evaluate(() => {
        const original = File.prototype.arrayBuffer;
        File.prototype.arrayBuffer = function () {
          if (this.name === 'slow.srt') {
            return new Promise((resolve) => {
              window.__releaseDirect = async () => resolve(await original.call(this));
            });
          }
          return original.call(this);
        };
      });
      await chooser.setInputFiles({
        name: 'slow.srt',
        mimeType: 'application/x-subrip',
        buffer: approved,
      });
      await expect(page.getByRole('status')).toContainText('자막 불러오는 중');
      await expect.poll(() => page.evaluate(() => Boolean(window.__releaseDirect))).toBe(true);
      const replacement = '17\n00:00:03,000 --> 00:00:04,000\n새 파일 문구\n';
      await chooser.setInputFiles({
        name: 'replacement.srt',
        mimeType: 'application/x-subrip',
        buffer: Buffer.from(replacement),
      });
      await expect(firstText).toHaveValue('새 파일 문구');
      await page.evaluate(async () => {
        await window.__releaseDirect();
        await new Promise(requestAnimationFrame);
      });
      await expect(firstText).toHaveValue('새 파일 문구');
      await expect(firstStart).toHaveValue('00:00:03,000');
      for (const invalid of [Buffer.from('{}'), Buffer.alloc(0), Buffer.from([255])]) {
        await chooser.setInputFiles({
          name: 'invalid.srt',
          mimeType: 'application/x-subrip',
          buffer: invalid,
        });
        await expect(page.getByRole('alert')).toBeVisible();
        await expect(firstText).toHaveCount(0);
        await expect(page.getByRole('button', { name: 'SRT 받기', exact: true })).toBeDisabled();
      }
      assert.deepEqual(fs.readFileSync(approvedPath), approved);
      await page.close();
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpected, []);
    assert.ok(calls.every((call) => call.method === 'GET'));
  } finally {
    await browser.close();
    assert.ok(path.resolve(directory).startsWith(path.resolve(scratch) + path.sep));
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
