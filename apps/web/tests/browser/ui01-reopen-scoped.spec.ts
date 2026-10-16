import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';

for (const width of [1440, 390]) {
  test(`scoped confirmed registry option on node reopen ${width}`, async ({ page }) => {
    test.setTimeout(600000);
    page.setDefaultTimeout(30000);
    const E = 'docs/evidence/UI-01-R1';
    await fs.mkdir(E, { recursive: true });
    const root = path.resolve('test-results/ui01-r1-' + randomUUID());
    await fs.mkdir(root, { recursive: true });
    const errors: string[] = [],
      events: unknown[] = [];
    let drift = false,
      externalEdit = false;
    page.on('pageerror', (e) => errors.push(e.message));
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await page.addInitScript(() =>
      document.addEventListener('DOMContentLoaded', () => {
        const p = document.createElement('p');
        p.textContent = '격리 실제 ASGI·등록모델 binding / 통제 request transport·실추론 아님';
        p.style.cssText =
          'background:#fff3c4;color:#403214;padding:6px;text-align:center;position:static;font-size:12px';
        document.body.prepend(p);
      }),
    );
    await page.route('**/api/**', async (route) => {
      const req = route.request(),
        p = new URL(req.url()).pathname;
      if (!p.startsWith('/api/settings/') && p !== '/api/videos') {
        return route.fulfill({
          json: p.endsWith('session')
            ? { enabled: false, user: null }
            : p.endsWith('video-uploads')
              ? { uploads: [] }
              : { jobs: [] },
        });
      }
      const payload = req.method() === 'GET' ? undefined : req.postDataJSON();
      const data = await new Promise<{
        status: number;
        body: unknown;
        binary?: string;
        content_type?: string;
      }>((resolve, reject) => {
        const driftNow = drift && p.endsWith('/confirm');
        const editNow =
          externalEdit && req.method() === 'PUT' && p.endsWith('/reviews/review_text');
        if (driftNow) {
          drift = false;
        }
        if (editNow) {
          externalEdit = false;
        }
        const c = spawn('docker', [
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
          root + ':/fixture:rw',
          '-e',
          'PYTHONDONTWRITEBYTECODE=1',
          '-e',
          'PYTHONPATH=/src/packages/shared:/src/apps/api:/src/workers/media',
          'video-subtitle-api:renewal-ad1eaa82',
          'python',
          '/src/apps/web/tests/browser/ui01_bridge.py',
        ]);
        let out = '',
          err = '';
        c.stdout.on('data', (v) => (out += v));
        c.stderr.on('data', (v) => (err += v));
        c.on('error', reject);
        c.on('close', (code) => {
          if (code) {
            reject(new Error(err));
          } else {
            try {
              resolve(JSON.parse(out));
            } catch (e) {
              reject(e);
            }
          }
        });
        c.stdin.end(
          JSON.stringify({
            method: req.method(),
            path: p,
            payload,
            drift: driftNow,
            external_edit: editNow,
          }),
        );
      });
      events.push({ method: req.method(), path: p, status: data.status, payload });
      return data.binary
        ? route.fulfill({
            status: data.status,
            body: Buffer.from(data.binary, 'base64'),
            contentType: data.content_type,
          })
        : route.fulfill({ status: data.status, json: data.body });
    });
    await page.goto('/#/serving');
    await page.getByLabel('등록 이름', { exact: true }).fill('검증용 판단 모델');
    await page.getByLabel('등록 provider', { exact: true }).selectOption('openai');
    await page.getByLabel('등록 model', { exact: true }).fill('gpt-4o-mini');
    await page.getByRole('button', { name: '호환 용도 확인', exact: true }).click();
    await page.getByLabel('판단 용도', { exact: true }).check();
    await page.getByRole('button', { name: '모델 등록 저장', exact: true }).click();
    await expect(page.locator('.model-registry')).toContainText('검증용 판단 모델');
    await page.screenshot({ path: `${E}/registry-${width}.png` });
    await page.goto('/#/workflow-editor');
    await page.getByLabel('저장된 정의', { exact: true }).selectOption('a'.repeat(32));
    await page.getByRole('button', { name: '선택 정의 서버값 열기', exact: true }).click();
    await page.locator('.canvas-node[data-id="judge"] .canvas-drag').click();
    const model = page.getByLabel('호환 등록 모델', { exact: true });
    await expect(model.locator('option')).toHaveCount(2);
    const reference = await model.locator('option').nth(1).getAttribute('value');
    await model.selectOption(reference!);
    await page.getByRole('button', { name: '편집 정의 저장', exact: true }).click();
    await expect(page.locator('.workflow-editor [role="status"]')).toContainText('서버 저장 완료');
    await page.reload();
    await page.getByLabel('저장된 정의', { exact: true }).selectOption('a'.repeat(32));
    await page.getByRole('button', { name: '선택 정의 서버값 열기', exact: true }).click();
    await page.locator('.canvas-node[data-id="judge"] .canvas-drag').click();
    await expect(page.getByLabel('호환 등록 모델', { exact: true })).toHaveValue(reference!);
    await expect(model).toBeEnabled();
    const option = model.locator('option:checked');
    await expect(option).toHaveText('검증용 판단 모델 · r1 · openai/gpt-4o-mini');
    await expect(option).toHaveAttribute('value', reference!);
    await expect(page.locator('.node-model-binding')).not.toContainText('등록 항목 미확인');
    const definition = JSON.parse(
      await fs.readFile(
        path.join(root, '.workflow-definitions/local', 'a'.repeat(32) + '.json'),
        'utf8',
      ),
    );
    const [model_id, revision] = reference!.split('@');
    expect(definition.nodes.find((node: { id: string }) => node.id === 'judge').model_ref).toEqual({
      model_id,
      revision: Number(revision),
    });
    await page.locator('.node-model-binding').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/node-reopened-confirmed-${width}.png` });
    expect(errors).toEqual([]);
    await fs.writeFile(
      `${E}/reopen-${width}.json`,
      JSON.stringify(
        {
          mode: 'actual isolated ASGI/registry/definition, no model execution',
          reference,
          selectedOption: await option.textContent(),
          pin: definition.nodes.find((node: { id: string }) => node.id === 'judge').model_ref,
          events,
          errors,
        },
        null,
        2,
      ),
    );
  });
}
