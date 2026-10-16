import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';

for (const width of [1440, 390]) {
  test(`registered models, node binding and workflow centered work ${width}`, async ({ page }) => {
    test.setTimeout(600000);
    page.setDefaultTimeout(30000);
    const E = 'docs/evidence/UI-01';
    await fs.mkdir(E, { recursive: true });
    const root = path.resolve('test-results/ui01-' + randomUUID());
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
    await page.goto('/#/start');
    await expect(page.getByRole('heading', { name: '작업 시작', exact: true })).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByRole('combobox', { name: '실행기 유형', exact: true })).toHaveCount(0);
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
    await expect(page.getByLabel('호환 등록 모델', { exact: true })).toBeEnabled();
    await expect(page.getByLabel('호환 등록 모델', { exact: true })).toHaveValue(reference!);
    await expect(
      page.getByLabel('호환 등록 모델', { exact: true }).locator('option:checked'),
    ).toHaveText('검증용 판단 모델 · r1 · openai/gpt-4o-mini');
    await expect(page.locator('.node-model-binding')).not.toContainText('등록 항목 미확인');
    await page.locator('.node-model-binding').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/node-binding-${width}.png` });
    await page.goto('/#/start');
    await page.getByLabel('입력 영상', { exact: true }).selectOption('b'.repeat(32));
    await page.getByLabel('저장 워크플로우', { exact: true }).selectOption('a'.repeat(32));
    await expect(page.locator('.workflow-start')).toContainText('검증용 판단 모델');
    await page.getByRole('button', { name: '계획·비용 확인으로', exact: true }).click();
    await expect(page.locator('.start-plan')).toContainText('아직 티켓');
    await page.locator('.start-plan').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/before-ticket-plan-${width}.png` });
    expect(
      await fs.readdir(path.join(root, '.workflow-work-tickets')).catch(() => []),
    ).toHaveLength(0);
    await page.getByLabel('계획의 모델 호출 확인', { exact: true }).check();
    await page.getByRole('button', { name: '확인하고 티켓 만들기', exact: true }).click();
    await expect(page.getByRole('heading', { name: '작업 티켓', exact: true })).toBeVisible();
    const run = async (continuation = false) => {
      await page.getByRole('button', { name: '실행 계획 불러오기', exact: true }).click();
      const paid = page.getByLabel('유료 모델 호출 확인', { exact: true });
      if (await paid.isEnabled()) {
        await paid.check();
      }
      await page.getByRole('button', { name: '계획 확인 저장', exact: true }).click();
      const done = page.waitForResponse(
        (r) =>
          r.request().method() === 'POST' &&
          /\/work-tickets\/[0-9a-f]{32}\/(start|continue)$/.test(new URL(r.url()).pathname),
      );
      await page
        .getByRole('button', {
          name: continuation ? '확인한 계획 이어 실행 요청' : '확인한 계획 실행 요청',
          exact: true,
        })
        .click();
      expect((await done).status()).toBe(200);
      await expect(page.locator('.workflow-tickets > [role="status"]')).toContainText(
        '실행 응답을 저장',
        { timeout: 20000 },
      );
    };
    await run();
    await expect(page.locator('[data-node-id="judge"] .decision-evidence')).toContainText(
      '선택 경로 a',
    );
    await page.locator('[data-node-id="judge"]').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/bound-judgment-${width}.png` });
    await run(true);
    await expect(page.locator('.ticket-state')).toHaveText('사람 검수 대기');
    await page.getByRole('button', { name: '현재 revision/SHA 명시 승인', exact: true }).click();
    await expect(page.locator('[data-node-id="gate"]')).toContainText('자료 확정');
    await run(true);
    await expect(page.locator('.ticket-state')).toHaveText('선택 단계 완료');
    await page.screenshot({ path: `${E}/completed-${width}.png` });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBeTruthy();
    expect(errors).toEqual([]);
    const tickets = await fs.readdir(path.join(root, '.workflow-work-tickets/local'));
    const ids = tickets.filter((x) => /^[0-9a-f]{32}$/.test(x));
    expect(ids).toHaveLength(1);
    await fs.copyFile(
      path.join(root, '.workflow-work-tickets/local', ids[0], 'ticket.json'),
      `${E}/stored-${width}.json`,
    );
    const definition = await fs.readFile(
      path.join(root, '.workflow-definitions/local', 'a'.repeat(32) + '.json'),
      'utf8',
    );
    expect(
      JSON.parse(definition).nodes.find((n: { id: string }) => n.id === 'judge').model_ref,
    ).toBeTruthy();
    await fs.writeFile(`${E}/definition-${width}.json`, definition);
    // Change entity revision; the saved definition and existing ticket must keep r1.
    await page.goto('/#/serving');
    await page.getByRole('button', { name: '수정 검증용 판단 모델', exact: true }).click();
    await page.getByLabel('등록 model', { exact: true }).fill('gpt-4o');
    await page.getByRole('button', { name: '호환 용도 확인', exact: true }).click();
    await page.getByLabel('판단 용도', { exact: true }).check();
    await page.getByRole('button', { name: '모델 등록 저장', exact: true }).click();
    await expect(
      page.getByRole('heading', { name: '검증용 판단 모델 · r2', exact: true }),
    ).toBeVisible();
    await page.screenshot({ path: `${E}/new-revision-keeps-pin-${width}.png` });
    await page.goto('/#/start');
    await page.getByLabel('입력 영상', { exact: true }).selectOption('b'.repeat(32));
    await page.getByLabel('저장 워크플로우', { exact: true }).selectOption('a'.repeat(32));
    await expect(page.locator('.workflow-start')).toContainText('r1 · openai/gpt-4o-mini');
    await page.getByRole('button', { name: '계획·비용 확인으로', exact: true }).click();
    await page.getByLabel('계획의 모델 호출 확인', { exact: true }).check();
    const created = page.waitForResponse(
      (r) =>
        r.request().method() === 'POST' &&
        new URL(r.url()).pathname.endsWith('/settings/work-entry/create'),
    );
    await page.getByRole('button', { name: '확인하고 티켓 만들기', exact: true }).click();
    const pending = await (await created).json();
    expect(pending.model_bindings.judge.model).toBe('gpt-4o-mini');
    await page.goto('/#/serving');
    await page.getByRole('button', { name: '사용 중지', exact: true }).click();
    await expect(page.locator('.model-registry [role="status"]')).toContainText('사용 중지');
    const oldConfirmationStatus = await page.evaluate(async (ticket) => {
      const response = await fetch(`/api/settings/work-tickets/${ticket.id}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          request_id: crypto.randomUUID(),
          revision: ticket.revision,
          token: ticket.confirmation.token,
        }),
      });
      return response.status;
    }, pending);
    expect(oldConfirmationStatus).toBe(409);
    await page.goto('/#/work-tickets');
    await page.getByRole('button', { name: new RegExp(pending.id.slice(0, 6)) }).click();
    await expect(page.locator('.node-model-snapshot')).toContainText('사용 중지');
    await run();
    await expect(page.locator('[data-node-id="judge"]')).toContainText('ModelUnavailable');
    await expect(page.locator('[data-node-id="independent"]')).toContainText('성공');
    await page.locator('[data-node-id="judge"]').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/disabled-old-ticket-${width}.png` });
    const trace = (await fs.readFile(path.join(root, 'actual-trace.jsonl'), 'utf8'))
      .trim()
      .split('\n')
      .map((line) => JSON.parse(line));
    expect(trace.filter((event) => event.registered_model_call)).toHaveLength(1);
    await fs.writeFile(
      `${E}/registered-binding-trace-${width}.json`,
      JSON.stringify(trace, null, 2),
    );
    await fs.copyFile(
      path.join(root, '.workflow-work-tickets/local', pending.id, 'ticket.json'),
      `${E}/disabled-stored-${width}.json`,
    );
    await page.getByRole('button', { name: new RegExp(ids[0].slice(0, 6)) }).click();
    await expect(page.locator('.ticket-state')).toHaveText('선택 단계 완료');
    const result = page.locator('[data-node-id="joined"] a.artifact-link');
    const readable = page.waitForResponse(
      (r) =>
        r.request().method() === 'GET' &&
        new URL(r.url()).pathname.includes('/artifacts/joined/manifest'),
    );
    await result.click();
    expect((await readable).status()).toBe(200);
    expect(errors).toEqual([]);
    await fs.writeFile(
      `${E}/events-${width}.json`,
      JSON.stringify(
        {
          mode: 'actual isolated store/API/registered config, controlled request transport NOT real inference',
          events,
          errors,
        },
        null,
        2,
      ),
    );
  });
}
