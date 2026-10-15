import { expect, test } from '@playwright/test';
import fs from 'node:fs/promises';
const evidence = 'docs/evidence/INT-03/regression-workflow';
const asset = 'a'.repeat(32);
const video = {
  asset_id: asset,
  original_filename: '긴_인터뷰_원본과_워크플로우_입력_확인을_위한_영상.mp4',
  size_bytes: 2000,
  created_at: '2026-10-14T00:00:00Z',
  provenance: { kind: 'upload' },
};
const fullPlan = {
  version: 1,
  template: 'full',
  stages: [
    'analyze',
    'extract_audio',
    'preprocess_audio',
    'transcribe',
    'translate',
    'generate_subtitle',
    'encode',
    'validate_video',
  ],
  reused: [],
  paid_stages: ['transcribe', 'translate'],
};
const errors: string[] = [];
test.beforeEach(async ({ page }) => {
  errors.length = 0;
  page.on('pageerror', (e) => errors.push(e.message));
  await fs.mkdir(evidence, { recursive: true });
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/stream') || path.endsWith('/thumbnail')) {
      return route.fulfill({ status: 404 });
    }
    const payload: Record<string, unknown> = {
      '/api/auth/session': { enabled: false, user: null },
      '/api/videos': { videos: [video] },
      '/api/jobs': { jobs: [] },
      '/api/video-uploads': { uploads: [] },
      [`/api/videos/${asset}`]: { video, jobs: [] },
      [`/api/videos/${asset}/subtitles`]: { subtitles: [] },
      [`/api/videos/${asset}/audio-inputs`]: { audio_inputs: [] },
      [`/api/videos/${asset}/workflow-plan`]: fullPlan,
    };
    return route.fulfill({ json: payload[path] ?? {} });
  });
});
test.afterEach(() => expect(errors).toEqual([]));

