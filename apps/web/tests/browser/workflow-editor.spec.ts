import { expect, test } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';

for (const width of [1440, 390]) {
  test(`real ASGI canvas storage journey ${width}`, async ({ page }) => {
    test.setTimeout(180000);
    const evidence = 'docs/evidence/WF-02';
    await fs.mkdir(evidence, { recursive: true });
    const fixture = path.resolve('test-results/wf02-' + randomUUID());
    await fs.mkdir(fixture, { recursive: true });
    const ledger: unknown[] = [];
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    let fail = true,
      external = false;
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await page.addInitScript(() =>
      document.addEventListener('DOMContentLoaded', () => {
        const b = document.createElement('p');
        b.textContent = '안전 격리 ASGI 저장 · 실엔진/운영데이터 아님';
        b.style.cssText = 'background:#fff3c4;color:#403214;padding:8px;text-align:center';
        document.body.prepend(b);
      }),
    );
    await page.route('**/api/**', async (route) => {
      const req = route.request(),
        p = new URL(req.url()).pathname;
      if (
        p.startsWith('/api/settings/workflow-definitions') ||
        p === '/api/settings/node-catalog' || p.startsWith('/api/settings/registered-models')
      ) {
        const method = req.method();
        const payload = method === 'GET' ? undefined : req.postDataJSON();
        const body = {
          method,
          path: p,
          payload,
          fail: method === 'PUT' && fail,
          external: method === 'PUT' && external,
        };
        if (method === 'PUT') {
          fail = false;
          external = false;
        }
        const data = await new Promise<{ status: number; body: unknown; server_revision?: number }>(
          (resolve, reject) => {
            const child = spawn('docker', [
              'run',
              '--rm',
              '-i',
              '--network',
              'none',
              '--read-only',
              '--tmpfs',
              '/tmp:rw,size=256m',
              '-v',
              path.resolve('../..') + ':/src:ro',
              '-v',
              fixture + ':/fixture:rw',
              '-e',
              'PYTHONPATH=/src/packages/shared:/src/apps/api:/src/workers/media',
              process.env.WF02_API_IMAGE || 'video-subtitle-api:renewal-a6083229',
              'python',
              '/src/apps/web/tests/browser/workflow_bridge.py',
            ]);
            let out = '',
              err = '';
            child.stdout.on('data', (v) => (out += v));
            child.stderr.on('data', (v) => (err += v));
            child.on('error', reject);
            child.on('close', (code) => {
              if (code !== 0) {
                reject(new Error(err));
                return;
              }
              try {
                resolve(JSON.parse(out));
              } catch (e) {
                reject(e);
              }
            });
            child.stdin.end(JSON.stringify(body));
          },
        );
        ledger.push({
          method,
          path: p,
          request_revision: payload?.revision,
          status: data.status,
          server_revision: data.server_revision,
        });
        return route.fulfill({ status: data.status, json: data.body });
      }
      if (p === '/api/auth/session') {
        return route.fulfill({ json: { enabled: false, user: null } });
      }
      return route.fulfill({
        json: p.endsWith('videos')
          ? { videos: [] }
          : p.endsWith('video-uploads')
            ? { uploads: [] }
            : { jobs: [] },
      });
    });
    await page.goto('/#/workflow-editor');
    await expect(page.getByRole('heading', { name: '워크플로우 편집기', exact: true })).toBeVisible(
      { timeout: 15000 },
    );
    await page.getByRole('button', { name: '오디오 추출 추가', exact: true }).click();
    await page.getByRole('button', { name: '음성 전처리 추가', exact: true }).click();
    await page.getByLabel('워크플로우 이름', { exact: true }).fill('격리 저장 검증');
    await page.getByRole('button', { name: '서버에서 그래프 검증', exact: true }).click();
    await expect(page.locator('.graph-issues')).toContainText('필수 입력');
    await page.getByRole('button', { name: '외부 출력 video', exact: true }).click();
    await page
      .locator('[data-node-type=extract_audio]')
      .getByRole('button', { name: '입력 video', exact: true })
      .click();
    await page
      .locator('[data-node-type=extract_audio]')
      .getByRole('button', { name: '출력 audio', exact: true })
      .click();
    await page
      .locator('[data-node-type=preprocess_audio]')
      .getByRole('button', { name: '입력 audio', exact: true })
      .click();
    const dragHandle = page.locator('[data-node-type=preprocess_audio] .canvas-drag');
    await dragHandle.scrollIntoViewIfNeeded();
    const beforeDrag = Number(await page.getByLabel('노드 X', { exact: true }).inputValue());
    const box = (await dragHandle.boundingBox())!;
    await page.mouse.move(box.x + 60, box.y + 20);
    await page.mouse.down();
    await page.mouse.move(box.x + 100, box.y + 40, { steps: 5 });
    await page.mouse.up();
    await expect(page.getByLabel('노드 X', { exact: true })).toHaveValue(String(beforeDrag + 40));
    await page.getByLabel('노드 옵션 audio_filter', { exact: true }).selectOption('strong');
    await page.getByLabel('노드 X', { exact: true }).fill('680');
    await page.getByLabel('노드 Y', { exact: true }).fill('240');
    await page.getByRole('button', { name: '편집 정의 저장', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('저장소');
    await expect(page.getByLabel('워크플로우 이름', { exact: true })).toHaveValue('격리 저장 검증');
    await page.getByRole('button', { name: '편집 정의 저장', exact: true }).click();
    await expect(page.getByRole('status').filter({ hasText: '서버 저장 완료' })).toBeVisible({
      timeout: 15000,
    });
    await page.getByLabel('워크플로우 이름', { exact: true }).fill('충돌 직후 유지할 입력');
    external = true;
    await page.getByRole('button', { name: '편집 정의 저장', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('다른 편집');
    await page.getByRole('button', { name: '편집 정의 저장', exact: true }).click();
    await expect(page.getByLabel('워크플로우 이름', { exact: true })).toHaveValue(
      '충돌 직후 유지할 입력',
    );
    await page.getByRole('button', { name: '현재 정의 서버값 다시 불러오기', exact: true }).click();
    await expect(page.getByLabel('워크플로우 이름', { exact: true })).toHaveValue(
      '서버의 다른 편집',
    );
    await page.getByLabel('워크플로우 이름', { exact: true }).fill('저장 후 다시 여는 흐름');
    await page.getByRole('button', { name: '편집 정의 저장', exact: true }).click();
    await expect(page.getByRole('status').filter({ hasText: '서버 저장 완료' })).toBeVisible();
    await page.getByRole('button', { name: '현재 정의 서버값 다시 불러오기', exact: true }).click();
    await expect(page.getByLabel('워크플로우 이름', { exact: true })).toHaveValue(
      '저장 후 다시 여는 흐름',
    );
    await page.locator('[data-node-type=preprocess_audio] .canvas-drag').click();
    await expect(page.getByLabel('노드 옵션 audio_filter', { exact: true })).toHaveValue('strong');
    await expect(page.getByLabel('노드 X', { exact: true })).toHaveValue('680');
    await expect(page.getByLabel('노드 Y', { exact: true })).toHaveValue('240');
    await expect(page.locator('.graph-edge-row')).toHaveCount(2);
    await expect(page.locator('.canvas-node')).toHaveCount(2);
    const handle = page.locator('[data-node-type=preprocess_audio] .canvas-drag');
    await handle.focus();
    await page.keyboard.press('ArrowRight');
    await expect(page.getByLabel('노드 X', { exact: true })).toHaveValue('700');
    await page.getByRole('button', { name: '영상 분석 추가', exact: true }).click();
    await page.getByRole('button', { name: '선택 노드 삭제', exact: true }).click();
    await expect(page.locator('.canvas-node')).toHaveCount(2);
    await page
      .locator('.graph-edge-row')
      .last()
      .getByRole('button', { name: '연결 해제', exact: true })
      .click();
    await page.getByRole('button', { name: '서버에서 그래프 검증', exact: true }).click();
    await expect(page.locator('.graph-issues')).toContainText('필수 입력');
    await page.getByRole('button', { name: '외부 출력 video', exact: true }).click();
    await page
      .locator('[data-node-type=preprocess_audio]')
      .getByRole('button', { name: '입력 audio', exact: true })
      .click();
    await page.getByRole('button', { name: '서버에서 그래프 검증', exact: true }).click();
    await expect(page.locator('.graph-issues')).toContainText('유형');
    await page.screenshot({ path: `${evidence}/invalid-${width}.png` });
    await page
      .locator('.graph-edge-row')
      .last()
      .getByRole('button', { name: '연결 해제', exact: true })
      .click();
    await page
      .locator('[data-node-type=extract_audio]')
      .getByRole('button', { name: '출력 audio', exact: true })
      .click();
    await page
      .locator('[data-node-type=preprocess_audio]')
      .getByRole('button', { name: '입력 audio', exact: true })
      .click();
    await page.getByRole('button', { name: '편집 정의 저장', exact: true }).click();
    await expect(page.getByRole('status').filter({ hasText: '서버 저장 완료' })).toBeVisible();
    await page.getByRole('button', { name: '현재 정의 서버값 다시 불러오기', exact: true }).click();
    await page.locator('[data-node-type=preprocess_audio] .canvas-drag').click();
    await expect(page.getByLabel('노드 X', { exact: true })).toHaveValue('700');
    await page.locator('.editor-canvas').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${evidence}/canvas-${width}.png` });
    const storedDir = path.join(fixture, '.workflow-definitions/local');
    const storedFile = (await fs.readdir(storedDir)).find((n) => n.endsWith('.json'))!;
    const persisted = await fs.readFile(path.join(storedDir, storedFile), 'utf8');
    const value = JSON.parse(persisted);
    expect(value.executable).toBe(false);
    expect(value.nodes).toHaveLength(2);
    expect(value.edges).toHaveLength(2);
    await page
      .getByRole('heading', { name: '워크플로우 편집기', exact: true })
      .scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${evidence}/editor-${width}.png` });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    expect(errors).toEqual([]);
    await fs.writeFile(`${evidence}/stored-${width}.json`, persisted);
    await fs.writeFile(
      `${evidence}/events-${width}.json`,
      JSON.stringify(
        {
          transport:
            'real TestClient/DefinitionStore over network-none Docker; injected 503 and real concurrent write',
          ledger,
          errors,
        },
        null,
        2,
      ),
    );
  });
}
