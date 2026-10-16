import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import contracts from './fixtures/serving.json' with { type: 'json' };

for (const width of [1440, 390]) {
  for (const kind of ['start', 'models'] as const) {
    test(`scoped ${kind} initial error empty success stale refresh ${width}`, async ({ page }) => {
      const E = 'docs/evidence/UI-01-R1';
      await fs.mkdir(E, { recursive: true });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      const errors: string[] = [];
      const ledger: unknown[] = [];
      page.on('pageerror', (e) => errors.push(e.message));
      let state: 'error' | 'empty' | 'rows' = 'error';
      const version = {
        model_id: 'c'.repeat(32),
        revision: 1,
        name: '이전 확인 모델',
        provider: 'openai',
        model: 'gpt-4o-mini',
        uses: ['decision'],
        sha256: '1'.repeat(64),
      };
      const model = {
        id: 'c'.repeat(32),
        revision: 1,
        current_revision: 1,
        state_revision: 0,
        active: true,
        connection: 'unverified',
        versions: { '1': version },
      };
      await page.addInitScript(() =>
        document.addEventListener('DOMContentLoaded', () => {
          const banner = document.createElement('p');
          banner.textContent = '국소 목록상태 API fixture · 실모델/운영데이터 아님';
          document.body.prepend(banner);
        }),
      );
      await page.route('**/api/**', async (route) => {
        const request = route.request();
        const path = new URL(request.url()).pathname;
        const target =
          (kind === 'start' &&
            (path === '/api/videos' || path === '/api/settings/workflow-definitions')) ||
          (kind === 'models' && path === '/api/settings/registered-models');
        if (target) {
          ledger.push({ path, state, method: request.method() });
          if (state === 'error') {
            return route.fulfill({ status: 500, json: { detail: '국소 목록 조회 실패' } });
          }
          if (path.endsWith('/videos')) {
            return route.fulfill({
              json: {
                videos:
                  state === 'empty'
                    ? []
                    : [{ asset_id: 'b'.repeat(32), original_filename: '이전 확인 영상.mp4' }],
              },
            });
          }
          if (path.endsWith('/workflow-definitions')) {
            return route.fulfill({
              json: {
                definitions:
                  state === 'empty'
                    ? []
                    : [{ id: 'a'.repeat(32), name: '이전 확인 흐름', revision: 1 }],
              },
            });
          }
          return route.fulfill({
            json: {
              models: state === 'empty' ? [] : [model],
              providers: { openai: 'OpenAI' },
              connection: 'unverified',
            },
          });
        }
        if (path === '/api/settings/serving') {
          return route.fulfill({ json: contracts.serving });
        }
        if (path === '/api/settings/node-catalog') {
          return route.fulfill({ json: contracts.catalog });
        }
        return route.fulfill({
          json: path.endsWith('session')
            ? { enabled: false, user: null }
            : path.endsWith('/videos')
              ? { videos: [] }
              : path.endsWith('video-uploads')
                ? { uploads: [] }
                : { jobs: [], status: 'ok' },
        });
      });
      await page.goto(kind === 'start' ? '/#/start' : '/#/serving');
      const panel = page.locator(kind === 'start' ? '.workflow-start' : '.model-registry');
      const absent = kind === 'start' ? /저장 워크플로우 없음|입력 영상 없음/ : /등록 모델 없음/;
      const refresh = page.getByRole('button', {
        name: kind === 'start' ? '목록 새로 읽기' : '등록 목록 새로 읽기',
        exact: true,
      });
      await expect(panel.locator('.list-query-error')).toContainText('국소 목록 조회 실패');
      await expect(panel).not.toContainText(absent);
      if (kind === 'models') {
        await page.getByRole('button', { name: '새 등록 입력', exact: true }).click();
        await expect(panel.locator('.list-query-error')).toContainText('국소 목록 조회 실패');
      }
      await page.screenshot({ path: `${E}/${kind}-initial-error-${width}.png` });
      state = 'empty';
      await refresh.click();
      await expect(panel).toContainText(
        kind === 'start' ? '저장 워크플로우 없음' : '등록 모델 없음',
      );
      await expect(panel.locator('.list-query-error')).toHaveCount(0);
      await page.screenshot({ path: `${E}/${kind}-successful-empty-${width}.png` });
      state = 'rows';
      await refresh.click();
      if (kind === 'start') {
        await expect(page.getByLabel('입력 영상').locator('option')).toContainText([
          '영상 선택',
          '이전 확인 영상.mp4',
        ]);
      } else {
        await expect(panel).toContainText('이전 확인 모델');
      }
      state = 'error';
      await refresh.click();
      await expect(panel.locator('.list-query-error')).toContainText('국소 목록 조회 실패');
      await expect(panel.locator('.list-query-stale')).toContainText('이전 조회값 · 최신 미확인');
      await expect(panel).not.toContainText(absent);
      if (kind === 'start') {
        await expect(page.getByLabel('입력 영상').locator('option')).toContainText([
          '영상 선택',
          '이전 확인 영상.mp4',
        ]);
      } else {
        await expect(panel).toContainText('이전 확인 모델');
      }
      await page.screenshot({ path: `${E}/${kind}-stale-refresh-${width}.png`, fullPage: true });
      state = 'empty';
      await refresh.click();
      await expect(panel).toContainText(
        kind === 'start' ? '저장 워크플로우 없음' : '등록 모델 없음',
      );
      await expect(panel.locator('.list-query-stale')).toHaveCount(0);
      expect(errors).toEqual([]);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      ).toBeTruthy();
      await fs.writeFile(
        `${E}/${kind}-list-ledger-${width}.json`,
        JSON.stringify(
          {
            mode: 'stateful API response fixture for rendering ONLY, not real store/provider',
            ledger,
            errors,
          },
          null,
          2,
        ),
      );
    });
  }
}