test('유료 단계는 별도 확인 전 form submit도 거부하고 같은 payload 재시도는 request_id를 보존한다', async ({
  page,
}) => {
  const bodies: Record<string, unknown>[] = [];
  await page.route(`**/api/videos/${asset}/jobs`, (route) => {
    bodies.push(route.request().postDataJSON());
    return route.fulfill({ status: 503, json: { detail: 'fixture 생성 실패 · 실제 실행 없음' } });
  });
  await page.goto(`/#/videos/${asset}`);
  await page.getByRole('button', { name: '새 작업', exact: true }).click();
  const dialog = page.getByRole('dialog');
  const start = dialog.getByRole('button', { name: '작업 시작', exact: true });
  await expect(dialog.getByRole('heading', { name: '유료 단계 확인', exact: true })).toBeVisible();
  await expect(start).toBeDisabled();
  await dialog
    .locator('form')
    .evaluate((form) =>
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })),
    );
  expect(bodies).toHaveLength(0);
  await page.screenshot({ path: `${evidence}/settings-desktop.png`, fullPage: true });
  await dialog.locator('.workflow-paid').scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${evidence}/paid-unconfirmed-desktop.png`, fullPage: true });
  await dialog
    .getByRole('checkbox', { name: '표시된 유료 단계의 실행을 확인했습니다.', exact: true })
    .check();
  await expect(start).toBeEnabled();
  await dialog.locator('form').evaluate((form) => {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await expect(dialog.getByRole('alert')).toHaveText('fixture 생성 실패 · 실제 실행 없음');
  expect(bodies).toHaveLength(1);
  expect(bodies[0]).toMatchObject({
    template: 'full',
    subtitle_artifact_id: null,
    audio_job_id: null,
    options: { target_language: 'ko', subtitle_mode: 'burn' },
  });
  expect(bodies[0].request_id).toEqual(expect.any(String));
  await start.click();
  await expect.poll(() => bodies.length).toBe(2);
  expect(bodies[1].request_id).toBe(bodies[0].request_id);
  await expect(start).toBeEnabled();
  await page.screenshot({ path: `${evidence}/paid-confirmed-error-desktop.png`, fullPage: true });
});

test('옵션·음성·원본·계획 갱신에 이전 확인을 승계하지 않는다', async ({ page }) => {
  const bodies: Record<string, unknown>[] = [];
  const audioId = 'b'.repeat(32);
  await page.route(`**/api/videos/${asset}/audio-inputs`, (r) =>
    r.fulfill({
      json: { audio_inputs: [{ job_id: audioId, created_at: video.created_at, size_bytes: 200 }] },
    }),
  );
  await page.route(`**/api/videos/${asset}/workflow-plan`, (r) => {
    const body = r.request().postDataJSON();
    return r.fulfill({
      json: {
        ...fullPlan,
        reused: body.audio_job_id ? ['audio'] : [],
        stages: body.audio_job_id
          ? fullPlan.stages.filter((s) => s !== 'extract_audio')
          : fullPlan.stages,
      },
    });
  });
  await page.route(`**/api/videos/${asset}/jobs`, (r) => {
    bodies.push(r.request().postDataJSON());
    return r.fulfill({ status: 503, json: { detail: 'fixture 생성 실패' } });
  });
  await page.goto(`/#/videos/${asset}`);
  await page.getByRole('button', { name: '새 작업', exact: true }).click();
  const dialog = page.getByRole('dialog');
  const consent = dialog.getByRole('checkbox', {
    name: '표시된 유료 단계의 실행을 확인했습니다.',
    exact: true,
  });
  const start = dialog.getByRole('button', { name: '작업 시작', exact: true });
  await consent.check();
  await start.click();
  await expect(dialog.getByRole('alert')).toHaveText('fixture 생성 실패');
  const choices = [
    ['원본 언어', 'en'],
    ['무음 필터', 'off'],
    ['번역 언어', 'en'],
    ['코덱', 'h264'],
    ['화질', 'high'],
    ['해상도', '720p'],
    ['자막 출력', 'soft'],
    ['음성 입력', audioId],
  ];
  for (const [label, value] of choices) {
    await dialog.getByRole('combobox', { name: label, exact: true }).selectOption(value);
    await expect(consent).not.toBeChecked();
    await expect(start).toBeDisabled();
    await dialog
      .locator('form')
      .evaluate((f) => f.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
    expect(bodies).toHaveLength(1);
    await consent.check();
  }
  await dialog.getByRole('checkbox', { name: 'NVIDIA 음성 감지', exact: true }).check();
  await expect(consent).not.toBeChecked();
  await consent.check();
  await dialog
    .getByLabel('영상 설명', { exact: true })
    .fill('옵션 변경은 같은 단계 목록이어도 새 확인이 필요합니다.');
  await expect(consent).not.toBeChecked();
  await consent.check();
  await dialog.getByRole('button', { name: '계획 다시 확인', exact: true }).click();
  await expect(consent).not.toBeChecked();
  await expect(dialog.getByText('재사용: 추출 음성', { exact: true })).toBeVisible();
  await consent.check();
  await start.click();
  await expect.poll(() => bodies.length).toBe(2);
  await expect(start).toBeEnabled();
  expect(bodies[1].request_id).not.toBe(bodies[0].request_id);
  expect(bodies[1]).toMatchObject({
    audio_job_id: audioId,
    options: {
      source_language: 'en',
      target_language: 'en',
      audio_filter: 'off',
      video_codec: 'h264',
      quality_profile: 'high',
      resolution: '720p',
      subtitle_mode: 'soft',
      vad_mode: 'nvidia',
    },
  });
  const other = 'b'.repeat(32);
  await page.route(`**/api/videos/${other}`, (r) =>
    r.fulfill({
      json: { video: { ...video, asset_id: other, original_filename: '다른_원본.mp4' }, jobs: [] },
    }),
  );
  await page.route(`**/api/videos/${other}/subtitles`, (r) =>
    r.fulfill({ json: { subtitles: [] } }),
  );
  await page.route(`**/api/videos/${other}/audio-inputs`, (r) =>
    r.fulfill({ json: { audio_inputs: [] } }),
  );
  await page.route(`**/api/videos/${other}/workflow-plan`, (r) => r.fulfill({ json: fullPlan }));
  await page.evaluate((id) => {
    location.hash = `/videos/${id}`;
  }, other);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: '새 작업', exact: true }).click();
  await expect(consent).not.toBeChecked();
  await expect(start).toBeDisabled();
});

