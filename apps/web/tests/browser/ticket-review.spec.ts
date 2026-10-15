import { expect, test } from '@playwright/test';
import fs from 'node:fs/promises';

const evidence = 'docs/evidence/INT-03/regression-ticket';
const id = 'c'.repeat(32);
const original =
  '아주 긴 원문 자막입니다. 영상 처리와 검수 상태를 구분하고 긴 번역도 읽을 수 있어야 합니다.';
const job = {
  job_id: id,
  status: 'AWAITING_REVIEW',
  original_filename: '긴_입력_영상_티켓_검수_흐름_확인용_촬영본.mp4',
  expected_size: 1024,
  uploaded_bytes: 1024,
  source_language: 'auto',
  target_language: 'ko',
  quality_profile: 'balanced',
  created_at: '2026-10-14T00:00:00Z',
  completed_at: null,
  error: null,
  video_description: 'fixture 입력 영상 설명',
  metadata: {
    asset_id: 'a'.repeat(32),
    workflow: { template: 'full', stages: ['analyze', 'transcribe', 'translate', 'encode'] },
  },
};
const draft = {
  revision: 7,
  duration: 60,
  languages: { original: '원문', translated: '한국어' },
  tracks: {
    original: [{ start: 0, end: 4, text: original }],
    translated: [{ start: 0, end: 4, text: '검수할 번역 자막' }],
  },
};

test.beforeEach(async ({ page }) => {
  await fs.mkdir(evidence, { recursive: true });
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/stream') || path.endsWith('/thumbnail')) {
      return route.fulfill({ status: 404 });
    }
    const values: Record<string, unknown> = {
      '/api/auth/session': { enabled: false, user: null },
      '/api/jobs': { jobs: [job] },
      '/api/videos': { videos: [] },
      '/api/video-uploads': { uploads: [] },
      [`/api/jobs/${id}`]: job,
      [`/api/jobs/${id}/preview`]: {
        video_available: false,
        expired: false,
        tracks: {
          original: {
            available: true,
            partial: true,
            cues: [{ start: 0, end: 4, text: original }],
          },
          translated: {
            available: true,
            partial: true,
            cues: [{ start: 0, end: 4, text: '검수할 번역 자막' }],
          },
        },
      },
      [`/api/jobs/${id}/subtitles`]: draft,
    };
    return route.fulfill({ json: values[path] ?? {} });
  });
});

test('현재 단계·실패/부분 결과·대기는 실제 상태와 분리해 표시한다', async ({ page }) => {
  let active: Record<string, unknown> = {
    ...job,
    status: 'TRANSCRIBING',
    metadata: {
      ...job.metadata,
      transcription_progress: {
        total: 4,
        completed: 2,
        in_flight: 1,
        retrying: 0,
        failed: 0,
        draining: false,
      },
    },
  };
  await page.route(`**/api/jobs/${id}`, (route) => route.fulfill({ json: active }));
  await page.goto(`/#/jobs/${id}`);
  await expect(page.getByRole('progressbar', { name: '전사 진행률', exact: true })).toHaveAttribute(
    'aria-valuenow',
    '2',
  );
  await expect(page.locator('.ticket-plan [aria-current=step]')).toContainText('전사');
  await page.screenshot({ path: `${evidence}/progress-desktop.png`, fullPage: true });
  active = {
    ...job,
    status: 'FAILED',
    error: 'fixture 검증 오류',
    metadata: {
      ...job.metadata,
      failure: {
        kind: 'content_blocked',
        provider: 'Fixture',
        stage: 'TRANSLATING',
        blocks: [{ segment: 2, reason: 'BLOCKED' }],
      },
      translation_progress: {
        language: 'ko',
        total: 4,
        completed: 2,
        in_flight: 0,
        retrying: 0,
        failed: 1,
        draining: false,
      },
      failed_stage: 'TRANSLATING',
    },
  };
  await page.getByRole('button', { name: '새로고침', exact: true }).click();
  await expect(page.getByText('콘텐츠 차단', { exact: true })).toBeVisible();
  await expect(page.getByText(/자동 재시도는 중단했으며 완료된 결과는 보존됩니다/)).toBeVisible();
  await expect(page.getByRole('button', { name: '자막 검수', exact: true })).toHaveCount(0);
  await expect(
    page.getByText('읽기 전용 미리보기 · 현재 상태에서는 자막 편집을 제공하지 않습니다.', {
      exact: true,
    }),
  ).toBeVisible();
  await page.screenshot({ path: `${evidence}/blocked-desktop.png`, fullPage: true });
  active = {
    ...job,
    status: 'ENCODING',
    status_message: 'fixture 인코딩',
    metadata: { ...job.metadata, stage_progress: 0.66 },
  };
  await page.getByRole('button', { name: '새로고침', exact: true }).click();
  await expect(
    page.getByRole('progressbar', { name: '인코딩 진행률', exact: true }),
  ).toHaveAttribute('aria-valuenow', '0.66');
  active = { ...job, status: 'CANCELLED', metadata: { ...job.metadata, cancel_requested: true } };
  await page.getByRole('button', { name: '새로고침', exact: true }).click();
  await expect(page.getByText('중단됨', { exact: true })).toBeVisible();
  await expect(
    page.getByText('중단 요청됨 · 실행 중인 요청의 정리를 기다리고 있어요.', { exact: true }),
  ).toHaveCount(0);
  active = { ...job, status: 'QUEUED' };
  await page.getByRole('button', { name: '새로고침', exact: true }).click();
  await expect(page.getByText('처리 시작을 기다리고 있어요.', { exact: true })).toBeVisible();
  await expect(page.getByRole('progressbar')).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `${evidence}/queued-mobile.png`, fullPage: true });
});

