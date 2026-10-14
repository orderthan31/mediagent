import { expect, test } from '@playwright/test';
import fs from 'node:fs/promises';

const videos = [
  {
    asset_id: 'a'.repeat(32),
    original_filename: '인터뷰_원본.mp4',
    size_bytes: 10485760,
    created_at: '2026-10-14T00:00:00Z',
    media: { duration: 90, width: 1920, height: 1080, has_audio: true },
    provenance: { kind: 'upload' },
  },
  {
    asset_id: 'b'.repeat(32),
    original_filename:
      '길이가_긴_영상_제목에서도_기존_목록을_읽고_선택할_수_있는지_확인하는_촬영본.mp4',
    size_bytes: 20971520,
    created_at: '2026-10-14T00:00:00Z',
    provenance: { kind: 'upload' },
  },
];
const evidence = 'docs/evidence/REN-02';

// Explicit fixtures, no real authentication, media or paid execution.
test.beforeEach(async ({ page }) => {
  await fs.mkdir(evidence, { recursive: true });
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/thumbnail')) {
      return route.fulfill({ status: 404 });
    }
    const values: Record<string, unknown> = {
      '/api/auth/session': { enabled: false, user: null },
      '/api/videos': { videos },
      '/api/jobs': { jobs: [] },
      '/api/video-uploads': { uploads: [] },
    };
    if (path === `/api/videos/${videos[0].asset_id}`) {
      return route.fulfill({ json: { video: videos[0], jobs: [] } });
    }
    if (path.endsWith('/subtitles')) {
      return route.fulfill({ json: { subtitles: [] } });
    }
    if (path === '/api/settings/llm') {
      return route.fulfill({ status: 503, json: { detail: '검증용 설정 서버 오류' } });
    }
    return route.fulfill({ json: values[path] ?? {} });
  });
});

test('PC 공통 탐색·선택·검색·기존 영상 선택·업로드 행동을 연결한다', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('link', { name: '영상 보관함', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await expect(page.locator('.workspace-theme[data-palette="Indigo"]')).toBeVisible();
  await expect(page.locator('.workspace-header')).toHaveCSS('border-top-width', '0px');
  await expect(page.getByRole('heading', { name: '영상 보관함', exact: true })).toBeVisible();
  await expect(page.locator('.asset-row')).toHaveCount(2);
  await page.screenshot({ path: `${evidence}/desktop-library.png`, fullPage: true });
  const search = page.getByLabel('영상 검색', { exact: true });
  await search.fill('없는 영상');
  await expect(page.getByText('검색 결과가 없습니다.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '영상 검색 지우기' }).click();
  await expect(page.locator('.asset-row')).toHaveCount(2);
  const picker = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: '영상 업로드', exact: true }).click();
  expect(await picker).toBeTruthy();
  await page.locator('.asset-row').first().click();
  await expect(page).toHaveURL(new RegExp(videos[0].asset_id));
  await expect(page.getByText('첨부된 자막이 없습니다.', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '영상 보관함', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );
});

test('정상 연결된 빈 보관함에서 업로드 행동을 유지한다', async ({ page }) => {
  await page.route('**/api/videos', (route) => route.fulfill({ json: { videos: [] } }));
  await page.goto('/');
  await expect(page.getByText('서버 연결됨', { exact: true })).toBeVisible();
  await expect(page.getByText('등록된 원본 영상이 없습니다.', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '영상 업로드', exact: true })).toBeVisible();
  await page.screenshot({ path: `${evidence}/empty-library.png`, fullPage: true });
});

test('작은 화면에서 실제 메뉴·작업·설정 route와 검색 초기화를 연결한다', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.locator('.asset-row')).toHaveCount(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `${evidence}/mobile-library.png`, fullPage: true });
  await page.getByText('메뉴', { exact: true }).click();
  await page.screenshot({ path: `${evidence}/mobile-menu.png`, fullPage: true });
  await page.getByRole('link', { name: '작업 목록', exact: true }).click();
  await expect(page).toHaveURL(/#\/jobs$/);
  await expect(page.getByRole('heading', { name: '작업 목록', exact: true })).toBeVisible();
  await expect(page.locator('details[open]')).toHaveCount(0);
  await page.getByLabel('작업 검색', { exact: true }).fill('검증');
  await page.getByText('메뉴', { exact: true }).click();
  await page.getByRole('link', { name: '영상 보관함', exact: true }).click();
  await expect(page.getByLabel('영상 검색', { exact: true })).toHaveValue('');
  await page.getByText('메뉴', { exact: true }).click();
  await page.keyboard.press('Escape');
  await expect(page.locator('details[open]')).toHaveCount(0);
  await page.getByText('메뉴', { exact: true }).click();
  await page.getByRole('link', { name: '설정', exact: true }).click();
  await expect(page).toHaveURL(/#\/settings$/);
  await expect(page.getByRole('heading', { name: 'AI 공급자 설정', exact: true })).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('검증용 설정 서버 오류');
});
