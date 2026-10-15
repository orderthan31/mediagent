import { expect, test } from '@playwright/test';
import fs from 'node:fs/promises';

const evidence = 'docs/evidence/REN-03';
const runtimeErrors: string[] = [];
test.afterEach(() => {
  expect(runtimeErrors).toEqual([]);
});
const video = {
  asset_id: 'a'.repeat(32),
  original_filename: '아주_긴_원본_촬영_파일명_재생시간이_아직_확인되지_않은_인터뷰_영상.mp4',
  size_bytes: 20971520,
  created_at: '2026-10-14T00:00:00Z',
  provenance: { kind: 'upload' },
};

test.beforeEach(async ({ page }) => {
  runtimeErrors.length = 0;
  page.on('pageerror', (error) => runtimeErrors.push(error.message));
  await fs.mkdir(evidence, { recursive: true });
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/thumbnail') || path.endsWith('/stream')) {
      return route.fulfill({ status: 404 });
    }
    const payload: Record<string, unknown> = {
      '/api/auth/session': { enabled: false, user: null },
      '/api/videos': { videos: [video] },
      '/api/jobs': { jobs: [] },
      '/api/video-uploads': { uploads: [] },
      [`/api/videos/${video.asset_id}`]: { video, jobs: [] },
      [`/api/videos/${video.asset_id}/subtitles`]: { subtitles: [] },
    };
    return route.fulfill({ json: payload[path] ?? {} });
  });
});

