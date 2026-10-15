import { expect, test } from '@playwright/test';
import fs from 'node:fs/promises';
const evidence = 'docs/evidence/INT-03/regression-settings';
const fakeKey = 'fixture-only-not-a-real-api-key';
const fakeToken = 'fixture-only-not-a-real-session';
const longModel = 'fixture-model-' + 'long-model-id-'.repeat(8);
const preferences = {
  revision: 7,
  transcription_provider: 'gemini',
  transcription_fallback_provider: 'gemini',
  transcription_model: longModel,
  transcription_fallback_model: '',
  translation_model: 'fixture-translation',
  translation_fallback_model: '',
  translation_provider: 'gemini',
  translation_fallback_provider: 'openai',
  fallback_on_error: false,
  fallback_on_block: false,
  has_api_key: true,
  key_source: 'registered',
  credentials: {
    gemini: { has_api_key: true, key_source: 'registered' },
    openai: { has_api_key: true, key_source: 'environment' },
    xai: { has_api_key: false, key_source: 'none' },
    openrouter: { has_api_key: true, key_source: 'registered' },
    anthropic: { has_api_key: false, key_source: 'none' },
  },
};
const errors: string[] = [];
test.beforeEach(async ({ page }) => {
  errors.length = 0;
  page.on('pageerror', (e) => errors.push(e.message));
  await fs.mkdir(evidence, { recursive: true });
  await page.route('**/api/**', (r) => {
    const p = new URL(r.request().url()).pathname;
    const data: Record<string, unknown> = {
      '/api/auth/session': {
        enabled: true,
        user: { id: 'fixture-user', username: 'fixture-reviewer' },
        csrf_token: fakeToken,
      },
      '/api/settings/llm': preferences,
      '/api/settings/storage': {
        checked_at: 1792022400,
        disk: { total_bytes: 1000, used_bytes: 100, free_bytes: 900 },
        host_disk: null,
        container: true,
        total_bytes: 100,
        quota_bytes: 1000,
        categories: {},
        jobs: [],
      },
      '/api/settings/llm/stt-models': {
        providers: { gemini: [], openai: ['whisper-1'], xai: [], openrouter: [] },
      },
      '/api/videos': { videos: [] },
      '/api/jobs': { jobs: [] },
      '/api/video-uploads': { uploads: [] },
    };
    return r.fulfill({ json: data[p] ?? {} });
  });
});
test.afterEach(() => expect(errors).toEqual([]));

