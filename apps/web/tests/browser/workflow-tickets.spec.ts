import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
for (const width of [1440, 390]) {
  test(`definition ticket real orchestration ${width}`, async ({ page }) => {
    test.setTimeout(240000);
    const E = 'docs/evidence/WF-03';
    await fs.mkdir(E, { recursive: true });
    const root = path.resolve('test-results/wf03-' + randomUUID());
    await fs.mkdir(root, { recursive: true });
    const events: unknown[] = [];
    const errors: string[] = [];
    let drift = false,
      edit = false,
      fail = false;
    page.on('pageerror', (e) => errors.push(e.message));
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await page.addInitScript(() =>
      document.addEventListener('DOMContentLoaded', () => {
        const p = document.createElement('p');
        p.textContent = '안전 격리 ASGI·결정론 executor / 실모델 성공 아님';
        p.style.cssText =
          'background:#fff3c4;color:#403214;padding:6px;text-align:center;position:fixed;bottom:0;left:0;right:0;z-index:9999;font-size:12px';
        document.body.prepend(p);
      }),
    );
    await page.route('**/api/**', async (route) => {
      const req = route.request(),
        p = new URL(req.url()).pathname;
      if (p.startsWith('/api/settings/') || p === '/api/videos') {
        const method = req.method();
        const payload = method === 'GET' ? undefined : req.postDataJSON();
        const body = {
          method,
          path: p,
          payload,
          drift: drift && p.endsWith('/confirm'),
          edit_definition: edit && p.endsWith('/plan'),
          fail_run: fail && p.endsWith('/start'),
        };
        if (body.drift) {
          drift = false;
        }
        if (body.edit_definition) {
          edit = false;
        }
        if (body.fail_run) {
          fail = false;
        }
        const data = await new Promise<{ status: number; body: unknown; binary?: string }>(
          (resolve, reject) => {
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
              'PYTHONPATH=/src/packages/shared:/src/apps/api:/src/workers/media',
              'video-subtitle-api:renewal-0616538b',
              'python',
              '/src/apps/web/tests/browser/ticket_bridge.py',
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
            c.stdin.end(JSON.stringify(body));
          },
        );
        events.push({ method, path: p, status: data.status, request_revision: payload?.revision });
        return data.binary
          ? route.fulfill({ status: data.status, body: Buffer.from(data.binary, 'base64') })
          : route.fulfill({ status: data.status, json: data.body });
      }
      return route.fulfill({
        json: p.endsWith('session')
          ? { enabled: false, user: null }
          : p.endsWith('video-uploads')
            ? { uploads: [] }
            : { jobs: [] },
      });
    });
    await page.goto('/#/workflow-tickets');
    await expect(
      page.getByRole('heading', { name: '순차 워크플로우 티켓', exact: true }),
    ).toBeVisible({ timeout: 15000 });
    await page.getByLabel('입력 영상', { exact: true }).selectOption('b'.repeat(32));
    await page.getByLabel('저장 워크플로우', { exact: true }).selectOption('c'.repeat(32));
    await expect(page.locator('.execution-reasons')).toContainText('S5');
    await page.getByLabel('저장 워크플로우', { exact: true }).selectOption('a'.repeat(32));
    await expect(page.locator('.execution-capability')).toContainText('순차 범위 지원');
    await page.getByRole('button', { name: '보류 티켓 생성', exact: true }).click();
    await expect(page.locator('.ticket-detail .ticket-state')).toHaveText('생성 보류');
    edit = true;
    await page.getByRole('button', { name: '실행 계획 불러오기', exact: true }).click();
    await expect(page.locator('.execution-plan')).toContainText('서빙 revision 0');
    drift = true;
    await page.getByRole('button', { name: '계획 확인 저장', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('바뀌');
    await page.getByRole('button', { name: '실행 계획 불러오기', exact: true }).click();
    await expect(page.locator('.execution-plan')).toContainText('서빙 revision 1');
    await page.getByRole('button', { name: '계획 확인 저장', exact: true }).click();
    await expect(page.locator('.ticket-detail .ticket-state')).toHaveText('계획 확인 · 실행 대기');
    fail = true;
    await page.getByRole('button', { name: '확인한 계획 실행 요청', exact: true }).click();
    await expect(page.locator('.ticket-detail .ticket-state')).toHaveText('첫 실패 중단', {
      timeout: 20000,
    });
    await expect(page.locator('.partial-link')).toHaveCount(1);
    await expect(page.locator('.artifact-link')).toHaveCount(1);
    const artifact = await page.evaluate(async () => {
      const a = document.querySelector('.artifact-link') as HTMLAnchorElement;
      const r = await fetch(a.href);
      return { status: r.status, text: await r.text() };
    });
    expect(artifact.status).toBe(200);
    expect(artifact.text).toContain('deterministic fixture');
    await page.locator('.ticket-detail').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/partial-${width}.png` });
    await page.getByLabel('입력 언어', { exact: true }).fill('en');
    await expect(page.locator('.execution-plan')).toHaveCount(0);
    await page.getByRole('button', { name: '선택 정의 새로 읽기', exact: true }).click();
    await expect(page.locator('.execution-capability')).toContainText('순차 범위 지원');
    await page.getByRole('button', { name: '보류 티켓 생성', exact: true }).click();
    await page.getByRole('button', { name: '실행 계획 불러오기', exact: true }).click();
    await page.getByRole('button', { name: '계획 확인 저장', exact: true }).click();
    await page.getByRole('button', { name: '확인한 계획 실행 요청', exact: true }).click();
    await expect(page.locator('.ticket-detail .ticket-state')).toHaveText('선택 단계 완료', {
      timeout: 20000,
    });
    await page.getByRole('button', { name: '티켓 서버값 다시 불러오기', exact: true }).click();
    await expect(page.locator('.workflow-tickets').getByRole('status')).toContainText(
      '티켓 서버값을 다시 불러왔습니다.',
    );
    await expect(page.locator('.execution-plan')).toHaveCount(0);
    await expect(page.locator('.ticket-step')).toHaveCount(2);
    await expect(page.locator('.artifact-link')).toHaveCount(3);
    await page.locator('.ticket-detail').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/completed-${width}.png` });
    expect(errors).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    const store = path.join(root, '.workflow-tickets/local');
    const all = [];
    const rawRecords: string[] = [];
    for (const d of await fs.readdir(store, { withFileTypes: true })) {
      if (d.isDirectory()) {
        const raw = await fs.readFile(path.join(store, d.name, 'ticket.json'), 'utf8');
        rawRecords.push(raw);
        all.push(JSON.parse(raw));
      }
    }
    expect(all).toHaveLength(2);
    expect(all.map((t) => t.status).sort()).toEqual(['completed', 'failed']);
    expect(all.map((t) => t.definition.revision).sort()).toEqual([1, 2]);
    expect(all.every((t) => t.settings_snapshot.revision === 1)).toBe(true);
    // Preserve original JSON numeric tokens (notably nanosecond timestamps).
    await fs.writeFile(`${E}/stored-${width}.json`, '[' + rawRecords.join(',\n') + ']\n');
    await fs.writeFile(
      `${E}/events-${width}.json`,
      JSON.stringify(
        {
          transport:
            'actual ASGI + deterministic executor; injected external definition/settings writes and node failure',
          events,
          errors,
        },
        null,
        2,
      ),
    );
  });
}