test('새 목록/업로드 빈 상태와 조회 실패의 미확정 개수·업로드 행동을 구분한다', async ({
  page,
}) => {
  let fail = false;
  await page.route('**/api/videos', (route) =>
    fail
      ? route.fulfill({ status: 503, json: { detail: '검증용 목록 조회 실패' } })
      : route.fulfill({ json: { videos: [] } }),
  );
  await page.goto('/');
  await expect(page.locator('.workspace-page-actions > span')).toHaveText('0개');
  await expect(
    page.getByRole('heading', { name: '등록된 원본 영상이 없습니다.', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('heading', { name: '진행 중인 업로드가 없습니다.', exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: `${evidence}/empty-library.png`, fullPage: true });
  fail = true;
  await expect(page.locator('.workspace-page-actions > span')).toHaveText(
    '마지막 확인 0개 · 최신이 아닐 수 있음',
  );
  await expect(page.getByRole('button', { name: '영상 업로드', exact: true })).toBeEnabled();
  await page.screenshot({ path: `${evidence}/stale-library.png`, fullPage: true });
  await page.reload();
  await expect(page.locator('.workspace-page-actions > span')).toHaveText('개수 확인 불가');
  await expect(
    page.getByRole('heading', { name: '등록된 원본 영상이 없습니다.', exact: true }),
  ).not.toBeVisible();
  await expect(page.getByRole('button', { name: '영상 업로드', exact: true })).toBeEnabled();
  await page.screenshot({ path: `${evidence}/offline-library.png`, fullPage: true });
});

test('PC 목록·원본/결과 출처·검색 없음·상세 정보 위계를 보존한다', async ({ page }) => {
  const knownVideo = {
    ...video,
    media: { duration: 125, width: 1920, height: 1080, has_audio: true },
  };
  await page.route('**/api/videos', (route) =>
    route.fulfill({
      json: {
        videos: [
          knownVideo,
          {
            ...video,
            asset_id: 'b'.repeat(32),
            original_filename: '작업_결과에서_등록한_영상.mp4',
            provenance: { kind: 'result', parent_asset_id: video.asset_id },
          },
        ],
      },
    }),
  );
  await page.route(`**/api/videos/${video.asset_id}`, (route) =>
    route.fulfill({ json: { video: knownVideo, jobs: [] } }),
  );
  await page.goto('/');
  await expect(page.locator('.asset-row')).toHaveCount(2);
  await expect(page.getByText('2분 5초', { exact: true })).toBeVisible();
  await expect(page.getByText('결과에서 등록', { exact: true })).toBeVisible();
  await page.screenshot({ path: `${evidence}/library-desktop.png`, fullPage: true });
  await page.getByLabel('영상 검색', { exact: true }).fill('없는 파일');
  await expect(
    page.getByRole('heading', { name: '검색 결과가 없습니다.', exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: `${evidence}/search-empty.png`, fullPage: true });
  await page.getByRole('button', { name: '영상 검색 지우기' }).click();
  await page.locator('.asset-row').first().click();
  await expect(page.getByText('첨부된 자막이 없습니다.', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '원본 다운로드', exact: true })).toHaveAttribute(
    'href',
    `/api/videos/${video.asset_id}/download`,
  );
  await expect(page.locator('.storage-preview video')).toHaveAttribute('preload', 'none');
  await page.screenshot({ path: `${evidence}/detail-desktop.png`, fullPage: true });
});

test('기존 직렬 queue의 대기·전송·중단·등록·완료·integrity/chunk 오류·재시도·제거를 보존한다', async ({
  page,
}) => {
  let correctSize = false;
  let failRegistration = true;
  let firstChunk = true;
  let releaseChunk!: () => void;
  let releaseComplete!: () => void;
  const chunkGate = new Promise<void>((resolve) => {
    releaseChunk = resolve;
  });
  const completeGate = new Promise<void>((resolve) => {
    releaseComplete = resolve;
  });
  await page.route('**/api/video-uploads**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/video-uploads') {
      if (request.method() === 'POST') {
        const name = request.postDataJSON().filename;
        return route.fulfill({
          json: {
            upload_id: name.startsWith('integrity')
              ? 'error-id'
              : name.startsWith('transfer')
                ? 'transfer-id'
                : 'queued-id',
          },
        });
      }
      return route.fulfill({ json: { uploads: [] } });
    }
    if (path.endsWith('/verify')) {
      return route.fulfill({ status: 204 });
    }
    if (path.endsWith('/chunks')) {
      if (path.includes('error-id')) {
        return route.fulfill({ status: 400, json: { detail: '검증용 chunk 오류' } });
      }
      if (path.includes('transfer-id') && firstChunk) {
        firstChunk = false;
        await chunkGate;
      }
      return route.fulfill({ json: { uploaded_bytes: 8 } }).catch(() => {});
    }
    if (path.endsWith('/complete')) {
      if (path.includes('queued-id')) {
        await completeGate;
        if (failRegistration) {
          return route.fulfill({ status: 400, json: { detail: '검증용 영상 등록 실패' } });
        }
      }
      return route.fulfill({ json: {} }).catch(() => {});
    }
    return route.fulfill({
      json: {
        uploaded_bytes: path.includes('queued-id') ? 8 : path.includes('transfer-id') ? 4 : 0,
        expected_size: path.includes('error-id') && !correctSize ? 9 : 8,
        resumable: true,
      },
    });
  });
  try {
    await page.goto('/');
    await page
      .locator('input[type=file]')
      .first()
      .setInputFiles(
        ['integrity-fixture.mp4', 'transfer-fixture.mp4', 'queued-fixture.mp4'].map((name) => ({
          name,
          mimeType: 'video/mp4',
          buffer: Buffer.alloc(8),
        })),
      );
    const card = (name: string) =>
      page
        .locator('.storage-upload')
        .filter({ has: page.getByRole('heading', { name, exact: true }) });
    await expect(card('integrity-fixture.mp4').getByRole('alert')).toHaveText(
      '원본 파일과 크기가 일치해야 합니다.',
    );
    await expect(card('transfer-fixture.mp4')).toContainText('50%');
    await expect(card('transfer-fixture.mp4')).toContainText('4 B / 8 B');
    await expect(card('queued-fixture.mp4')).toContainText('전송 대기');
    await page.screenshot({ path: `${evidence}/queue-desktop.png`, fullPage: true });
    await page
      .getByRole('button', { name: '업로드 일시정지: transfer-fixture.mp4', exact: true })
      .click();
    releaseChunk();
    await expect(card('transfer-fixture.mp4')).toContainText('일시정지');
    await expect(card('queued-fixture.mp4')).toContainText('영상 확인 및 등록 중');
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: `${evidence}/queue-mobile.png`, fullPage: true });
    releaseComplete();
    await expect(card('queued-fixture.mp4').getByRole('alert')).toHaveText('검증용 영상 등록 실패');
    await page.screenshot({ path: `${evidence}/registration-failed-mobile.png`, fullPage: true });
    failRegistration = false;
    await page
      .getByRole('button', { name: '업로드 재시도: queued-fixture.mp4', exact: true })
      .click();
    await expect(card('queued-fixture.mp4')).toContainText('완료');
    await page
      .getByRole('button', { name: '업로드 재개: transfer-fixture.mp4', exact: true })
      .click();
    await expect(card('transfer-fixture.mp4')).toContainText('완료');
    await page.screenshot({ path: `${evidence}/queue-completed-mobile.png`, fullPage: true });
    correctSize = true;
    await page
      .getByRole('button', { name: '업로드 재시도: integrity-fixture.mp4', exact: true })
      .click();
    await expect(card('integrity-fixture.mp4').getByRole('alert')).toHaveText('검증용 chunk 오류');
    await page
      .getByRole('button', { name: '업로드 제거: integrity-fixture.mp4', exact: true })
      .click();
    await expect(card('integrity-fixture.mp4')).toHaveCount(0);
  } finally {
    releaseChunk();
    releaseComplete();
  }
});