test('키 출처·변경 대기·모델 조회와 저장 충돌/키 초기화·성공 적용을 구분한다', async ({ page }) => {
  const puts: Record<string, unknown>[] = [],
    queries: string[] = [];
  await page.route('**/api/settings/llm/models?*', (r) => {
    queries.push(new URL(r.request().url()).searchParams.get('provider')!);
    return r.fulfill({ json: { models: ['fixture-lookup-one', longModel] } });
  });
  await page.route('**/api/settings/llm', (r) => {
    if (r.request().method() !== 'PUT') {
      return r.fulfill({ json: { ...preferences, revision: puts.length ? 8 : 7 } });
    }
    const body = r.request().postDataJSON();
    puts.push(body);
    expect(r.request().headers()['x-csrf-token']).toBe(fakeToken);
    return puts.length === 1
      ? r.fulfill({
          status: 409,
          json: { detail: '설정이 변경되었습니다. 새로 불러온 뒤 저장하세요.' },
        })
      : r.fulfill({
          json: {
            ...preferences,
            ...body,
            credential_updates: undefined,
            revision: 9,
            credentials: {
              ...preferences.credentials,
              openrouter: { has_api_key: false, key_source: 'none' },
            },
          },
        });
  });
  await page.goto('/#/settings');
  await expect(
    page.getByText('키 보유 상태와 모델 목록 조회는 연결·추론 성공을 뜻하지 않습니다.', {
      exact: true,
    }),
  ).toBeVisible();
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({ path: `${evidence}/settings-desktop.png`, fullPage: true });
  await page.getByRole('button', { name: 'Gemini 모델 목록 조회', exact: true }).click();
  await expect.poll(() => queries.length).toBe(1);
  expect(queries[0]).toBe('gemini');
  await page.getByRole('combobox', { name: '공급자', exact: true }).selectOption('openai');
  await page.getByRole('button', { name: 'OpenAI 모델 목록 조회', exact: true }).click();
  await expect.poll(() => queries.length).toBe(2);
  expect(queries[1]).toBe('openai');
  await page.getByRole('combobox', { name: '공급자', exact: true }).selectOption('xai');
  await expect(
    page.getByRole('button', { name: 'xAI (Grok) 모델 목록 조회', exact: true }),
  ).toBeDisabled();
  await page.getByRole('combobox', { name: '공급자', exact: true }).selectOption('openrouter');
  await page.getByRole('button', { name: '등록 키 삭제', exact: true }).click();
  await expect(page.getByText('등록 키 삭제 예정', { exact: true }).first()).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'OpenRouter 모델 목록 조회', exact: true }),
  ).toBeDisabled();
  await page.getByRole('button', { name: '등록 키 삭제 취소', exact: true }).click();
  await page.getByRole('button', { name: '등록 키 삭제', exact: true }).click();
  await page.getByRole('combobox', { name: '공급자', exact: true }).selectOption('gemini');
  await page.getByLabel('새 API 키', { exact: true }).fill(fakeKey);
  await expect(
    page.getByRole('button', { name: 'Gemini 모델 목록 조회', exact: true }),
  ).toBeDisabled();
  expect(await page.locator('body').innerText()).not.toContain(fakeKey);
  await page.getByLabel('전사 모델', { exact: true }).fill('fixture-edited-transcription');
  await page.getByRole('combobox', { name: '기본 공급자', exact: true }).selectOption('openai');
  await expect(page.getByLabel('번역 모델', { exact: true })).toHaveValue('');
  await page.getByLabel('번역 모델', { exact: true }).fill('fixture-edited-translation');
  await page.getByRole('checkbox', { name: '요청 오류 시 폴백 사용', exact: true }).check();
  await page.getByRole('button', { name: '설정 저장', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText(
    '설정이 변경되었습니다. 새로 불러온 뒤 저장하세요.',
  );
  await expect(page.getByLabel('새 API 키', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('전사 모델', { exact: true })).toHaveValue(
    'fixture-edited-transcription',
  );
  await expect(page.getByLabel('번역 모델', { exact: true })).toHaveValue(
    'fixture-edited-translation',
  );
  expect(puts[0]).toMatchObject({
    revision: 7,
    translation_provider: 'openai',
    transcription_fallback_model: '',
    translation_fallback_model: '',
    fallback_on_error: true,
    credential_updates: {
      gemini: { api_key: fakeKey, remove_api_key: false },
      openrouter: { remove_api_key: true },
    },
  });
  expect(puts[0]).not.toHaveProperty('credentials');
  expect(puts[0]).not.toHaveProperty('has_api_key');
  expect(puts[0]).not.toHaveProperty('key_source');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({ path: `${evidence}/conflict-mobile.png`, fullPage: true });
  await page.getByRole('button', { name: '설정 새로 불러오기', exact: true }).click();
  await expect(page.getByLabel('전사 모델', { exact: true })).toHaveValue(longModel);
  await expect(page.getByText('등록 키 삭제 예정', { exact: true })).toHaveCount(0);
  await page.getByRole('combobox', { name: '공급자', exact: true }).selectOption('openrouter');
  await page.getByRole('button', { name: '등록 키 삭제', exact: true }).click();
  await page.getByRole('combobox', { name: '공급자', exact: true }).selectOption('gemini');
  await page.getByLabel('새 API 키', { exact: true }).fill(fakeKey);
  await page.getByRole('button', { name: '설정 저장', exact: true }).click();
  await expect(
    page.getByText('저장했습니다. 다음 작업·재시도부터 적용됩니다.', { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel('새 API 키', { exact: true })).toHaveValue('');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({ path: `${evidence}/saved-mobile.png`, fullPage: true });
  expect(puts[1]).toHaveProperty('revision', 8);
  await expect(
    page
      .getByRole('list', { name: '공급자별 키 상태', exact: true })
      .locator('li')
      .filter({ hasText: 'OpenRouter' }),
  ).toContainText('사용할 키 없음');
  await page.getByLabel('번역 폴백 모델', { exact: true }).fill('fixture-new-fallback');
  await expect(
    page.getByText('저장했습니다. 다음 작업·재시도부터 적용됩니다.', { exact: true }),
  ).toHaveCount(0);
});

test('초기 조회/모델 조회·저장 대기와 실패 및 필수 입력을 구분한다', async ({ page }) => {
  let phase = 'hold';
  const pending: (() => void)[] = [];
  let releaseSave: (() => void) | undefined, releaseModels: (() => void) | undefined;
  let puts = 0;
  await page.route('**/api/settings/llm', async (r) => {
    if (r.request().method() === 'PUT') {
      puts++;
      await new Promise<void>((resolve) => {
        releaseSave = resolve;
      });
      return r.fulfill({ status: 503, json: { detail: 'fixture 설정 저장 실패' } });
    }
    const mode = phase;
    if (mode === 'hold') {
      await new Promise<void>((resolve) => pending.push(resolve));
    }
    return mode === 'ready'
      ? r.fulfill({ json: preferences })
      : r.fulfill({ status: 503, json: { detail: 'fixture 설정 조회 실패' } });
  });
  await page.route('**/api/settings/llm/models?*', async (r) => {
    await new Promise<void>((resolve) => {
      releaseModels = resolve;
    });
    return r.fulfill({
      status: 502,
      json: { detail: 'fixture 모델 조회 실패 · 직접 입력할 수 있습니다.' },
    });
  });
  await page.goto('/#/settings');
  await expect.poll(() => pending.length).toBeGreaterThan(0);
  await expect(page.getByText('설정을 불러오는 중입니다.', { exact: true })).toBeVisible();
  await expect(
    page.getByRole('button', { name: '설정 새로 불러오기', exact: true }),
  ).toBeDisabled();
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({ path: `${evidence}/loading-desktop.png`, fullPage: true });
  phase = 'failed';
  pending.splice(0).forEach((resolve) => resolve());
  await expect(page.getByRole('alert')).toHaveText('fixture 설정 조회 실패');
  await expect(page.getByRole('button', { name: '설정 저장', exact: true })).toHaveCount(0);
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({ path: `${evidence}/load-failed-desktop.png`, fullPage: true });
  phase = 'ready';
  await page.getByRole('button', { name: '설정 새로 불러오기', exact: true }).click();
  const model = page.getByLabel('전사 모델', { exact: true });
  await expect(model).toHaveValue(longModel);
  await model.fill('');
  await page.getByRole('button', { name: '설정 저장', exact: true }).click();
  expect(puts).toBe(0);
  expect(await model.evaluate((e: HTMLInputElement) => e.validity.valueMissing)).toBe(true);
  await model.fill('fixture-retained-model');
  await page.getByRole('button', { name: 'Gemini 모델 목록 조회', exact: true }).click();
  await expect(page.getByRole('button', { name: '모델 목록 조회 중', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '설정 저장', exact: true })).toBeDisabled();
  await expect.poll(() => !!releaseModels).toBe(true);
  releaseModels!();
  await expect(page.getByRole('alert')).toHaveText(
    'fixture 모델 조회 실패 · 직접 입력할 수 있습니다.',
  );
  await page.getByLabel('새 API 키', { exact: true }).fill(fakeKey);
  await page.getByRole('button', { name: '설정 저장', exact: true }).click();
  await expect(page.getByRole('button', { name: '저장 중', exact: true })).toBeDisabled();
  await expect(
    page.getByText('저장했습니다. 다음 작업·재시도부터 적용됩니다.', { exact: true }),
  ).toHaveCount(0);
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({ path: `${evidence}/saving-desktop.png`, fullPage: true });
  await expect.poll(() => !!releaseSave).toBe(true);
  releaseSave!();
  await expect(page.getByRole('alert')).toHaveText('fixture 설정 저장 실패');
  await expect(model).toHaveValue('fixture-retained-model');
  await expect(page.getByLabel('새 API 키', { exact: true })).toHaveValue('');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({ path: `${evidence}/save-failed-mobile.png`, fullPage: true });
});

test('계정 메뉴·로그아웃 실패/성공·로그인 재입력과 세션 만료 계약을 보존한다', async ({ page }) => {
  let logoutCount = 0,
    loginCount = 0,
    expired = false;
  const nextToken = 'fixture-only-new-session';
  await page.route('**/api/auth/logout', (r) => {
    logoutCount++;
    expect(r.request().headers()['x-csrf-token']).toBe(fakeToken);
    return logoutCount === 1
      ? r.fulfill({ status: 503, json: { detail: 'fixture 로그아웃 실패' } })
      : r.fulfill({ status: 204 });
  });
  await page.route('**/api/auth/login', (r) => {
    loginCount++;
    expect(r.request().headers()).not.toHaveProperty('x-session-token');
    expect(r.request().postDataJSON()).toMatchObject({
      username: 'fixture-reviewer',
      password: 'fixture-only-password',
    });
    return loginCount === 1
      ? r.fulfill({ status: 403, json: { detail: 'fixture 로그인 실패' } })
      : r.fulfill({
          json: {
            enabled: true,
            user: { id: 'fixture-user', username: 'fixture-account-with-a-very-long-name' },
            csrf_token: nextToken,
          },
        });
  });
  await page.route('**/api/settings/llm', (r) =>
    expired
      ? r.fulfill({ status: 401, json: { detail: 'fixture 세션 만료' } })
      : r.fulfill({ json: preferences }),
  );
  await page.goto('/#/settings');
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('fixture 로그아웃 실패');
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: '작업 공간에 로그인', exact: true }),
  ).toBeVisible();
  await page.getByLabel(/^사용자 이름/).fill('fixture-reviewer');
  await page.getByLabel(/^비밀번호/).fill('fixture-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('fixture 로그인 실패');
  await expect(page.getByLabel(/^비밀번호/)).toHaveValue('');
  await expect(page.getByLabel(/^사용자 이름/)).toHaveValue('fixture-reviewer');
  await page.getByLabel(/^비밀번호/).fill('fixture-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'AI 공급자 설정', exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({ path: `${evidence}/account-mobile.png`, fullPage: true });
  expired = true;
  await page.getByRole('button', { name: '설정 새로 불러오기', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: '작업 공간에 로그인', exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('세션이 만료되었습니다. 다시 로그인하세요.');
  await expect(page.getByLabel(/^비밀번호/)).toHaveValue('');
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({ path: `${evidence}/expired-mobile.png`, fullPage: true });
});
