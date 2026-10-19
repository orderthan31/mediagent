import { test, expect as baseExpect } from '@playwright/test';
const expect = baseExpect.configure({ timeout: 30000 });
import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';

for (const width of [1440, 390]) {
  test(`opt-in recovery, reuse and history ${width}`, async ({ page }) => {
    test.setTimeout(600000);
    page.setDefaultTimeout(30000);
    const E = 'docs/evidence/WF-07';
    await fs.mkdir(E, { recursive: true });
    const root = path.resolve('test-results/wf07-' + randomUUID());
    await fs.mkdir(root, { recursive: true });
    const errors: string[] = [],
      events: unknown[] = [];
    let drift = false,
      externalEdit = false;
    let seedInterrupted = false;
    let seedQuarantine = false;
    page.on('pageerror', (e) => errors.push(e.message));
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await page.addInitScript(() =>
      document.addEventListener('DOMContentLoaded', () => {
        const p = document.createElement('p');
        p.textContent = '격리 실제 ASGI/복구 저장소 · 합성 CPU 영상/통제 실패 · 실추론 아님';
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
          'video-subtitle-api:renewal-ad1eaa82',
          'python',
          '/src/apps/web/tests/browser/wf07_bridge.py',
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
            seed_interrupted: seedInterrupted,
            seed_quarantine: seedQuarantine,
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
    await expect(page.getByLabel('복구 계약 사용', { exact: true })).toBeVisible();
    await page.getByLabel('입력 영상', { exact: true }).selectOption('b'.repeat(32));
    await page.getByLabel('저장 워크플로우', { exact: true }).selectOption('a'.repeat(32));
    await page.getByLabel('복구 계약 사용', { exact: true }).check();
    await page.getByRole('button', { name: '계획·비용 확인으로', exact: true }).click();
    await expect(page.locator('.start-plan')).toContainText('미실행 대상');
    await page.getByRole('button', { name: '확인하고 티켓 만들기', exact: true }).click();
    await expect(page.locator('.recovery-actions')).toContainText('새 복구 계약');
    const confirmRun = async () => {
      await page.getByRole('button', { name: '실행 계획 불러오기', exact: true }).click();
      await page.getByRole('button', { name: '계획 확인 저장', exact: true }).click();
      await page.getByRole('button', { name: '확인한 계획 실행 요청', exact: true }).click();
    };
    await confirmRun();
    await expect(page.locator('.ticket-detail .ticket-state')).toContainText('실패', {
      timeout: 30000,
    });
    await expect(page.locator('[data-node-id="joined"]')).toHaveAttribute(
      'data-status',
      'succeeded',
    );
    await page.locator('.recovery-actions').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/failed-preserved-${width}.png` });
    const parentFiles = await fs.readdir(path.join(root, '.workflow-recovery-tickets/local'));
    const parentId = parentFiles.find((p) => /^[0-9a-f]{32}$/.test(p))!;
    const parentBefore = await fs.readFile(
      path.join(root, '.workflow-recovery-tickets/local', parentId, 'ticket.json'),
    );
    await page.getByRole('button', { name: '검증하고 새 복구 티켓 만들기', exact: true }).click();
    await expect(page.locator('.recovery-actions')).toContainText('원 티켓');
    await expect(page.locator('.recovery-actions')).toContainText('joined');
    await expect(page.locator('.ticket-detail .ticket-state')).toContainText('생성 보류');
    const traceBefore = (await fs.readFile(path.join(root, 'actual-trace.jsonl'), 'utf8'))
      .trim()
      .split('\n')
      .map((l) => JSON.parse(l));
    expect(traceBefore.filter((r) => r.node === 'failure')).toHaveLength(1);
    await page.screenshot({ path: `${E}/child-held-${width}.png` });
    await confirmRun();
    await expect(page.locator('.ticket-detail .ticket-state')).toContainText('선택 단계 완료', {
      timeout: 30000,
    });
    await page.screenshot({ path: `${E}/recovered-${width}.png` });
    const trace = (await fs.readFile(path.join(root, 'actual-trace.jsonl'), 'utf8'))
      .trim()
      .split('\n')
      .map((l) => JSON.parse(l));
    expect(trace.filter((r) => r.node === 'a')).toHaveLength(1);
    expect(trace.filter((r) => r.node === 'b')).toHaveLength(1);
    expect(trace.filter((r) => r.node === 'failure')).toHaveLength(2);
    expect(
      await fs.readFile(
        path.join(root, '.workflow-recovery-tickets/local', parentId, 'ticket.json'),
      ),
    ).toEqual(parentBefore);
    const originalIds = (
      await fs.readdir(path.join(root, '.workflow-recovery-tickets/local'))
    ).filter((p) => /^[0-9a-f]{32}$/.test(p));
    const originalChild = originalIds.find((p) => p !== parentId)!;
    await page.goto('/#/start');
    await page.reload();
    await page.getByLabel('입력 영상', { exact: true }).selectOption('b'.repeat(32));
    await page.getByLabel('저장 워크플로우', { exact: true }).selectOption('a'.repeat(32));
    await page.getByLabel('복구 계약 사용', { exact: true }).check();
    await page.getByRole('button', { name: '계획·비용 확인으로', exact: true }).click();
    await page.getByRole('button', { name: '확인하고 티켓 만들기', exact: true }).click();
    await page.getByRole('button', { name: '취소 요청 접수', exact: true }).click();
    await expect(page.locator('.recovery-actions')).toContainText('취소됨 · 결과 보존');
    await page.locator('.recovery-actions').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/cancelled-${width}.png` });
    await page.getByRole('button', { name: '검증하고 새 복구 티켓 만들기', exact: true }).click();
    await expect(page.locator('.recovery-actions')).toContainText('생성 보류 · 새 계획 확인 필요');
    const noNewCalls = (await fs.readFile(path.join(root, 'actual-trace.jsonl'), 'utf8'))
      .trim()
      .split('\n')
      .map((line) => JSON.parse(line));
    expect(noNewCalls).toEqual(trace);
    seedInterrupted = true;
    await page.goto('/#/recovery-tickets');
    const interrupted = page.getByRole('button', { name: /중단 복구 확인.*단계 처리 중/ });
    await expect(interrupted).toBeVisible();
    seedInterrupted = false;
    await interrupted.click();
    await expect(
      page.getByLabel('결과 불명 중복호출 위험 별도확인', { exact: true }),
    ).toBeVisible();
    await page.getByRole('button', { name: '검증하고 새 복구 티켓 만들기', exact: true }).click();
    await expect(page.locator('.recovery-actions [role="alert"]')).toContainText('결과 불명');
    await page.locator('.recovery-actions').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/unknown-rejected-${width}.png` });
    await page.getByLabel('결과 불명 중복호출 위험 별도확인', { exact: true }).check();
    await page.getByRole('button', { name: '검증하고 새 복구 티켓 만들기', exact: true }).click();
    await expect(page.locator('.recovery-actions')).toContainText('위험 별도확인 기록됨');
    await expect(page.locator('.recovery-actions')).toContainText('생성 보류');
    await page.screenshot({ path: `${E}/unknown-child-held-${width}.png` });
    seedQuarantine = true;
    await page.goto('/#/recovery-tickets');
    await page.reload();
    const lateButton = page.getByRole('button', { name: /늦은 결과 격리 확인.*취소됨/ });
    await expect(lateButton).toBeVisible();
    seedQuarantine = false;
    await lateButton.click();
    const lateRow = page.locator('[data-node-id="late_call"]');
    await expect(lateRow).toHaveAttribute('data-status', 'quarantined');
    await expect(lateRow).toContainText('늦은 결과 격리');
    await lateRow.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/late-quarantined-${width}.png`, fullPage: true });
    await page.goto('/#/workflow-editor');
    await page.getByLabel('저장된 정의', { exact: true }).selectOption('a'.repeat(32));
    await page.getByRole('button', { name: '선택 정의 서버값 열기', exact: true }).click();
    await page.getByRole('button', { name: '저장 이력 읽기', exact: true }).click();
    await page.getByLabel('복원할 저장 revision', { exact: true }).selectOption('1');
    await page
      .getByRole('button', { name: '선택 이력을 새 revision으로 복원', exact: true })
      .click();
    await expect(page.locator('.definition-history')).toContainText('새 revision 3');
    await expect(
      page.getByLabel('저장된 정의', { exact: true }).locator('option:checked'),
    ).toContainText('r3');
    await page.screenshot({ path: `${E}/history-restored-${width}.png` });
    await page.goto('/#/recovery-tickets');
    await page.getByRole('button', { name: /복구 검사 흐름 최신.*선택 단계 완료/ }).click();
    await page.getByText('티켓 정의 snapshot 복원', { exact: true }).click();
    await page
      .getByRole('button', { name: '티켓 정의를 새 revision으로 복원', exact: true })
      .click();
    const snapshotStatus = page
      .getByRole('status')
      .filter({ hasText: '티켓 snapshot을 새 revision 4' });
    await expect(snapshotStatus).toBeVisible();
    await snapshotStatus.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/ticket-snapshot-restored-${width}.png` });
    expect(errors).toEqual([]);
    const lateIdentity = JSON.parse(
      await fs.readFile(path.join(root, 'quarantined-ticket.json'), 'utf8'),
    ).id;
    await fs.copyFile(
      path.join(root, '.workflow-recovery-tickets/local', lateIdentity, 'ticket.json'),
      `${E}/late-ticket-${width}.json`,
    );
    await fs.copyFile(
      path.join(root, '.workflow-recovery-tickets/local', lateIdentity, 'control.json'),
      `${E}/late-control-${width}.json`,
    );
    const lateSaved = JSON.parse(
      await fs.readFile(
        path.join(root, '.workflow-recovery-tickets/local', lateIdentity, 'ticket.json'),
        'utf8',
      ),
    );
    expect(lateSaved.status).toBe('cancelled');
    expect(lateSaved.steps[0].status).toBe('quarantined');
    expect(lateSaved.scheduler.nodes.late_call.status).toBe('quarantined');
    expect(lateSaved.scheduler.nodes.late_call.result).toBeUndefined();
    expect(lateSaved.receipts.late_call).toBeUndefined();

    await fs.copyFile(
      path.join(root, '.workflow-definitions/local', 'a'.repeat(32) + '.json'),
      `${E}/restored-definition-${width}.json`,
    );
    await fs.copyFile(
      path.join(root, '.workflow-definitions/local/.versions', 'a'.repeat(32), '4.json'),
      `${E}/snapshot-restore-provenance-${width}.json`,
    );
    for (const [label, id] of [
      ['parent', parentId],
      ['child', originalChild],
    ]) {
      await fs.copyFile(
        path.join(root, '.workflow-recovery-tickets/local', id, 'ticket.json'),
        `${E}/${label}-${width}.json`,
      );
      await fs.copyFile(
        path.join(root, '.workflow-recovery-tickets/local', id, 'control.json'),
        `${E}/${label}-control-${width}.json`,
      );
    }
    await fs.writeFile(
      `${E}/journey-${width}.json`,
      JSON.stringify(
        {
          mode: 'actual isolated ASGI/store, synthetic CPU media and controlled failure; NOT inference',
          parentId,
          trace,
          events,
          errors,
        },
        null,
        2,
      ),
    );
  });
}
