import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';

for (const width of [1440, 390]) {
  test(`actual structured judgment, fixed route and explicit continuation ${width}`, async ({
    page,
  }) => {
    test.setTimeout(600000);
    page.setDefaultTimeout(30000);
    const E = 'docs/evidence/WF-06';
    await fs.mkdir(E, { recursive: true });
    const root = path.resolve('test-results/wf06-' + randomUUID());
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
        p.textContent = '격리 실제 ASGI·영속 판단 / 구조화 고정 adapter·외부 추론 아님';
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
          'PYTHONPATH=/src/packages/shared:/src/apps/api:/src/agents/media',
          'video-subtitle-api:renewal-dfa7a496',
          'python',
          '/src/apps/web/tests/browser/decision_bridge.py',
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
    await page.goto('/#/decision-tickets');
    await expect(
      page.getByRole('heading', { name: 'AI 판단 워크플로우 티켓', exact: true }),
    ).toBeVisible({ timeout: 15000 });
    await page.goto('/#/workflow-editor');
    await page.getByLabel('저장된 정의', { exact: true }).selectOption('a'.repeat(32));
    await page.getByRole('button', { name: '선택 정의 서버값 열기', exact: true }).click();
    await expect(page.locator('.canvas-node[data-node-type="decision"]')).toHaveCount(1);
    await page.locator('.canvas-node[data-id="judge"] .canvas-drag').click();
    await page.getByLabel('노드 X', { exact: true }).fill('450');
    await page.getByRole('button', { name: '편집 정의 저장', exact: true }).click();
    await expect(page.locator('.workflow-editor [role="status"]')).toContainText('서버 저장 완료');
    await page.goto('/#/decision-tickets');
    await page.getByLabel('입력 영상', { exact: true }).selectOption('b'.repeat(32));
    await page.getByLabel('저장 워크플로우', { exact: true }).selectOption('a'.repeat(32));
    await expect(page.locator('.execution-capability')).toContainText('AI 판단 범위 지원');
    await page.getByRole('button', { name: '보류 티켓 생성', exact: true }).click();
    const run = async (continuation = false) => {
      await page.getByRole('button', { name: '실행 계획 불러오기', exact: true }).click();
      await expect(page.locator('.execution-plan')).toContainText('명시 실행 계획 확인');
      if (await page.getByLabel('유료 모델 호출 확인', { exact: true }).isEnabled()) {
        await page.getByLabel('유료 모델 호출 확인', { exact: true }).check();
      }
      await page.getByRole('button', { name: '계획 확인 저장', exact: true }).click();
      await expect(page.locator('.ticket-detail .ticket-state')).toContainText(
        continuation ? '요청 대기' : '실행 대기',
      );
      const settled = page.waitForResponse(
        (response) =>
          response.request().method() === 'POST' &&
          /\/settings\/decision-tickets\/[0-9a-f]{32}\/(start|continue)$/.test(
            new URL(response.url()).pathname,
          ),
      );
      await page
        .getByRole('button', {
          name: continuation ? '확인한 계획 이어 실행 요청' : '확인한 계획 실행 요청',
          exact: true,
        })
        .click();
      expect((await settled).status()).toBe(200);
      await expect(page.locator('.workflow-tickets > [role="status"]')).toContainText(
        '실행 응답을 저장',
        { timeout: 20000 },
      );
    };
    await run();
    await expect(page.locator('.ticket-detail .ticket-state')).toHaveText(
      '판단 완료 · 선택 후행 확인 대기',
    );
    const judge = page.locator('[data-node-id="judge"]');
    await expect(judge.locator('.decision-evidence')).toContainText('선택 경로 a');
    await expect(page.locator('[data-node-id="a"]')).toHaveAttribute('data-status', 'pending');
    await expect(page.locator('[data-node-id="b"]')).toHaveAttribute('data-status', 'pending');
    await expect(page.locator('[data-node-id="independent"]')).toHaveAttribute(
      'data-status',
      'succeeded',
    );
    await judge.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/judgment-${width}.png` });
    await page.reload();
    await page.locator('.ticket-list button').first().click();
    await expect(page.locator('[data-node-id="judge"] .decision-evidence')).toContainText(
      '선택 경로 a',
    );
    await run(true);
    await expect(page.locator('.ticket-detail .ticket-state')).toHaveText('사람 검수 대기');
    await expect(page.locator('[data-node-id="b"]')).toHaveAttribute('data-status', 'skipped');
    await page.getByRole('button', { name: '현재 revision/SHA 명시 승인', exact: true }).click();
    await expect(page.locator('[data-node-id="gate"] .review-panel')).toContainText('자료 확정');
    await run(true);
    await expect(page.locator('.ticket-detail .ticket-state')).toHaveText('선택 단계 완료');
    await expect(page.locator('[data-node-id="a"]')).toHaveAttribute('data-status', 'succeeded');
    await expect(page.locator('[data-node-id="joined"]')).toHaveAttribute(
      'data-status',
      'succeeded',
    );
    await page.locator('[data-node-id="judge"]').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/completed-${width}.png` });
    for (const scenario of [
      { label: 'reject', code: '' },
      { label: 'review', code: 'condition_error' },
      { label: 'invalid', code: 'format_error' },
      { adapter_error: true, code: 'adapter_error' },
    ]) {
      await fs.writeFile(path.join(root, 'scenario.json'), JSON.stringify(scenario));
      await page.getByLabel('입력 영상', { exact: true }).selectOption('b'.repeat(32));
      await page.getByLabel('저장 워크플로우', { exact: true }).selectOption('');
      await page.getByLabel('저장 워크플로우', { exact: true }).selectOption('a'.repeat(32));
      await expect(page.locator('.ticket-detail')).toHaveCount(0);
      await page.getByRole('button', { name: '보류 티켓 생성', exact: true }).click();
      await run();
      if (!scenario.code) {
        await expect(page.locator('[data-node-id="judge"] .decision-evidence')).toContainText(
          '선택 경로 b',
        );
        await run(true);
        await expect(page.locator('.ticket-detail .ticket-state')).toHaveText('선택 단계 완료');
        await expect(page.locator('[data-node-id="a"]')).toHaveAttribute('data-status', 'skipped');
        await expect(page.locator('[data-node-id="gate"]')).toHaveAttribute(
          'data-status',
          'skipped',
        );
        await expect(page.locator('[data-node-id="b"]')).toHaveAttribute(
          'data-status',
          'succeeded',
        );
      } else {
        await expect(page.locator('[data-node-id="judge"] .decision-evidence')).toContainText(
          scenario.code,
        );
        await expect(page.locator('[data-node-id="a"]')).toHaveAttribute('data-status', 'blocked');
        await expect(page.locator('[data-node-id="b"]')).toHaveAttribute('data-status', 'blocked');
        await expect(page.locator('[data-node-id="joined"]')).toHaveAttribute(
          'data-status',
          'blocked',
        );
      }
      await expect(page.locator('[data-node-id="independent"]')).toHaveAttribute(
        'data-status',
        'succeeded',
      );
      await page.locator('[data-node-id="judge"]').scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${E}/${scenario.code || 'selected-b'}-${width}.png` });
    }
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBeTruthy();
    expect(errors).toEqual([]);
    const scoped = path.join(root, '.workflow-decision-tickets');
    const owners = await fs.readdir(scoped);
    expect(owners).toHaveLength(1);
    const ids = (await fs.readdir(path.join(scoped, owners[0]))).filter((x) =>
      /^[0-9a-f]{32}$/.test(x),
    );
    expect(ids).toHaveLength(5);
    for (const id of ids) {
      const dir = path.join(scoped, owners[0], id);
      const raw = await fs.readFile(path.join(dir, 'ticket.json'), 'utf8');
      const data = JSON.parse(raw);
      const failure = await fs
        .readFile(path.join(dir, 'work/judge/decision-error.json'), 'utf8')
        .catch(() => null);
      const result = await fs
        .readFile(path.join(dir, 'work/judge/decision.json'), 'utf8')
        .catch(() => null);
      const name = failure
        ? JSON.parse(failure).code
        : 'selected-' + JSON.parse(result!).judgment.label;
      await fs.writeFile(`${E}/stored-${name}-${width}.json`, raw);
      await fs.cp(path.join(dir, 'work/judge'), `${E}/decision-docs-${name}-${width}`, {
        recursive: true,
        filter: (s) => !s.endsWith('.lock'),
      });
      expect(data.status).toBe(failure ? 'failed' : 'completed');
    }
    const trace = (await fs.readFile(path.join(root, 'actual-trace.jsonl'), 'utf8'))
      .trim()
      .split('\n')
      .map((x) => JSON.parse(x));
    expect(trace.filter((x) => x.decision_input)).toHaveLength(5);
    expect(trace.filter((x) => x.node === 'a')).toHaveLength(1);
    expect(trace.filter((x) => x.node === 'b')).toHaveLength(1);
    await fs.writeFile(
      `${E}/events-${width}.json`,
      JSON.stringify(
        {
          mode: 'actual isolated ASGI/store/executor; controlled structured adapter, NOT external inference',
          events,
          trace,
          errors,
        },
        null,
        2,
      ),
    );
  });
}