test('불완전 세션·등록 재시도·삭제 확인을 명확한 업로드 카드로 보존한다', async ({ page }) => {
  const sessions = [
    {
      upload_id: 'ready-session',
      filename: '등록_대기_촬영본.mp4',
      expected_size: 10485760,
      uploaded_bytes: 10485760,
      status: 'READY',
      created_at: '2026-10-14T00:00:00Z',
    },
    {
      upload_id: 'partial-session',
      filename: '중단된_아주_긴_원본_업로드_파일을_선택해서_재개해야_하는_촬영본.mp4',
      expected_size: 20971520,
      uploaded_bytes: 10485760,
      status: 'UPLOADING',
      created_at: '2026-10-14T00:00:00Z',
    },
  ];
  let completed = 0;
  let deleted = 0;
  await page.route('**/api/video-uploads**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/complete')) {
      completed++;
      return route.fulfill({ json: {} });
    }
    if (route.request().method() === 'DELETE') {
      deleted++;
      return route.fulfill({ status: 403, json: { detail: '검증용 삭제 권한 오류' } });
    }
    return route.fulfill({ json: { uploads: sessions } });
  });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '업로드', exact: true })).toBeVisible();
  await expect(page.locator('.storage-upload')).toHaveCount(2);
  await page
    .getByRole('button', { name: '영상 등록 재시도: 등록_대기_촬영본.mp4', exact: true })
    .click();
  await expect.poll(() => completed).toBe(1);
  const picker = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: /^파일 선택 후 업로드 재개:/ }).click();
  expect(await picker).toBeTruthy();
  await page.screenshot({ path: `${evidence}/sessions-desktop.png`, fullPage: true });
  await page.getByRole('button', { name: /^업로드 삭제: 중단된/ }).click();
  await expect(page.getByRole('dialog')).toContainText('업로드를 삭제할까요?');
  await page.screenshot({ path: `${evidence}/session-delete-confirm.png`, fullPage: true });
  expect(deleted).toBe(0);
  await page.getByRole('button', { name: '삭제', exact: true }).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('검증용 삭제 권한 오류');
  expect(deleted).toBe(1);
  await page.getByRole('button', { name: '취소', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `${evidence}/sessions-mobile.png`, fullPage: true });
});

test('모바일 원본의 명확한 열기·미확인 메타데이터에서 실제 상세와 삭제 취소로 연결한다', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  const row = page.locator('.asset-row').first();
  await expect(row.getByText('영상 열기', { exact: true })).toBeVisible();
  await expect(row.getByText('재생시간 미확인', { exact: true })).toBeVisible();
  await expect(row).not.toContainText('· 20.0 MB');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `${evidence}/library-mobile.png`, fullPage: true });
  await row.click();
  await expect(page).toHaveURL(new RegExp(video.asset_id));
  await expect(page.getByRole('heading', { name: '영상 정보', exact: true })).toBeVisible();
  await expect(page.getByText('첨부된 자막이 없습니다.', { exact: true })).toBeVisible();
  await page.screenshot({ path: `${evidence}/detail-mobile.png`, fullPage: true });
  await page.getByRole('button', { name: '원본 삭제', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('연결된 작업이 있으면 삭제할 수 없습니다.');
  await page.getByRole('button', { name: '취소', exact: true }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
});
