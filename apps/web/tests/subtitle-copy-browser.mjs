// Real workspace, authenticated file-read helper and editor; synthetic offline sources only.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

const scratch = 'C:/Users/skygg/AppData/Local/hermes/cache/scratch/mediagent-5178-parity';
const jobId = '1'.repeat(32),
  runId = '2'.repeat(32),
  otherRun = '3'.repeat(32);
const root = `/api/renewal/jobs/${jobId}`;
const primaryPath = `${root}/artifacts/${runId}/subtitles`;
const otherPath = `${root}/artifacts/${otherRun}/subtitles`;
const trackPath = `${root}/subtitle-outputs/${otherRun}/translated.pt-BR/srt`;
const fixtureText =
  '\ufeff' +
  Array.from(
    { length: 121 },
    (_, i) =>
      `${i === 0 ? '90071992547409931234567890' : i + 1}\r\n00:00:00,001 --> 00:00:04,999\r\n  ${i === 0 ? '<script>window.__xss=1</script>' : '합성 자막 ' + (i + 1)}${' 문구'.repeat(40)}  \r\n둘째 줄\t\r\n`,
  ).join('\r\n');
const shortText = '17\n00:00:01,000 --> 00:00:02,000\n다른 파일 문구\n';
const reference = {
  type: 'subtitle',
  bytes: Buffer.byteLength(fixtureText),
  sha256: 'a'.repeat(64),
  storage_key: 'PRIVATE TEST LOCATOR',
};
const definition = {
  id: 'unit-definition',
  catalog_version: 2,
  revision: 1,
  inputs: {},
  nodes: [{ id: 'subtitle', type: 'subtitle_file_agent', position: { x: 0, y: 0 }, options: {} }],
  edges: [],
};
const job = {
  id: jobId,
  ticket_number: 42,
  revision: 1,
  status: 'failed',
  display_status: 'failed',
  parent_id: null,
  access: { can_manage: false },
  reviews: [],
  artifact_manifest: { entry_count: 4 },
  snapshot: {
    asset: { asset_id: '4'.repeat(32), original_filename: '원래 표시 이름.mp4' },
    definition,
    tool_definition: {
      nodes: [
        { id: 'subtitle__generate', type: 'generate_subtitle', options: {} },
        { id: 'subtitle__outputs', type: 'subtitle_outputs', options: {} },
      ],
      edges: [],
    },
  },
  agent_workflow: {
    definition,
    legacy_projection: false,
    edges: {},
    nodes: [
      {
        id: 'subtitle',
        type: 'subtitle_file_agent',
        label: '자막 파일',
        state: 'completed',
        status_label: '완료',
        reason: '',
        selected_tool_id: 'subtitle__generate',
        tools: [
          {
            node_id: 'subtitle__generate',
            role: 'generate_subtitle',
            label: '자막 생성',
            state: 'completed',
            reason: '',
            run_id: runId,
          },
          {
            node_id: 'subtitle__outputs',
            role: 'subtitle_outputs',
            label: '언어별 자막',
            state: 'completed',
            reason: '',
            run_id: otherRun,
          },
        ],
        outputs: [
          {
            name: 'subtitles',
            run_id: runId,
            node_id: 'subtitle__generate',
            port: 'subtitles',
            type: 'subtitle',
          },
        ],
      },
    ],
  },
  runs: [
    {
      id: runId,
      node_id: 'subtitle__generate',
      node_type: 'generate_subtitle',
      status: 'completed',
      options: {},
      inputs: {},
      result: { outputs: { subtitles: reference, sami: reference } },
    },
    {
      id: otherRun,
      node_id: 'subtitle__outputs',
      node_type: 'subtitle_outputs',
      status: 'completed',
      options: {},
      inputs: {},
      result: {
        outputs: { subtitles: reference, manifest: { ...reference, type: 'artifact_manifest' } },
      },
    },
  ],
};

