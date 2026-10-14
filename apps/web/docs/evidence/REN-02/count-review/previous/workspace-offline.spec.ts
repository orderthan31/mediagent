import { expect, test } from '@playwright/test';

test('목록 연결 실패를 빈 보관함으로 확정하지 않고 기존 탐색을 유지한다', async ({ page }) => {
  await page.route('**/api/**', (route) => {
    if (new URL(route.request().url()).pathname === '/api/auth/session') {
      return route.fulfill({ json: { enabled: false, user: null } });
    }
    return route.fulfill({ status: 503, json: { detail: '검증용 목록 연결 실패' } });
  });
  await page.goto('/');
  await expect(page.getByText('서버 연결 확인 필요', { exact: true })).toBeVisible();
  await expect(
    page.getByText('서버 연결을 확인해 주세요. 목록 정보가 최신이 아닐 수 있어요.', {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByText('등록된 원본 영상이 없습니다.', { exact: true })).not.toBeVisible();
  await expect(page.getByRole('link', { name: '작업 목록', exact: true })).toBeVisible();
  await page.screenshot({ path: 'docs/evidence/REN-02/offline-library.png', fullPage: true });
});