test('완료 티켓의 결과 링크·원문/번역·저장 성공과 readonly 거부를 보존한다', async ({ page }) => {
  const done = {
    ...job,
    status: 'COMPLETED',
    metadata: { ...job.metadata, result_files: ['original.srt', 'translated.srt'] },
  };
  await page.route(`**/api/jobs/${id}`, (route) => route.fulfill({ json: done }));
  let readonly = false;
  let empty = false;
  let savedBody: Record<string, unknown> | null = null;
  await page.route(`**/api/jobs/${id}/subtitles`, (route) => {
    if (readonly) {
      return route.fulfill({ status: 403, json: { detail: '검증용 읽기 전용 자막입니다.' } });
    }
    if (route.request().method() === 'GET') {
      return route.fulfill({
        json: empty
          ? {
              ...draft,
              tracks: { original: [] },
              languages: { original: '원문' },
              allow_imported_layout: true,
            }
          : { ...draft, allow_imported_layout: true },
      });
    }
    savedBody = route.request().postDataJSON();
    expect(savedBody?.action).toBe('save');
    expect(savedBody?.revision).toBe(7);
    return route.fulfill({
      json: { ...draft, allow_imported_layout: true, revision: 8, tracks: savedBody?.tracks },
    });
  });
  await page.goto(`/#/jobs/${id}`);
  await expect(
    page.getByText('티켓 처리가 완료됐어요. 보관 중인 결과를 확인할 수 있어요.', { exact: true }),
  ).toBeVisible();
  await page.getByRole('tab', { name: '번역 자막', exact: true }).click();
  await expect(page.locator('.text-download a')).toHaveAttribute(
    'href',
    `/api/jobs/${id}/results/translated.srt`,
  );
  await page.locator('.result-downloads summary').click();
  await expect(page.locator('.result-downloads a')).toHaveCount(2);
  await page.locator('.result-downloads summary').click();
  await page.getByRole('button', { name: '자막 수정', exact: true }).click();
  const editor = page.getByRole('dialog', { name: '자막 수정', exact: true });
  await expect(
    editor.getByText('SRT·SMI 자막 파일에 반영됩니다. 기존 MP4의 자막은 변경되지 않습니다.', {
      exact: true,
    }),
  ).toBeVisible();
  await expect(editor.getByRole('button', { name: '최종 출력', exact: true })).toHaveCount(0);
  await editor.getByLabel('자막 1 문구', { exact: true }).fill('수입 자막 원문\n둘째 줄\n셋째 줄');
  await editor.getByRole('button', { name: '자막 저장', exact: true }).click();
  await expect(editor.getByText('저장되었습니다.', { exact: true })).toBeVisible();
  await expect(editor.getByLabel('자막 1 문구', { exact: true })).toHaveValue(
    '수입 자막 원문\n둘째 줄\n셋째 줄',
  );
  expect(savedBody).not.toBeNull();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await editor.getByLabel('자막 1 문구', { exact: true }).scrollIntoViewIfNeeded();
  await expect(editor.getByLabel('자막 1 문구', { exact: true })).toBeInViewport({ ratio: 0.5 });
  const startBox = await editor.getByLabel('자막 1 시작', { exact: true }).boundingBox();
  const endBox = await editor.getByLabel('자막 1 종료', { exact: true }).boundingBox();
  expect(Math.abs(startBox!.y - endBox!.y)).toBeLessThan(3);
  await page.screenshot({ path: `${evidence}/editor-saved-mobile.png`, fullPage: true });
  await editor.getByRole('button', { name: '편집 닫기', exact: true }).click();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: `${evidence}/completed-desktop.png`, fullPage: true });
  readonly = true;
  await page.getByRole('button', { name: '자막 수정', exact: true }).click();
  await expect(editor.getByRole('alert')).toHaveText('검증용 읽기 전용 자막입니다.');
  await expect(editor.getByLabel('자막 1 문구', { exact: true })).toHaveCount(0);
  await page.screenshot({ path: `${evidence}/readonly-editor.png`, fullPage: true });
  await editor.getByRole('button', { name: '편집 닫기', exact: true }).click();
  readonly = false;
  empty = true;
  await page.getByRole('button', { name: '자막 수정', exact: true }).click();
  await expect(
    editor.getByRole('heading', { name: '현재 트랙에 자막이 없습니다.', exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: `${evidence}/empty-editor.png`, fullPage: true });
});