test('accepted SRT copy editor downloads exact bytes and works in production CSS at PC/390px offline', async () => {
  const directory = fs.mkdtempSync(path.join(scratch, 'subtitle-copy-downloads-'));
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
  let mode = 'success',
    release;
  try {
    const context = await browser.newContext({ offline: true, acceptDownloads: true });
    await context.addInitScript(() => {
      window.__xss = 0;
      window.__aborts = [];
      const original = window.fetch;
      window.fetch = (url, init) => {
        init?.signal?.addEventListener('abort', () => window.__aborts.push(String(url)));
        return original(url, init);
      };
    });
    await context.route('**/*', async (route) => {
      const request = route.request(),
        url = new URL(request.url());
      if (url.origin !== 'https://subtitle-copy.invalid') {
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
      calls.push({ path: url.pathname + url.search, method: request.method() });
      assert.equal(request.method(), 'GET');
      const json = (value) =>
        route.fulfill({ contentType: 'application/json', body: JSON.stringify(value) });
      if (url.pathname === '/api/auth/session') {
        return json({
          enabled: true,
          user: { id: 'unit-reader', username: 'unit-reader', role: 'user' },
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
      if (url.pathname === root) {
        return json(job);
      }
      if (url.pathname === '/api/work-entry/catalog') {
        return json({
          nodes: [
            { id: 'subtitle_file_agent', label: '자막 파일', inputs: {}, outputs: {}, options: {} },
          ],
        });
      }
      if (url.pathname === root + '/projection-recoveries') {
        return json({ can_manage: false, candidates: [], operations: [] });
      }
      if (url.pathname.endsWith('/logs')) {
        return json({
          run_id: url.pathname.split('/').at(-2),
          state: 'completed',
          has_more: false,
          entries: [],
          console: { available: false, truncated: false, lines: [] },
        });
      }
      if (url.pathname === root + '/subtitle-outputs') {
        return json({
          outputs: [
            {
              run_id: otherRun,
              review: null,
              tracks: {
                'translated.pt-BR': {
                  language: 'pt-BR',
                  transcript: { type: 'transcript', sha256: 'a'.repeat(64) },
                  files: {
                    srt: { filename: 'translated.pt-BR.srt', reference },
                    smi: { filename: 'translated.pt-BR.smi', reference },
                  },
                },
              },
            },
          ],
        });
      }
      if ([primaryPath, otherPath, trackPath].includes(url.pathname)) {
        const selectedMode = mode;
        if (selectedMode === 'defer' && url.pathname === primaryPath) {
          await new Promise((resolve) => {
            release = resolve;
          });
        }
        if (selectedMode === 'error') {
          return route.fulfill({ status: 404, body: 'not available' });
        }
        const filename =
          url.pathname === trackPath
            ? 'translated.pt-BR.srt'
            : `${url.pathname === primaryPath ? runId : otherRun}-subtitles.srt`;
        try {
          return await route.fulfill({
            contentType: selectedMode === 'json' ? 'application/json' : 'text/plain; charset=utf-8',
            headers: {
              'Content-Disposition': `attachment; filename="${selectedMode === 'wrong' ? 'wrong.srt' : filename}"`,
            },
            body: Buffer.from(
              selectedMode === 'invalid'
                ? '1\nmissing time\ntext'
                : url.pathname === primaryPath
                  ? fixtureText
                  : shortText,
              'utf8',
            ),
          });
        } catch {
          return;
        } // A deliberately aborted old response cannot update the editor.
      }
      unexpected.push(url.pathname);
      return route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: '{"detail":"offline unexpected read"}',
      });
    });
    const css = fs
      .readdirSync('dist/assets')
      .filter((name) => name.endsWith('.css'))
      .map((name) => fs.readFileSync(path.join('dist/assets', name), 'utf8'))
      .join('\n');
    for (const width of [1440, 390]) {
      mode = 'success';
      const page = await context.newPage();
      page.on('pageerror', (error) => errors.push(error.message));
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await page.goto(`https://subtitle-copy.invalid/#/jobs/${jobId}`);
      await page.addStyleTag({ content: css });
      await page.addScriptTag({ content: bundle.outputFiles[0].text });
      const files = page.getByRole('region', { name: '결과 파일', exact: true });
      const primary = files
        .locator('li')
        .filter({ has: page.locator(`a[href="${primaryPath}"]`) })
        .getByRole('button', { name: '자막 수정', exact: true });
      const other = files
        .locator('li')
        .filter({ has: page.locator(`a[href="${otherPath}"]`) })
        .getByRole('button', { name: '자막 수정', exact: true });
      await expect(primary).toBeVisible();
      await expect(files.locator(`a[href="${root}/manifest?download=true"]`)).toBeVisible();
      assert.equal(await files.getByRole('button', { name: '자막 수정', exact: true }).count(), 2);
      await primary.click();
      const editor = page.getByRole('dialog', { name: '자막 수정', exact: true });
      const first = editor.getByRole('textbox', {
        name: '자막 90071992547409931234567890 문구',
        exact: true,
      });
      await expect(first).toHaveValue(/<script>/);
      assert.equal(await page.evaluate(() => window.__xss), 0);
      assert.equal(await editor.locator('script').count(), 0);
      const saveCopy = async (expected) => {
        const pending = page.waitForEvent('download');
        await editor.getByRole('button', { name: '수정본 받기', exact: true }).click();
        const download = await pending;
        assert.equal(download.suggestedFilename(), `${runId}-subtitles-수정본.srt`);
        const target = path.join(directory, `${width}-${Date.now()}.srt`);
        await download.saveAs(target);
        assert.deepEqual(fs.readFileSync(target), Buffer.from(expected, 'utf8'));
      };
      await saveCopy(fixtureText);
      const original = await first.inputValue();
      await first.fill('');
      await expect(first).toHaveAttribute('aria-invalid', 'true');
      await expect(editor.getByRole('button', { name: '수정본 받기', exact: true })).toBeDisabled();
      await first.fill(original.replace('<script>window.__xss=1</script>', '직접 수정한 문구'));
      await saveCopy(fixtureText.replace('<script>window.__xss=1</script>', '직접 수정한 문구'));
      await editor.getByRole('combobox', { name: '페이지 선택', exact: true }).selectOption('7');
      const last = editor.getByRole('textbox', { name: '자막 121 문구', exact: true });
      await expect(last).toHaveValue(/합성 자막 121/);
      await editor.getByRole('combobox', { name: '페이지 선택', exact: true }).selectOption('1');
      const twentieth = editor.getByRole('textbox', { name: '자막 20 문구', exact: true });
      await twentieth.scrollIntoViewIfNeeded();
      assert.ok((await editor.locator('.srt-copy-body').evaluate((node) => node.scrollTop)) > 0);
      await twentieth.click();
      const headingStyle = await editor.locator('.srt-copy-heading').evaluate((node) => ({
        position: getComputedStyle(node).position,
        zIndex: getComputedStyle(node).zIndex,
      }));
      assert.deepEqual(headingStyle, { position: 'static', zIndex: 'auto' });
      for (const button of ['수정본 받기', '닫기']) {
        const control = editor.getByRole('button', { name: button, exact: true });
        await control.click({ trial: true });
        const box = await control.boundingBox();
        assert.ok(
          box &&
            box.x >= 0 &&
            box.x + box.width <= width &&
            box.y >= 0 &&
            box.y + box.height <= (width === 390 ? 844 : 1000),
          JSON.stringify(box),
        );
      }
      const box = await editor.boundingBox();
      assert.ok(box && box.x >= 0 && box.x + box.width <= width);
      await editor.getByRole('button', { name: '닫기', exact: true }).click();
      await primary.click();
      await expect(first).toHaveValue(original); // Closing discards local edits.
      await editor.getByRole('button', { name: '닫기', exact: true }).click();
      for (const failure of ['error', 'json', 'wrong', 'invalid']) {
        mode = failure;
        await primary.click();
        await expect(editor.getByRole('alert')).toBeVisible();
        assert.equal(await editor.getByRole('textbox').count(), 0);
        await expect(
          editor.getByRole('button', { name: '수정본 받기', exact: true }),
        ).toBeDisabled();
        await editor.getByRole('button', { name: '닫기', exact: true }).click();
      }
      mode = 'defer';
      release = undefined;
      await primary.click();
      await expect(editor).toContainText('자막 불러오는 중');
      await expect.poll(() => Boolean(release)).toBe(true);
      await editor.getByRole('button', { name: '닫기', exact: true }).click();
      await expect
        .poll(() =>
          page.evaluate(() =>
            window.__aborts.some((url) => url.includes('/artifacts/') && url.includes('subtitles')),
          ),
        )
        .toBe(true);
      mode = 'success';
      await other.click();
      await expect(editor.getByRole('textbox')).toHaveValue('다른 파일 문구');
      release();
      await expect(editor.getByRole('textbox')).toHaveValue('다른 파일 문구');
      await editor.getByRole('button', { name: '닫기', exact: true }).click();
      const tracks = page.getByRole('region', { name: '언어별 자막 산출물' });
      assert.equal(await tracks.getByRole('button', { name: '자막 수정', exact: true }).count(), 1);
      await tracks.getByRole('button', { name: '자막 수정', exact: true }).click();
      await expect(editor).toContainText('translated.pt-BR.srt');
      await expect(editor.getByRole('textbox')).toHaveValue('다른 파일 문구');
      await editor.press('Escape');
      await expect(editor).toHaveCount(0);
      await page.locator('[data-node-id="subtitle"] .workflow-node-heading').click();
      const detail = page.getByRole('dialog', { name: '노드 실행 결과', exact: true });
      await detail.getByRole('button', { name: '자막 수정', exact: true }).click();
      await expect(first).toHaveValue(original);
      assert.ok(
        (await first.evaluate((node) => Number.parseFloat(getComputedStyle(node).fontSize))) >= 14,
      );
      await editor.press('Escape');
      await expect(editor).toHaveCount(0);
      await expect(detail).toBeVisible();
      await page.close();
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpected, []);
    assert.ok(calls.length && calls.every((call) => call.method === 'GET'));
    assert.ok(calls.some((call) => call.path === primaryPath + '?download=true'));
    assert.ok(calls.some((call) => call.path === trackPath));
  } finally {
    await browser.close();
    assert.ok(path.resolve(directory).startsWith(path.resolve(scratch) + path.sep));
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
