import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';

for (const width of [1440, 390]) {
  test(`real graph orchestration and manual routing ${width}`, async ({ page }) => {
    test.setTimeout(300000);
    const E = 'docs/evidence/WF-04';
    await fs.mkdir(E, { recursive: true });
    const root = path.resolve('test-results/wf04-' + randomUUID());
    await fs.mkdir(root, { recursive: true });
    const errors: string[] = [],
      events: unknown[] = [];
    let drift = false,
      edit = false,
      fail = false;
    page.on('pageerror', (e) => errors.push(e.message));
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await page.addInitScript(() =>
      document.addEventListener('DOMContentLoaded', () => {
        const p = document.createElement('p');
        p.textContent = '안전 격리 실제 ASGI·결정론 병렬 executor / 실모델 아님';
        p.style.cssText =
          'background:#fff3c4;color:#403214;padding:6px;text-align:center;position:fixed;bottom:0;left:0;right:0;z-index:9999;font-size:12px';
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
      const method = req.method(),
        payload = method === 'GET' ? undefined : req.postDataJSON();
      const body = {
        method,
        path: p,
        payload,
        drift: drift && p.endsWith('/confirm'),
        edit_definition: edit && p.endsWith('/plan'),
        fail_run: fail && p.endsWith('/start'),
        hold_run: fail && p.endsWith('/start'),
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
            'PYTHONPATH=/src/packages/shared:/src/apps/api:/src/agents/media',
            'video-subtitle-api:renewal-39617aec',
            'python',
            '/src/apps/web/tests/browser/graph_bridge.py',
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
    });
    await page.goto('/#/graph-tickets');
    await expect(
      page.getByRole('heading', { name: '분기·병렬 워크플로우 티켓', exact: true }),
    ).toBeVisible({ timeout: 15000 });
    await page.getByLabel('입력 영상', { exact: true }).selectOption('b'.repeat(32));
    await page.getByLabel('저장 워크플로우', { exact: true }).selectOption('c'.repeat(32));
    await expect(page.locator('.execution-reasons')).toContainText('GPU');
    await page.getByLabel('저장 워크플로우', { exact: true }).selectOption('a'.repeat(32));
    await expect(page.locator('.execution-capability')).toContainText('분기·병렬 범위 지원');
    await page.getByLabel('분기 choose 선택', { exact: true }).selectOption('both');
    await page.getByRole('button', { name: '보류 티켓 생성', exact: true }).click();
    await expect(page.locator('.ticket-detail')).toContainText('choose=both');
    edit = true;
    await page.getByRole('button', { name: '실행 계획 불러오기', exact: true }).click();
    await expect(page.locator('.execution-plan')).toContainText('서빙 revision 0');
    drift = true;
    await page.getByRole('button', { name: '계획 확인 저장', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('바뀌');
    await page.getByRole('button', { name: '실행 계획 불러오기', exact: true }).click();
    await expect(page.locator('.execution-plan')).toContainText('서빙 revision 1');
    await page.getByRole('button', { name: '계획 확인 저장', exact: true }).click();
    fail = true;
    const ticketId = (await page.locator('.ticket-detail').textContent())!.match(
      /티켓 ([0-9a-f]{32})/,
    )![1];
    await page.getByRole('button', { name: '확인한 계획 실행 요청', exact: true }).click();
    await expect(page.locator('.ticket-step[data-status="running"]')).toHaveCount(2, {
      timeout: 12000,
    });
    await page.locator('.ticket-step[data-node-id="a"]').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/running-${width}.png` });
    const release = await page.evaluate(
      async (id) =>
        (
          await fetch('/api/settings/graph-fixture/release', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id }),
          })
        ).json(),
      ticketId,
    );
    expect(release.released).toBe(true);
    await expect(page.locator('.ticket-detail .ticket-state')).toHaveText(
      '선택 가지 실패 · 독립 결과 보존',
      { timeout: 20000 },
    );
    await expect(page.locator('.ticket-step[data-node-id="joined"]')).toContainText(
      '선행 실패로 차단',
    );
    await expect(page.locator('.ticket-step[data-node-id="b"]')).toContainText('성공');
    await expect(page.locator('.partial-link')).toHaveCount(1);
    await page.locator('.ticket-detail').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/failed-${width}.png` });
    await page.getByRole('button', { name: '선택 정의 새로 읽기', exact: true }).click();
    await page.getByLabel('분기 choose 선택', { exact: true }).selectOption('a');
    await expect(page.locator('.execution-plan')).toHaveCount(0);
    await page.getByRole('button', { name: '보류 티켓 생성', exact: true }).click();
    await page.getByRole('button', { name: '실행 계획 불러오기', exact: true }).click();
    await page.getByRole('button', { name: '계획 확인 저장', exact: true }).click();
    await page.getByRole('button', { name: '확인한 계획 실행 요청', exact: true }).click();
    await expect(page.locator('.ticket-detail .ticket-state')).toHaveText('선택 단계 완료', {
      timeout: 20000,
    });
    await expect(page.locator('.ticket-step[data-node-id="b"]')).toContainText('미선택 건너뜀');
    const manifest = await page.evaluate(async () => {
      const a = document.querySelector(
        '.ticket-step[data-node-id="joined"] .artifact-link',
      ) as HTMLAnchorElement;
      const r = await fetch(a.href);
      return { status: r.status, body: await r.json() };
    });
    expect(manifest.status).toBe(200);
    expect(Object.keys(manifest.body.members)).toEqual(['a.video']);
    await page.getByRole('button', { name: '티켓 서버값 다시 불러오기', exact: true }).click();
    await expect(page.locator('.workflow-tickets').getByRole('status')).toContainText(
      '티켓 서버값을 다시 불러왔습니다.',
    );
    await expect(page.locator('.execution-plan')).toHaveCount(0);
    await page.locator('.ticket-detail').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/selected-${width}.png` });
    await page.getByLabel('분기 choose 선택', { exact: true }).selectOption('both');
    await page.getByRole('button', { name: '보류 티켓 생성', exact: true }).click();
    await page.getByRole('button', { name: '실행 계획 불러오기', exact: true }).click();
    await page.getByRole('button', { name: '계획 확인 저장', exact: true }).click();
    await page.getByRole('button', { name: '확인한 계획 실행 요청', exact: true }).click();
    await expect(page.locator('.ticket-detail .ticket-state')).toHaveText('선택 단계 완료', {
      timeout: 20000,
    });
    await page.locator('.ticket-detail').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/completed-${width}.png` });
    await page.goto('/#/workflow-editor');
    await page.getByLabel('저장된 정의', { exact: true }).selectOption('a'.repeat(32));
    await page.getByRole('button', { name: '선택 정의 서버값 열기', exact: true }).click();
    await expect(page.locator('.canvas-node')).toHaveCount(4);
    const join = page.locator('.canvas-node[data-node-type="join"]');
    await join.locator('.canvas-drag').click();
    await page.getByLabel('노드 옵션 left_type', { exact: true }).selectOption('audio');
    await expect(join.locator('.editor-port.in').first()).toContainText('audio');
    await page.getByRole('button', { name: '편집 정의 저장', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('노드·연결 문제');
    await expect(page.getByLabel('노드 옵션 left_type', { exact: true })).toHaveValue('audio');
    await page.getByLabel('노드 옵션 left_type', { exact: true }).selectOption('video');
    await page.getByRole('button', { name: '편집 정의 저장', exact: true }).click();
    await expect(page.locator('.workflow-editor').getByRole('status')).toContainText(
      '서버 저장 완료',
    );
    await page.reload();
    await page.getByLabel('저장된 정의', { exact: true }).selectOption('a'.repeat(32));
    await page.getByRole('button', { name: '선택 정의 서버값 열기', exact: true }).click();
    await expect(page.locator('.canvas-node')).toHaveCount(4);
    await expect(join.locator('.editor-port.out')).toContainText('artifact_manifest');
    await join.locator('.canvas-drag').click();
    await expect(page.getByLabel('노드 옵션 left_type', { exact: true })).toHaveValue('video');
    await page.getByLabel('노드 옵션 left_type', { exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${E}/canvas-${width}.png` });
    expect(errors).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    const records: string[] = [];
    const store = path.join(root, '.workflow-graph-tickets/local');
    for (const d of await fs.readdir(store, { withFileTypes: true })) {
      if (d.isDirectory()) {
        records.push(await fs.readFile(path.join(store, d.name, 'ticket.json'), 'utf8'));
      }
    }
    const all = records.map((r) => JSON.parse(r));
    expect(all).toHaveLength(3);
    expect(all.map((t) => t.status).sort()).toEqual(['completed', 'completed', 'failed']);
    const traces = [];
    for (const f of await fs.readdir(path.join(root, 'execution-traces'))) {
      traces.push(JSON.parse(await fs.readFile(path.join(root, 'execution-traces', f), 'utf8')));
    }
    for (const trace of traces.filter(
      (t) => t.filter((e: { event: string }) => e.event === 'start').length === 2,
    )) {
      const start = trace.filter((e: { event: string }) => e.event === 'start');
      const done = trace.filter((e: { event: string }) => e.event !== 'start');
      expect(Math.max(...start.map((e: { time_ns: number }) => e.time_ns))).toBeLessThan(
        Math.min(...done.map((e: { time_ns: number }) => e.time_ns)),
      );
      expect(new Set(start.map((e: { thread: number }) => e.thread)).size).toBe(2);
    }
    await fs.writeFile(`${E}/stored-${width}.json`, '[' + records.join(',\n') + ']\n');
    await fs.writeFile(
      `${E}/events-${width}.json`,
      JSON.stringify(
        {
          transport: 'actual isolated ASGI + synchronized deterministic executor',
          events,
          traces,
          errors,
        },
        null,
        2,
      ),
    );
  });
}
