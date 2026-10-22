import { expect, test } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import fs from 'node:fs/promises';

// This case uses real HTTP + disposable PG, never the operating site or a model API.
const origin = process.env.MIDEAGENT_PROVIDER_TEST_URL;
const evidence = process.env.MIDEAGENT_PROVIDER_EVIDENCE_DIR;

test('격리 설치 API의 Gemini 키 등록·재조회·수정과 사용자 주소·키 연결을 보존한다', async ({
  page,
}) => {
  test.setTimeout(60000);
  test.skip(!origin || !evidence, 'Explicit disposable API and evidence directory required');
  expect(new URL(origin!).hostname).toBe('127.0.0.1');
  const firstKey = 'isolated-not-real-gemini-key-one';
  const nextKey = 'isolated-not-real-gemini-key-two';
  const customKey = 'isolated-not-real-custom-key';
  const username = 'isolated-provider-admin';
  const password = randomUUID();
  const errors: string[] = [];
  const pendingReads: Promise<void>[] = [];
  const responses: { path: string; method: string; status: number }[] = [];
  const outbound: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/*', (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) {
      outbound.push(url.origin);
      return route.abort();
    }
    return route.continue();
  });
  page.on('response', (response) => {
    const path = new URL(response.url()).pathname;
    if (!path.startsWith('/api/settings/serving-connections')) {
      return;
    }
    responses.push({ path, method: response.request().method(), status: response.status() });
    pendingReads.push(
      response.text().then((text) => {
        for (const key of [firstKey, nextKey, customKey]) {
          expect(text).not.toContain(key);
        }
      }),
    );
  });
  const bootstrap = await page.request.post(origin + '/api/auth/bootstrap', {
    data: { username, password },
    headers: { Origin: origin! },
  });
  expect(bootstrap.status()).toBe(201);
  await page.goto(origin + '/#/serving/connections/new');
  await page.getByLabel('사용자 이름', { exact: false }).fill(username);
  await page.getByLabel('비밀번호', { exact: false }).fill(password);
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('combobox', { name: '공급자', exact: true }).selectOption('gemini');
  await page.getByLabel('이름', { exact: true }).fill('격리 Gemini');
  await expect(page.getByLabel('API 기본 주소', { exact: true })).toHaveValue(
    'https://generativelanguage.googleapis.com/v1beta',
  );
  await expect(page.getByRole('combobox', { name: 'API 프로토콜', exact: true })).toHaveValue(
    'gemini',
  );
  await expect(
    page.getByText('등록은 연결·모델 호출 성공을 뜻하지 않습니다.', { exact: true }),
  ).toBeVisible();
  await page.getByLabel('API 키', { exact: true }).fill(firstKey);
  await fs.mkdir(evidence!, { recursive: true });
  await page.screenshot({ path: evidence + '/gemini-input-desktop.png' });
  await page.getByRole('button', { name: '저장', exact: true }).click();
  await expect(page.getByRole('button', { name: '수정', exact: true })).toBeVisible();
  const id = (await page.evaluate(() => location.hash)).match(/connections\/([a-f0-9]{32})/)![1];
  const list = async () =>
    (await page.request.get(origin + '/api/settings/serving-connections')).json();
  let row = (await list()).connections.find((item: { id: string }) => item.id === id);
  expect(row).toMatchObject({
    provider: 'gemini',
    protocol: 'gemini',
    revision: 2,
    credential: 'reference_set',
    connection_verified: false,
  });
  await page.reload();
  await expect(page.getByText('DB 암호화 저장됨', { exact: true })).toBeVisible();
  await expect(page.getByText('미확인', { exact: true })).toBeVisible();
  expect(await page.content()).not.toContain(firstKey);
  await page.screenshot({ path: evidence + '/gemini-saved-desktop.png' });
  await page.getByRole('button', { name: '수정', exact: true }).click();
  await expect(page.getByLabel('API 키', { exact: true })).toHaveValue('');
  await page.getByLabel('이름', { exact: true }).fill('격리 Gemini 수정');
  await page.getByRole('button', { name: '저장', exact: true }).click();
  await expect(page.getByRole('button', { name: '수정', exact: true })).toBeVisible();
  row = (await list()).connections.find((item: { id: string }) => item.id === id);
  expect(row).toMatchObject({
    name: '격리 Gemini 수정',
    revision: 3,
    credential: 'reference_set',
    protocol: 'gemini',
  });
  await page.getByRole('button', { name: '수정', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel('API 키', { exact: true }).fill(nextKey);
  await page.getByRole('button', { name: '저장', exact: true }).click();
  await expect(page.getByRole('button', { name: '수정', exact: true })).toBeVisible();
  row = (await list()).connections.find((item: { id: string }) => item.id === id);
  expect(row).toMatchObject({
    revision: 5,
    credential: 'reference_set',
    connection_verified: false,
  });
  await page.reload();
  await expect(page.getByText('DB 암호화 저장됨', { exact: true })).toBeVisible();
  await page.screenshot({ path: evidence + '/gemini-replaced-mobile.png' });
  expect(await page.content()).not.toContain(nextKey);
  await page.goto(origin + '/#/serving/connections/new');
  await page
    .getByRole('combobox', { name: '공급자', exact: true })
    .selectOption('openai_compatible');
  const customEndpoint = 'http://127.0.0.1:9456/custom/model-api/v1';
  await page.getByLabel('이름', { exact: true }).fill('격리 사용자 지정');
  await page.getByLabel('API 기본 주소', { exact: true }).fill(customEndpoint);
  await page.getByLabel('API 키', { exact: true }).fill(customKey);
  await page.getByRole('button', { name: '저장', exact: true }).click();
  await expect(page.getByRole('button', { name: '수정', exact: true })).toBeVisible();
  const customId = (await page.evaluate(() => location.hash)).match(
    /connections\/([a-f0-9]{32})/,
  )![1];
  await page.getByRole('button', { name: '수정', exact: true }).click();
  await expect(page.getByLabel('API 기본 주소', { exact: true })).toHaveValue(customEndpoint);
  await expect(page.getByRole('combobox', { name: 'API 프로토콜', exact: true })).toHaveValue(
    'openai_compatible',
  );
  await expect(page.getByLabel('API 키', { exact: true })).toHaveValue('');
  await page.getByLabel('이름', { exact: true }).fill('격리 사용자 지정 수정');
  await page.getByRole('button', { name: '저장', exact: true }).click();
  await expect(page.getByRole('button', { name: '수정', exact: true })).toBeVisible();
  const custom = (await list()).connections.find((item: { id: string }) => item.id === customId);
  expect(custom).toMatchObject({
    endpoint: customEndpoint,
    protocol: 'openai_compatible',
    revision: 3,
    credential: 'reference_set',
  });
  await page.screenshot({ path: evidence + '/custom-preserved-mobile.png' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await Promise.all(pendingReads);
  expect(errors).toEqual([]);
  expect(outbound).toEqual([]);
  await fs.writeFile(
    evidence + '/installed-browser-result.json',
    JSON.stringify(
      {
        boundary: 'actual installed API + disposable PG; no model call',
        gemini: { id, revision: row.revision, credential: row.credential, verified: false },
        custom: {
          id: customId,
          endpoint: custom.endpoint,
          revision: custom.revision,
          credential: custom.credential,
        },
        responses,
        pageErrors: errors,
        outboundRequests: outbound,
        viewports: [1440, 390],
      },
      null,
      2,
    ),
  );
});
