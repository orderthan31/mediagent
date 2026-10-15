import { expect, test, type Page } from '@playwright/test';
import fs from 'node:fs/promises';

const asset = 'a'.repeat(32),
  sessionId = 'b'.repeat(32),
  rendered = 'c'.repeat(32);
const evidence = 'docs/evidence/INT-03/S2-R1';
const filename = '안전_fixture_긴_영상명_얼굴합성_큐_저장공간_연결_검토.mp4';
const video = {
  asset_id: asset,
  original_filename: filename,
  size_bytes: 2048,
  created_at: '2026-10-15T00:00:00Z',
  provenance: { kind: 'upload' },
  media: { duration: 4, width: 640, height: 360, frame_rate: '25/1', has_audio: true },
};
const makeJob = (id: string, status = 'QUEUED') => ({
  job_id: id,
  status,
  original_filename: filename,
  expected_size: 2048,
  uploaded_bytes: 2048,
  source_language: 'auto',
  target_language: 'ko',
  quality_profile: 'balanced',
  created_at: video.created_at,
  completed_at: null,
  error: null,
  metadata: {
    asset_id: asset,
    workflow: { template: 'full', stages: ['analyze', 'transcribe', 'encode'] },
  },
});
const png = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=',
  'base64',
);

const fixture = async (page: Page) => {
  const errors: string[] = [],
    calls: {
      path: string;
      method: string;
      body?: unknown;
      status?: number;
      server_revision?: number;
    }[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.addInitScript(() => {
    document.addEventListener('DOMContentLoaded', () => {
      const note = document.createElement('div');
      note.textContent = '안전 API FIXTURE · 실제 엔진/처리/삭제/과금 없음';
      note.style.cssText =
        'position:sticky;top:0;z-index:99999;background:#fff3c4;color:#403214;text-align:center;padding:8px;font:13px sans-serif';
      document.body.prepend(note);
    });
  });
  const state = {
    ready: false,
    conflict: false,
    storageFail: false,
    saveFail: false,
    queue: {
      revision: 1,
      paused: false,
      order: ['d'.repeat(32), 'e'.repeat(32)],
      jobs: ['d'.repeat(32), 'e'.repeat(32)],
    },
    session: {
      session_id: sessionId,
      revision: 1,
      source_file: 'source.png',
      source_sha256: 'fixture-source-digest',
      settings: {
        reference_frame: 1,
        face_position: 0,
        source_position: 0,
        distance: 0.3,
        preset: 'balanced',
        video_codec: 'h264',
        mask_types: ['box'],
        mask_blur: 0.3,
        mask_padding: [0, 0, 0, 0],
        mask_areas: ['mouth'],
        mask_regions: ['skin'],
        detector_angles: [0],
      },
    },
    renderJob: null as ReturnType<typeof makeJob> | null,
  };
  let prefs = {
    revision: 1,
    transcription_provider: 'gemini',
    transcription_fallback_provider: 'openai',
    transcription_model: 'fixture-gemini',
    transcription_fallback_model: '',
    translation_provider: 'gemini',
    translation_fallback_provider: 'openai',
    translation_model: 'fixture-translation',
    translation_fallback_model: '',
    fallback_on_error: false,
    fallback_on_block: false,
    has_api_key: false,
    key_source: 'none',
    credentials: Object.fromEntries(
      ['gemini', 'openai', 'xai', 'openrouter', 'anthropic'].map((p) => [
        p,
        { has_api_key: false, key_source: 'none' },
      ]),
    ),
  };
  const faceJob = (operation: string) => ({
    ...makeJob(
      operation === 'preview'
        ? 'f'.repeat(32)
        : operation === 'analyze_source'
          ? '1'.repeat(32)
          : '2'.repeat(32),
      'COMPLETED',
    ),
    metadata: {
      faceswap_operation: operation,
      preview_resolution: 1024,
      faceswap: { ...structuredClone(state.session), fingerprint: 'fixture-engine' },
      faceswap_result: {
        frame_number: 1,
        frame_count: 100,
        fps: 25,
        matched_faces: 1,
        faces: [{ position: 0, bbox: [0.1, 0.1, 0.6, 0.7], file: 'face.png' }],
      },
    },
  });
  await page.route('**/api/**', async (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname,
      method = req.method();
    const body = method === 'GET' ? undefined : req.postDataJSON();
    calls.push({ path, method, body });
    if (path.endsWith('.png') || path.endsWith('/thumbnail')) {
      return route.fulfill({ contentType: 'image/png', body: png });
    }
    if (path.endsWith('/stream')) {
      return route.fulfill({ status: 404 });
    }
    if (path === '/api/auth/session') {
      return route.fulfill({ json: { enabled: false, user: null } });
    }
    if (path === '/api/videos') {
      return route.fulfill({ json: { videos: [video] } });
    }
    if (path === '/api/jobs') {
      return route.fulfill({
        json: {
          jobs: [
            ...state.queue.jobs.map((id) => makeJob(id)),
            ...(state.renderJob ? [state.renderJob] : []),
          ],
        },
      });
    }
    if (path === '/api/video-uploads') {
      return route.fulfill({ json: { uploads: [] } });
    }
    if (path === `/api/videos/${asset}`) {
      return route.fulfill({ json: { video, jobs: [] } });
    }
    if (path.endsWith('/subtitles')) {
      return route.fulfill({ json: { subtitles: [] } });
    }
    if (path.endsWith('/audio-inputs')) {
      return route.fulfill({ json: { audio_inputs: [] } });
    }
    if (path === '/api/queue') {
      if (method === 'PATCH') {
        if (state.conflict) {
          state.conflict = false;
          state.queue.revision++;
          return route.fulfill({
            status: 409,
            json: { detail: 'fixture 큐 revision 충돌 · 최신 상태 확인' },
          });
        }
        state.queue = {
          ...state.queue,
          ...body,
          revision: state.queue.revision + 1,
          jobs: body.order || state.queue.jobs,
        };
      }
      return route.fulfill({ json: state.queue });
    }
    if (path === '/api/queue/cancel-pending') {
      state.queue.jobs = state.queue.jobs.filter((id) => !body.job_ids.includes(id));
      return route.fulfill({
        json: { results: body.job_ids.map((id: string) => ({ job_id: id, status: 'cancelled' })) },
      });
    }
    if (path === '/api/settings/llm/stt-models') {
      return route.fulfill({
        json: {
          providers: {
            gemini: [],
            openai: ['whisper-1', 'gpt-4o-transcribe-diarize'],
            xai: ['grok-voice-transcribe-2.0'],
            openrouter: ['microsoft/mai-transcribe-2'],
          },
        },
      });
    }
    if (path === '/api/settings/llm') {
      const entry = calls[calls.length - 1];
      if (method === 'PUT') {
        if (state.saveFail) {
          state.saveFail = false;
          prefs = { ...prefs, revision: prefs.revision + 1 };
          Object.assign(entry, { status: 409, server_revision: prefs.revision });
          return route.fulfill({ status: 409, json: { detail: 'fixture 설정 충돌' } });
        }
        if (body.revision !== prefs.revision) {
          Object.assign(entry, { status: 409, server_revision: prefs.revision });
          return route.fulfill({
            status: 409,
            json: { detail: 'fixture stale revision · 설정 새로 불러오기 필요' },
          });
        }
        prefs = { ...prefs, ...body, revision: prefs.revision + 1 };
        delete (prefs as Record<string, unknown>).credential_updates;
      }
      Object.assign(entry, { status: 200, server_revision: prefs.revision });
      return route.fulfill({ json: prefs });
    }
    if (path === '/api/settings/storage') {
      if (state.storageFail) {
        return route.fulfill({ status: 503, json: { detail: 'fixture 저장소 조회 실패' } });
      }
      return route.fulfill({
        json: {
          checked_at: 1792022400,
          disk: { total_bytes: 1000000000000, used_bytes: 300000000000, free_bytes: 700000000000 },
          host_disk: null,
          container: true,
          total_bytes: 400000,
          quota_bytes: 900000,
          categories: { library: 200000, work: 100000, output: 100000 },
          jobs: [
            {
              job_id: '3'.repeat(32),
              filename,
              status: 'COMPLETED',
              input: 1000,
              work: 2000,
              output: 3000,
              total_bytes: 6000,
              temporary_bytes: 1500,
              deletable: true,
            },
            {
              job_id: '4'.repeat(32),
              filename: 'fixture_진행중_보호.mp4',
              status: 'ENCODING',
              input: 1000,
              work: 2000,
              output: 0,
              total_bytes: 3000,
              temporary_bytes: 0,
              deletable: false,
            },
          ],
        },
      });
    }
    if (path === '/api/settings/storage/cleanup') {
      return route.fulfill({ json: { removed_bytes: 1500, results: [{ status: 'cleaned' }] } });
    }
    if (path === '/api/faceswap/capabilities') {
      return route.fulfill({
        json: {
          ready: state.ready,
          reason: 'fixture 엔진 정지 상태',
          version: '3.9.0',
          fingerprint: 'fixture-engine',
          presets: ['fast', 'balanced', 'quality'],
        },
      });
    }
    if (path.endsWith('/faceswap-sessions')) {
      return route.fulfill({ json: { sessions: [state.session] } });
    }
    if (path === `/api/faceswap/sessions/${sessionId}`) {
      if (method === 'PUT') {
        state.session = {
          ...state.session,
          settings: body.settings,
          revision: state.session.revision + 1,
        };
      }
      return route.fulfill({ json: state.session });
    }
    if (path.endsWith('/requests')) {
      if (method === 'POST' && body.operation === 'render') {
        state.renderJob = {
          ...makeJob(rendered),
          metadata: {
            asset_id: asset,
            workflow: { template: 'faceswap', stages: ['faceswap', 'encode', 'validate_video'] },
          },
        };
        return route.fulfill({ status: 202, json: state.renderJob });
      }
      if (method === 'POST') {
        return route.fulfill({ status: 202, json: faceJob(body.operation) });
      }
      return route.fulfill({
        json: { jobs: ['analyze_source', 'analyze_reference', 'preview'].map(faceJob) },
      });
    }
    if (path === `/api/jobs/${rendered}`) {
      return route.fulfill({ json: state.renderJob });
    }
    if (path.endsWith('/preview')) {
      return route.fulfill({
        json: {
          video_available: false,
          expired: false,
          tracks: {
            original: { available: false, cues: [] },
            translated: { available: false, cues: [] },
          },
        },
      });
    }
    return route.fulfill({ status: 404, json: { detail: 'fixture未対応: ' + path } });
  });
  return { state, calls, errors };
};

for (const width of [1440, 390]) {
  test(`safe integrated operator journey ${width}px`, async ({ page }) => {
    test.setTimeout(90000);
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await fs.mkdir(evidence, { recursive: true });
    const { state, calls, errors } = await fixture(page);
    await page.goto('/#/jobs');
    const queue = page.getByRole('region', { name: '작업 큐' });
    await expect(queue.getByRole('button', { name: '새 작업 시작 일시정지' })).toBeEnabled();
    await queue.getByRole('button', { name: '새 작업 시작 일시정지' }).click();
    await expect(queue.getByRole('button', { name: '작업 시작 재개' })).toBeVisible();
    state.conflict = true;
    await queue.getByRole('button', { name: '아래로 이동' }).first().click();
    await expect(queue.getByRole('alert')).toContainText('revision 충돌');
    await queue.getByRole('button', { name: '아래로 이동' }).first().click();
    await expect.poll(() => state.queue.jobs[0]).toBe('e'.repeat(32));
    await queue.scrollIntoViewIfNeeded();

    await page.goto('/#/settings');
    await expect(page.getByLabel('전사 공급자', { exact: true })).toBeVisible();
    await page.getByLabel('전사 공급자', { exact: true }).selectOption('openai');
    await expect(page.getByLabel('전사 모델', { exact: true })).toHaveValue('');
    await page.getByLabel('전사 모델', { exact: true }).selectOption('whisper-1');
    state.saveFail = true;
    await page.getByRole('button', { name: '설정 저장', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('fixture 설정 충돌');
    await expect(page.getByLabel('전사 공급자', { exact: true })).toHaveValue('openai');
    await expect(page.getByLabel('전사 모델', { exact: true })).toHaveValue('whisper-1');
    const initialGets = calls.filter(
      (x) => x.path === '/api/settings/llm' && x.method === 'GET',
    ).length;
    await page.getByRole('button', { name: '설정 저장', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('fixture stale revision', {
      timeout: 3000,
    });
    await expect(
      page.getByText('저장했습니다. 다음 작업·재시도부터 적용됩니다.', { exact: true }),
    ).toHaveCount(0);
    expect(calls.filter((x) => x.path === '/api/settings/llm' && x.method === 'GET')).toHaveLength(
      initialGets,
    );
    await expect(page.getByLabel('전사 공급자', { exact: true })).toHaveValue('openai');
    await expect(page.getByLabel('전사 모델', { exact: true })).toHaveValue('whisper-1');
    await page.getByRole('alert').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${evidence}/stale-rejected-${width}.png` });
    await page.getByRole('button', { name: '설정 새로 불러오기', exact: true }).click();
    await expect(page.getByLabel('전사 공급자', { exact: true })).toHaveValue('gemini');
    await expect(page.getByLabel('전사 모델', { exact: true })).toHaveValue('fixture-gemini');
    await page.getByLabel('전사 공급자', { exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${evidence}/server-settings-reloaded-${width}.png` });
    await page.getByLabel('전사 공급자', { exact: true }).selectOption('openai');
    await expect(page.getByLabel('전사 모델', { exact: true })).toHaveValue('');
    await page.getByLabel('전사 모델', { exact: true }).selectOption('whisper-1');
    await page.getByRole('button', { name: '설정 저장', exact: true }).click();
    await expect(
      page.getByText('저장했습니다. 다음 작업·재시도부터 적용됩니다.', { exact: true }),
    ).toBeVisible();
    const storage = page.getByRole('region', { name: '저장 공간', exact: true });
    await expect(storage.getByRole('checkbox').nth(1)).toBeDisabled();
    await storage.getByRole('button', { name: '종료된 작업 선택' }).click();
    await storage.getByRole('button', { name: '중간 파일 비우기', exact: true }).click();
    await expect(storage.getByRole('group', { name: '파일 삭제 확인' })).toBeVisible();

    await storage.getByRole('button', { name: '취소', exact: true }).click();
    expect(calls.filter((x) => x.path.endsWith('/cleanup'))).toHaveLength(0);
    await page.getByLabel('전사 공급자', { exact: true }).scrollIntoViewIfNeeded();
    const revisionCalls = calls.filter((x) => x.path === '/api/settings/llm');
    expect(
      revisionCalls
        .slice(0, initialGets)
        .every((x) => x.method === 'GET' && x.status === 200 && x.server_revision === 1),
    ).toBe(true);
    const recoveryCalls = revisionCalls.slice(initialGets);
    expect(
      recoveryCalls.map((x) => [x.method, (x.body as { revision?: number } | undefined)?.revision]),
    ).toEqual([
      ['PUT', 1],
      ['PUT', 1],
      ['GET', undefined],
      ['PUT', 2],
    ]);
    expect(recoveryCalls.map((x) => [x.status, x.server_revision])).toEqual([
      [409, 2],
      [409, 2],
      [200, 2],
      [200, 3],
    ]);
    await page.screenshot({ path: `${evidence}/stt-reselected-saved-${width}.png` });
    await page.goto(`/#/videos/${asset}`);
    await page.getByRole('button', { name: '얼굴 합성', exact: true }).click();
    const dialog = page.getByRole('dialog');
    const render = dialog.getByRole('button', { name: '현재 설정으로 전체 영상 처리' });
    await expect(render).toBeDisabled();
    await expect(dialog.getByText('엔진 확인 필요', { exact: true })).toBeVisible();
    state.ready = true;
    await expect(render).toBeEnabled();
    await dialog.getByRole('checkbox', { name: '가림 처리', exact: true }).check();
    await expect.poll(() => state.session.settings.mask_types.includes('occlusion')).toBe(true);
    await expect(render).toBeEnabled();
    await dialog.evaluate((el) => {
      const note = document.createElement('p');
      note.textContent = '안전 API FIXTURE · 실제 엔진·처리 없음';
      note.style.cssText = 'background:#fff3c4;color:#403214;padding:8px;font-size:12px';
      el.prepend(note);
      el.scrollTop = 0;
    });

    await dialog.getByRole('heading', { name: '합성 설정', exact: true }).scrollIntoViewIfNeeded();

    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await render.click();
    await expect(page).toHaveURL(new RegExp(rendered));
    await expect(page.getByRole('region', { name: '얼굴 합성 작업' })).toBeVisible();
    const renderedBody = calls.find(
      (x) => x.method === 'POST' && (x.body as { operation?: string })?.operation === 'render',
    )?.body as Record<string, unknown>;
    expect(renderedBody.preview_job_id).toBe('f'.repeat(32));
    expect(renderedBody.request_id).toEqual(expect.any(String));
    if (state.renderJob) {
      state.renderJob.status = 'FACE_SWAPPING';
      Object.assign(state.renderJob.metadata, {
        stage_progress: 0.5,
        faceswap_chunks: { completed: 1, total: 2, current: 2, seconds: 600 },
        wait_reason: 'GPU 사용 대기',
        auto_recovery_count: 1,
      });
    }
    await page.reload();
    await expect(page.getByRole('progressbar', { name: '얼굴 합성 진행률' })).toBeVisible();

    expect(errors).toEqual([]);
    await fs.writeFile(
      `${evidence}/journey-${width}.json`,
      JSON.stringify({ fixture: true, externalCalls: false, width, calls, errors }, null, 2),
    );
  });
}
