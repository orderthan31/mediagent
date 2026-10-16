import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import contracts from './fixtures/serving.json' with { type: 'json' };

const cases = [
  { kind: 'recovery', width: 1440, copy: '저장된 복구 계약 티켓이 없습니다' },
  { kind: 'recovery', width: 390, copy: '저장된 복구 계약 티켓이 없습니다' },
  { kind: 'work', width: 1440, copy: '저장된 작업 티켓이 없습니다' },
  { kind: 'decision', width: 1440, copy: '저장된 AI 판단 티켓 없음.' },
];
for (const { kind, width, copy } of cases) {
  test(`WF07 R1 correct empty ticket subject ${kind} ${width}`, async ({ page }) => {
    const evidence = 'docs/evidence/WF-07-R1';
    await fs.mkdir(evidence, { recursive: true });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    const errors: string[] = [];
    const reads: { path: string; method: string }[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.addInitScript(() =>
      document.addEventListener('DOMContentLoaded', () => {
        const banner = document.createElement('p');
        banner.textContent = 'WF07-R1 빈 목록 UI 계약 fixture · 운영 저장/복구/실행 검사 아님';
        document.body.prepend(banner);
      }),
    );
    await page.route('**/api/**', async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      reads.push({ path, method: request.method() });
      if (request.method() !== 'GET') {
        return route.fulfill({
          status: 405,
          json: { detail: 'No mutation allowed in empty-list copy fixture' },
        });
      }
      const json = path.endsWith('/session')
        ? { enabled: false, user: null }
        : path === '/api/settings/node-catalog'
          ? contracts.catalog
          : path === '/api/settings/serving'
            ? contracts.serving
            : path.endsWith('/workflow-definitions')
              ? { definitions: [] }
              : /\/(?:work|decision|recovery)-tickets$/.test(path)
                ? { tickets: [] }
                : path.endsWith('/runtime')
                  ? { connected: false, label: '미연결 UI fixture' }
                  : path === '/api/videos'
                    ? { videos: [] }
                    : path.endsWith('/video-uploads')
                      ? { uploads: [] }
                      : { jobs: [], status: 'ok' };
      return route.fulfill({ json });
    });
    await page.goto('/#/' + kind + '-tickets');
    const panel = page.locator('.workflow-tickets');
    await expect(panel).toContainText(copy);
    for (const other of cases.map((c) => c.copy).filter((c) => c !== copy)) {
      await expect(panel).not.toContainText(other);
    }
    expect(reads.some((r) => r.path === '/api/settings/' + kind + '-tickets')).toBe(true);
    expect(reads.every((r) => r.method === 'GET')).toBe(true);
    expect(errors).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(
      false,
    );
    await page.getByText(copy, { exact: false }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${evidence}/${kind}-empty-${width}.png` });
    await fs.writeFile(
      `${evidence}/${kind}-${width}.json`,
      JSON.stringify(
        {
          kind,
          width,
          copy,
          mode: 'scoped UI API-contract fixture only; no storage/execution',
          reads,
          errors,
        },
        null,
        2,
      ),
    );
  });
}
