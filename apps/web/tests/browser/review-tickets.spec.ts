import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';

for (const width of [1440, 390]) {
  test(`actual durable review gates and explicit continuation ${width}`, async ({ page }) => {
    test.setTimeout(300000);
    const E = 'docs/evidence/WF-05';
    await fs.mkdir(E, { recursive: true });
    const root = path.resolve('test-results/wf05-' + randomUUID());
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
        p.textContent = '격리 실제 ASGI·영속 검수 / 결정론 executor·실모델 아님';
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
          'video-subtitle-api:renewal-1e07aa7d',
          'python',
          '/src/apps/web/tests/browser/review_bridge.py',
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
    await page.goto('/#/review-tickets');
    await expect(
      page.getByRole('heading', { name: '사람 검수 워크플로우 티켓', exact: true }),
    ).toBeVisible({ timeout: 15000 });
    await page.goto('/#/workflow-editor');
    await page.getByLabel('저장된 정의', { exact: true }).selectOption('a'.repeat(32));
    await page.getByRole('button', { name: '선택 정의 서버값 열기', exact: true }).click();
    await expect(page.locator('.canvas-node[data-node-type="review"]')).toHaveCount(3);
    await page.locator('.canvas-node[data-id="review_text"] .canvas-drag').click();
    await page.getByLabel('노드 X', { exact: true }).fill('850');
    await page.getByLabel('노드 Y', { exact: true }).fill('280');
    await page.getByRole('button', { name: '편집 정의 저장', exact: true }).click();
    await expect(page.locator('.workflow-editor [role="status"]')).toContainText('서버 저장 완료');
    await page.reload();
    await page.getByLabel('저장된 정의', { exact: true }).selectOption('a'.repeat(32));
    await page.getByRole('button', { name: '선택 정의 서버값 열기', exact: true }).click();
    await expect(page.locator('.canvas-node[data-id="review_text"]')).toHaveCSS('left', '850px');
    await page.goto('/#/review-tickets');
    await page.getByLabel('입력 영상', { exact: true }).selectOption('b'.repeat(32));
    await page.getByLabel('저장 워크플로우', { exact: true }).selectOption('a'.repeat(32));
    await expect(page.locator('.execution-capability')).toContainText('검수 범위 지원');
    await page.getByRole('button', { name: '보류 티켓 생성', exact: true }).click();
    const run = async (continuation = false) => {
      await page.getByRole('button', { name: '실행 계획 불러오기', exact: true }).click();
      await expect(page.locator('.execution-plan')).toBeVisible();
      const paid = page.getByLabel('유료 모델 호출 확인', { exact: true });
      if (await paid.isEnabled()) {
        await paid.check();
      }
      await page.getByRole('button', { name: '계획 확인 저장', exact: true }).click();
      await page
        .getByRole('button', {
          name: continuation ? '확인한 계획 이어 실행 요청' : '확인한 계획 실행 요청',
          exact: true,
        })
        .click();
    };
    await run();
    await expect(page.locator('.ticket-detail .ticket-state')).toHaveText('사람 검수 대기', {
      timeout: 20000,
    });
    await expect(page.locator('.ticket-step[data-node-id="independent"]')).toContainText('성공');
    await expect(page.locator('.ticket-step[data-node-id="subtitle"]')).toHaveAttribute(
      'data-status',
      'pending',
    );
    await page.reload();
    await page.locator('.ticket-list button').first().click();
    const text = page.locator('.review-panel[data-review-node="review_text"]');
    await expect(text).toBeVisible();
    await text.getByRole('button', { name: '현재 revision/SHA 명시 승인', exact: true }).click();
    await expect(text.getByRole('alert')).toContainText('차단 placeholder');
    await text.getByLabel('구간 1 텍스트', { exact: true }).fill('사람이 확정한 실제 수정본');
    externalEdit = true;
    await text.getByRole('button', { name: '수정본 별도 저장', exact: true }).click();
    await expect(text.getByRole('alert')).toContainText('revision/SHA');
    await expect(text.getByLabel('구간 1 텍스트', { exact: true })).toHaveValue(
      '사람이 확정한 실제 수정본',
    );
    await text.getByRole('button', { name: '수정본 별도 저장', exact: true }).click();
    await expect(text.getByRole('alert')).toContainText('revision/SHA');
    await text.getByRole('alert').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/conflict-preserved-${width}.png` });
    await text
      .getByRole('button', { name: '최신 서버값 조회 · 내 편집 유지', exact: true })
      .click();
    await text.getByRole('button', { name: '수정본 별도 저장', exact: true }).click();
    await expect(text).toContainText('수정본 r3');
    await expect(page.locator('.ticket-step[data-node-id="subtitle"]')).toHaveAttribute(
      'data-status',
      'pending',
    );
    await text.getByRole('button', { name: '현재 revision/SHA 명시 승인', exact: true }).click();
    await expect(text).toContainText('자료 확정 · 이어 실행 전');
    const metadata = page.locator('.review-panel[data-review-node="review_metadata"]');
    await expect(metadata).toContainText('확인만 지원');
    await metadata
      .getByRole('button', { name: '현재 revision/SHA 명시 승인', exact: true })
      .click();
    await page.getByRole('button', { name: '실행 계획 불러오기', exact: true }).click();
    drift = true;
    await page.getByRole('button', { name: '계획 확인 저장', exact: true }).click();
    await expect(page.locator('.workflow-tickets > [role="alert"]')).toContainText('바뀌');
    await run(true);
    const subtitle = page.locator('.review-panel[data-review-node="review_srt"]');
    await expect(subtitle).toBeVisible({ timeout: 20000 });
    await expect(subtitle.getByLabel('구간 1 텍스트', { exact: true })).toHaveValue(
      '사람이 확정한 실제 수정본',
    );
    await expect(page.locator('.ticket-step[data-node-id="encode"]')).toHaveAttribute(
      'data-status',
      'pending',
    );
    await subtitle.getByLabel('구간 1 텍스트', { exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/second-position-${width}.png` });
    await subtitle
      .getByRole('button', { name: '현재 revision/SHA 명시 승인', exact: true })
      .click();
    await run(true);
    await expect(page.locator('.ticket-detail .ticket-state')).toHaveText('선택 단계 완료', {
      timeout: 20000,
    });
    await expect(
      page.locator('.review-panel').getByText('승인 gate 통과', { exact: true }),
    ).toHaveCount(3);
    await page.screenshot({ path: `${E}/completed-${width}.png`, fullPage: true });
    expect(errors).toEqual([]);
    const trace = (await fs.readFile(path.join(root, 'actual-trace.jsonl'), 'utf8'))
      .trim()
      .split('\n')
      .map((x) => JSON.parse(x));
    expect(trace.filter((x) => x.node === 'stt')).toHaveLength(1);
    expect(trace.filter((x) => x.node === 'independent')).toHaveLength(1);
    expect(trace.find((x) => x.received_by_subtitle)?.received_by_subtitle[0].text).toBe(
      '사람이 확정한 실제 수정본',
    );
    const scoped = path.join(root, '.workflow-review-tickets');
    const owner = (await fs.readdir(scoped))[0];
    const ticketIds = (await fs.readdir(path.join(scoped, owner))).filter((name) =>
      /^[0-9a-f]{32}$/.test(name),
    );
    expect(ticketIds).toHaveLength(1);
    const ticketId = ticketIds[0];
    const work = path.join(scoped, owner, ticketId, 'work');
    for (const node of ['review_text', 'review_srt', 'review_metadata']) {
      await fs.cp(path.join(work, node, 'review'), `${E}/review-docs-${width}/${node}`, {
        recursive: true,
        filter: (src) => !src.endsWith('.lock'),
      });
    }
    await fs.copyFile(
      path.join(scoped, owner, ticketId, 'ticket.json'),
      `${E}/stored-${width}.json`,
    );
    await fs.writeFile(
      `${E}/journey-${width}.json`,
      JSON.stringify(
        {
          mode: 'Actual isolated ASGI/store, explicit deterministic executor, no real model/video engine',
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