test('계획 대기·실패·유료 정보 누락과 늦은 이전 응답은 생성 허가가 아니다', async ({ page }) => {
  let phase = 'hold';
  const release: (() => void)[] = [];
  let sent = 0;
  await page.route(`**/api/videos/${asset}/jobs`, (r) => {
    sent++;
    return r.fulfill({ status: 503 });
  });
  await page.route(`**/api/videos/${asset}/workflow-plan`, async (r) => {
    const mode = phase;
    const input = r.request().postDataJSON();
    if (mode === 'hold') {
      await new Promise<void>((resolve) => release.push(resolve));
    }
    if (mode === 'failure') {
      return r.fulfill({ status: 503, json: { detail: 'fixture 계획 조회 실패' } });
    }
    if (mode === 'missing') {
      return r.fulfill({ json: { stages: ['analyze'], reused: [] } });
    }
    return r.fulfill({
      json:
        input.template === 'extract_audio'
          ? {
              template: 'extract_audio',
              stages: ['analyze', 'extract_audio'],
              reused: [],
              paid_stages: [],
            }
          : fullPlan,
    });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/#/videos/${asset}`);
  await page.getByRole('button', { name: '새 작업', exact: true }).click();
  const dialog = page.getByRole('dialog');
  const start = dialog.getByRole('button', { name: '작업 시작', exact: true });
  const retry = dialog.getByRole('button', { name: '계획 다시 확인', exact: true });
  await expect.poll(() => release.length).toBeGreaterThan(0);
  await expect(start).toBeDisabled();
  await dialog
    .locator('form')
    .evaluate((f) => f.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(sent).toBe(0);
  await dialog.locator('.workflow-plan').scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${evidence}/plan-loading-mobile.png`, fullPage: true });
  phase = 'ready';
  release.splice(0).forEach((resolve) => resolve());
  const consent = dialog.getByRole('checkbox', {
    name: '표시된 유료 단계의 실행을 확인했습니다.',
    exact: true,
  });
  await consent.check();
  phase = 'missing';
  await retry.click();
  await expect(dialog.getByRole('alert')).toContainText('유료 단계 정보를 확인할 수 없습니다');
  await expect(start).toBeDisabled();
  await dialog
    .locator('form')
    .evaluate((f) => f.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(sent).toBe(0);
  await page.screenshot({ path: `${evidence}/plan-missing-mobile.png`, fullPage: true });
  phase = 'failure';
  await retry.click();
  await expect(dialog.getByRole('alert')).toHaveText('fixture 계획 조회 실패');
  await expect(start).toBeDisabled();
  await page.screenshot({ path: `${evidence}/plan-failed-mobile.png`, fullPage: true });
  phase = 'ready';
  await retry.click();
  await consent.check();
  phase = 'hold';
  await dialog
    .getByRole('combobox', { name: '작업 종류', exact: true })
    .selectOption('extract_audio');
  await expect.poll(() => release.length).toBeGreaterThan(0);
  phase = 'ready';
  await dialog.getByRole('combobox', { name: '작업 종류', exact: true }).selectOption('full');
  await expect(consent).not.toBeChecked();
  release.splice(0).forEach((resolve) => resolve());
  await expect(start).toBeDisabled();
  await dialog
    .locator('form')
    .evaluate((f) => f.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(sent).toBe(0);
  await consent.check();
  await expect(start).toBeEnabled();
  expect(await dialog.evaluate((d) => d.scrollWidth <= d.clientWidth)).toBe(true);
  await dialog.locator('.workflow-paid').scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${evidence}/paid-confirmed-mobile.png`, fullPage: true });
});

test('자막 가져오기·필수 선택·재사용·유료 없는 계획과 기존 티켓 생성 연결을 보존한다', async ({
  page,
}) => {
  const oldId = 'd'.repeat(32),
    newId = 'c'.repeat(32),
    artifact = 'e'.repeat(32);
  const job = {
    job_id: oldId,
    status: 'COMPLETED',
    original_filename: video.original_filename,
    expected_size: 2000,
    uploaded_bytes: 2000,
    source_language: 'auto',
    target_language: 'ko',
    quality_profile: 'balanced',
    created_at: video.created_at,
    completed_at: video.created_at,
    error: null,
    metadata: { asset_id: asset, result_files: ['original.srt'], subtitle_revision: 7 },
  };
  const added = {
    artifact_id: artifact,
    filename: '선택한_완료_자막의_긴_파일명_가져오기.srt',
    language: 'ko',
    cue_count: 42,
    created_at: video.created_at,
    provenance: { kind: 'job', revision: 7 },
  };
  const imports: unknown[] = [],
    creates: Record<string, unknown>[] = [];
  await page.route(`**/api/videos/${asset}`, (r) => r.fulfill({ json: { video, jobs: [job] } }));
  await page.route(`**/api/videos/${asset}/subtitle-inputs`, (r) => {
    imports.push(r.request().postDataJSON());
    return imports.length === 1
      ? r.fulfill({ status: 409, json: { detail: 'fixture 자막 가져오기 충돌' } })
      : r.fulfill({ json: added });
  });
  await page.route(`**/api/videos/${asset}/workflow-plan`, (r) => {
    const b = r.request().postDataJSON();
    const encode = b.template === 'encode';
    return r.fulfill({
      json: {
        stages: encode
          ? ['analyze', 'generate_subtitle', 'encode', 'validate_video']
          : ['analyze', 'translate', 'generate_subtitle'],
        reused: ['subtitle'],
        paid_stages: encode ? [] : ['translate'],
      },
    });
  });
  const created = {
    ...job,
    job_id: newId,
    status: 'QUEUED',
    completed_at: null,
    metadata: {
      asset_id: asset,
      workflow: {
        template: 'encode',
        stages: ['analyze', 'generate_subtitle', 'encode', 'validate_video'],
      },
    },
  };
  await page.route(`**/api/videos/${asset}/jobs`, (r) => {
    creates.push(r.request().postDataJSON());
    return r.fulfill({ json: created });
  });
  await page.route(`**/api/jobs/${newId}`, (r) => r.fulfill({ json: created }));
  await page.route(`**/api/jobs/${newId}/preview`, (r) =>
    r.fulfill({ json: { tracks: {}, languages: {} } }),
  );
  await page.goto(`/#/videos/${asset}`);
  await page.getByRole('button', { name: '새 작업', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('combobox', { name: '작업 종류', exact: true }).selectOption('translate');
  await expect(dialog.getByText('필수 자막 입력을 선택하세요.', { exact: true })).toBeVisible();
  const start = dialog.getByRole('button', { name: '작업 시작', exact: true });
  await expect(start).toBeDisabled();
  await dialog
    .getByRole('combobox', { name: '자막 입력', exact: true })
    .selectOption(`job:${oldId}:original:7`);
  await expect(dialog.getByRole('alert')).toHaveText('fixture 자막 가져오기 충돌');
  expect(creates).toHaveLength(0);
  await dialog
    .getByRole('combobox', { name: '자막 입력', exact: true })
    .selectOption(`job:${oldId}:original:7`);
  await expect(dialog.getByRole('combobox', { name: '자막 입력', exact: true })).toHaveValue(
    artifact,
  );
  expect(imports).toEqual([
    { job_id: oldId, track: 'original', revision: 7 },
    { job_id: oldId, track: 'original', revision: 7 },
  ]);
  const consent = dialog.getByRole('checkbox', {
    name: '표시된 유료 단계의 실행을 확인했습니다.',
    exact: true,
  });
  await expect(consent).not.toBeChecked();
  await expect(dialog.getByText('재사용: 선택한 자막', { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await dialog.evaluate((d) => {
    d.scrollTop = 0;
  });
  expect(await dialog.evaluate((d) => d.scrollWidth <= d.clientWidth)).toBe(true);
  await page.screenshot({ path: `${evidence}/imported-subtitle-mobile.png`, fullPage: true });
  await consent.check();
  await dialog.getByRole('combobox', { name: '자막 입력', exact: true }).selectOption('');
  await expect(start).toBeDisabled();
  await dialog.getByRole('combobox', { name: '자막 입력', exact: true }).selectOption(artifact);
  await expect(consent).not.toBeChecked();
  await dialog.getByRole('combobox', { name: '작업 종류', exact: true }).selectOption('encode');
  await expect(start).toBeDisabled();
  await dialog.getByRole('combobox', { name: '자막 입력', exact: true }).selectOption(artifact);
  await expect(start).toBeEnabled();
  await expect(consent).toHaveCount(0);
  await expect(
    dialog.getByText('현재 계획에 유료로 표시된 단계가 없습니다. 비용이 없다는 보장은 아닙니다.', {
      exact: true,
    }),
  ).toBeVisible();
  await dialog.locator('.workflow-plan').scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${evidence}/reuse-no-paid-mobile.png`, fullPage: true });
  await start.click();
  await expect(page).toHaveURL(new RegExp(`/#/jobs/${newId}$`));
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(creates).toHaveLength(1);
  expect(creates[0]).toMatchObject({
    template: 'encode',
    subtitle_artifact_id: artifact,
    audio_job_id: null,
    options: { subtitle_mode: 'burn' },
  });
});
