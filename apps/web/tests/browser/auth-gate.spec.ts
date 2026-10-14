import { expect, test } from '@playwright/test';
import fs from 'node:fs/promises';

const evidence = 'docs/evidence/REN-01';
const runtimeErrors: string[] = [];

test.beforeEach(({ page }) => {
  runtimeErrors.length = 0;
  page.on('pageerror', (error) => runtimeErrors.push(error.message));
});
test.afterEach(() => {
  expect(runtimeErrors).toEqual([]);
});

// API fixtures are explicit: this exercises the real UI, not a live auth server.
test('로그인 화면이 실제 Indigo 한결 UI와 로컬 Pretendard를 소비한다', async ({ page }) => {
  const fontResponses: string[] = [];
  page.on('response', (response) => {
    if (response.url().includes('/fonts/hangyeol/') && response.status() === 200) {
      fontResponses.push(new URL(response.url()).pathname);
    }
  });
  await page.route('**/api/auth/session', (route) =>
    route.fulfill({ json: { enabled: true, user: null } }),
  );
  await page.goto('/');
  await expect(page.getByLabel(/^사용자 이름/)).toBeVisible();
  await expect(page.locator('[data-hangyeol][data-palette="Indigo"]')).toBeVisible();
  await expect(page.getByRole('heading', { name: '작업 공간에 로그인' })).toBeVisible();
  const button = page.getByRole('button', { name: '로그인', exact: true });
  await expect(button).toHaveCSS('background-color', 'rgb(67, 89, 219)');
  await expect(button).toHaveAttribute('type', 'submit');
  await page.evaluate(() => document.fonts.ready);
  expect(await page.evaluate(() => document.fonts.check('16px Pretendard'))).toBe(true);
  expect(fontResponses).toContain('/fonts/hangyeol/Pretendard-Regular.woff2');
  await expect(page.getByLabel(/^사용자 이름/)).toHaveAttribute('maxlength', '64');
  await expect(page.getByLabel(/^비밀번호/)).toHaveAttribute('type', 'password');
  await expect(page.getByLabel(/^비밀번호/)).toHaveAttribute('autocomplete', 'current-password');
  await fs.mkdir(evidence, { recursive: true });
  await page.screenshot({ path: `${evidence}/login-desktop.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `${evidence}/login-mobile.png`, fullPage: true });
});

test('연결 대기·실패·재시도 상태를 분리한다', async ({ page }) => {
  let recover = false;
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route('**/api/auth/session', async (route) => {
    if (recover) {
      await route.fulfill({ json: { enabled: true, user: null } });
      return;
    }
    await gate;
    await route.fulfill({ status: 503, json: { detail: '검증용 연결 실패 메시지. '.repeat(30) } });
  });
  await page.goto('/');
  await expect(page.getByRole('status')).toContainText('연결 중');
  await expect(page.locator('.auth-description')).toHaveText(
    '서버 연결과 로그인 상태를 확인하고 있어요.',
  );
  await page.screenshot({ path: `${evidence}/connecting-copy-review.png`, fullPage: true });
  release();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.locator('.auth-description')).toHaveText(
    '서버 연결에 실패했어요. 연결 상태를 확인한 뒤 다시 시도해 주세요.',
  );
  await expect(page.locator('.auth-description')).not.toContainText('확인하고 있어요');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `${evidence}/connection-error-copy-review.png`, fullPage: true });
  recover = true;
  await page.getByRole('button', { name: '다시 연결' }).click();
  await expect(page.getByLabel(/^사용자 이름/)).toBeVisible();
});

test('native required·busy·실패 후 비밀번호 삭제 계약을 보존한다', async ({ page }) => {
  let loginCalls = 0;
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route('**/api/auth/session', (route) =>
    route.fulfill({ json: { enabled: true, user: null } }),
  );
  await page.route('**/api/auth/login', async (route) => {
    loginCalls += 1;
    expect(route.request().method()).toBe('POST');
    expect(Object.keys(route.request().postDataJSON()).sort()).toEqual(['password', 'username']);
    await gate;
    await route.fulfill({ status: 401, json: { detail: '검증용 로그인 거부' } });
  });
  await page.goto('/');
  const user = page.getByLabel(/^사용자 이름/);
  const password = page.getByLabel(/^비밀번호/);
  await expect(user).toBeVisible();
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  expect(loginCalls).toBe(0);
  await user.fill('ui-fixture-user');
  await password.fill('fixture-not-a-secret');
  await password.press('Enter');
  await expect(page.getByRole('button', { name: /로그인 중/ })).toBeDisabled();
  await expect(user).toBeDisabled();
  await expect(password).toBeDisabled();
  release();
  await expect(page.getByRole('alert')).toContainText('검증용 로그인 거부');
  await expect(password).toHaveValue('');
  await expect(user).toHaveValue('ui-fixture-user');
  expect(loginCalls).toBe(1);
  await page.screenshot({ path: `${evidence}/login-error.png`, fullPage: true });
});

test('로그인 성공 및 세션 만료를 기존 workspace와 재로그인으로 연결한다', async ({ page }) => {
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    const values: Record<string, unknown> = {
      '/api/auth/session': { enabled: true, user: null },
      '/api/auth/login': {
        enabled: true,
        user: { id: 'fixture', username: 'ui-fixture-user' },
        csrf_token: 'test-only-csrf',
      },
      '/api/videos': { videos: [] },
      '/api/jobs': { jobs: [] },
      '/api/video-uploads': { uploads: [] },
    };
    return route.fulfill({ json: values[path] ?? {} });
  });
  await page.goto('/');
  await page.getByLabel(/^사용자 이름/).fill('ui-fixture-user');
  await page.getByLabel(/^비밀번호/).fill('fixture-not-a-secret');
  await page.getByLabel(/^비밀번호/).press('Enter');
  await expect(page.locator('.video-workspace')).toBeVisible();
  await expect(page.locator('[data-hangyeol]')).toHaveCount(0);
  await page.evaluate(async () => {
    const modulePath = '/src/auth-session.ts';
    const { sessionEvents } = await import(modulePath);
    sessionEvents.dispatchEvent(new Event('expired'));
  });
  await expect(page.getByRole('alert')).toContainText('세션이 만료되었습니다');
  await expect(page.getByLabel(/^비밀번호/)).toHaveValue('');
});