test('검수 대기 티켓에서 부분 결과·요청 흐름을 구분하고 저장 충돌/실패 시 입력을 보존한다', async ({
  page,
}) => {
  let attempts = 0;
  await page.route(`**/api/jobs/${id}/subtitles`, (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ json: draft });
    }
    attempts++;
    const body = route.request().postDataJSON();
    expect(body.revision).toBe(7);
    expect(body.action).toBe('save');
    return route.fulfill({
      status: attempts === 1 ? 409 : 507,
      json: {
        detail:
          attempts === 1
            ? '다른 창에서 자막이 변경되었습니다. 최신 자막을 다시 불러오세요.'
            : '자막 저장 공간이 부족합니다.',
      },
    });
  });
  await page.goto(`/#/jobs/${id}`);
  await expect(page.getByText('티켓 상세', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '요청된 처리 흐름', exact: true })).toBeVisible();
  await expect(
    page.getByText('일부 결과 · 티켓 전체 완료를 뜻하지 않습니다.', { exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: `${evidence}/review-desktop.png`, fullPage: true });
  await page.getByRole('button', { name: '자막 검수', exact: true }).click();
  const editor = page.getByRole('dialog', { name: '자막 수정', exact: true });
  await editor.getByLabel('자막 1 문구', { exact: true }).fill('입력을 보존할 번역 문구');
  await editor.getByRole('button', { name: '초안 저장', exact: true }).click();
  await expect(editor.getByRole('alert')).toContainText('다른 창에서 자막이 변경되었습니다.');
  await expect(editor.getByLabel('자막 1 문구', { exact: true })).toHaveValue(
    '입력을 보존할 번역 문구',
  );
  await editor.getByRole('button', { name: '초안 저장', exact: true }).click();
  await expect(editor.getByRole('alert')).toContainText('자막 저장 공간이 부족합니다.');
  await expect(editor.getByLabel('자막 1 문구', { exact: true })).toHaveValue(
    '입력을 보존할 번역 문구',
  );
  await page.screenshot({ path: `${evidence}/editor-failed-desktop.png`, fullPage: true });
  await editor.getByRole('button', { name: '편집 닫기', exact: true }).click();
  await expect(editor.getByText('저장하지 않은 변경이 있습니다.', { exact: true })).toBeVisible();
  await editor.getByRole('button', { name: '계속 편집', exact: true }).click();
  await expect(editor.getByLabel('자막 1 문구', { exact: true })).toHaveValue(
    '입력을 보존할 번역 문구',
  );
});
