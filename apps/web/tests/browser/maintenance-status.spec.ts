import { expect, test } from '@playwright/test';
import fs from 'node:fs/promises';

// Explicit response fixtures: real production UI, not live auth/DB verification.
const evidence = process.env.MIDEAGENT_STATUS_EVIDENCE;
for (const width of [1440, 390]) {
  test(`maintenance response is not a DB outage (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const calls: string[] = [];
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/**', (route) => {
      const path = new URL(route.request().url()).pathname;
      calls.push(`${route.request().method()} ${path}`);
      if (path === '/api/auth/session') {
        return route.fulfill({
          json: {
            enabled: true,
            user: { id: 'fixture', username: 'response-fixture', role: 'admin' },
          },
        });
      }
      return route.fulfill({ status: 503, json: { detail: 'maintenance_admission_closed' } });
    });
    await page.goto('/#/jobs');
    const alert = page.getByRole('alert');
    await expect(alert).toContainText('유지보수 중 · 작업 이용 제한');
    await expect(alert).not.toContainText('작업 공간 조회 실패');
    await expect(page.getByText(/DB 연결 끊김|DB 정상|PostgreSQL 연동은 아직 준비/)).toHaveCount(0);
    await expect(page.locator('.auth-shell')).toHaveCount(0);
    await expect(page.locator('.account-username').first()).toContainText('response-fixture');
    // Navigation remains available; the allowed policy/API is not modified.
    await page.goto('/#/agents');
    await expect(alert).toContainText('유지보수 중 · 작업 이용 제한');
    expect(new Set(calls)).toEqual(new Set(['GET /api/auth/session', 'GET /api/capabilities']));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    const box = await alert.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(width);
    expect(errors).toEqual([]);
    if (evidence) {
      await fs.mkdir(evidence, { recursive: true });
      await page.screenshot({ path: `${evidence}/maintenance-${width}.png`, fullPage: true });
    }
  });
}

for (const width of [1440, 390]) {
  for (const failure of ['network', 'other-503', 'wrong-status', 'html-503']) {
    test(`communication is not maintenance or DB diagnosis (${failure}, ${width}px)`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.route('**/api/**', (route) => {
        const path = new URL(route.request().url()).pathname;
        if (path === '/api/auth/session') {
          return route.fulfill({
            json: {
              enabled: true,
              user: { id: 'fixture', username: 'response-fixture', role: 'admin' },
            },
          });
        }
        if (failure === 'network') {
          return route.abort('connectionfailed');
        }
        if (failure === 'html-503') {
          return route.fulfill({
            status: 503,
            contentType: 'text/html',
            body: '<h1>Service unavailable</h1>',
          });
        }
        return route.fulfill({
          status: failure === 'wrong-status' ? 500 : 503,
          json: {
            detail:
              failure === 'wrong-status'
                ? 'maintenance_admission_closed'
                : 'unclassified_upstream_failure',
          },
        });
      });
      await page.goto('/#/jobs');
      await expect(page.getByRole('alert')).toContainText('작업 공간 응답 확인 불가');
      await expect(page.getByRole('alert')).toContainText('DB 연결 상태는 확인되지 않았습니다.');
      await expect(page.getByText('유지보수 중 · 작업 이용 제한', { exact: true })).toHaveCount(0);
      await expect(
        page.getByText(
          /DB 연결 끊김|DB 정상|unclassified_upstream_failure|maintenance_admission_closed/,
        ),
      ).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      if (evidence && failure === 'network') {
        await page.screenshot({ path: `${evidence}/communication-${width}.png`, fullPage: true });
      }
    });
  }
  test(`expired login retains the existing login gate (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const calls: string[] = [];
    await page.route('**/api/**', (route) => {
      const path = new URL(route.request().url()).pathname;
      calls.push(path);
      if (path === '/api/auth/session') {
        return route.fulfill({
          json: {
            enabled: true,
            user: { id: 'fixture', username: 'response-fixture', role: 'admin' },
            csrf_token: 'ui-response-fixture-only',
          },
        });
      }
      return route.fulfill({ status: 401, json: { detail: 'authentication_required' } });
    });
    await page.goto('/#/jobs');
    await expect(page.getByRole('heading', { name: '작업 공간에 로그인' })).toBeVisible();
    await expect(page.getByRole('alert')).toContainText(
      '세션이 만료되었습니다. 다시 로그인하세요.',
    );
    await expect(page.getByLabel(/^비밀번호/)).toHaveValue('');
    await expect(page.locator('.video-workspace')).toHaveCount(0);
    expect(new Set(calls)).toEqual(new Set(['/api/auth/session', '/api/capabilities']));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    if (evidence) {
      await page.screenshot({ path: `${evidence}/login-required-${width}.png`, fullPage: true });
    }
  });
  test(`metadata-only capabilities do not diagnose DB state (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route('**/api/**', (route) =>
      route.fulfill({
        json:
          new URL(route.request().url()).pathname === '/api/auth/session'
            ? {
                enabled: true,
                user: { id: 'fixture', username: 'response-fixture', role: 'admin' },
              }
            : { features: [] },
      }),
    );
    await page.goto('/#/jobs');
    await expect(page.getByRole('status')).toContainText(
      '현재 이 서버에서는 작업 기능을 사용할 수 없습니다.',
    );
    await expect(page.getByText(/PostgreSQL 연동은 아직 준비|DB 연결 끊김|DB 정상/)).toHaveCount(0);
  });
}

for (const width of [1440, 390]) {
  test(`unauthorized capability response needs login even without cached token (${width}px)`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route('**/api/**', (route) =>
      new URL(route.request().url()).pathname === '/api/auth/session'
        ? route.fulfill({
            json: {
              enabled: true,
              user: { id: 'fixture', username: 'response-fixture', role: 'admin' },
            },
          })
        : route.fulfill({ status: 401, json: { detail: 'authentication_required' } }),
    );
    await page.goto('/#/jobs');
    await expect(page.getByRole('alert')).toContainText('로그인 필요');
    await expect(page.getByRole('alert')).not.toContainText('유지보수 중');
    await expect(page.getByText(/DB 연결 끊김|DB 정상/)).toHaveCount(0);
  });
}
