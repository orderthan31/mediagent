import { expect, test } from '@playwright/test';

const providers = {
  openai_compatible: 'OpenAI-compatible',
  openai: 'OpenAI',
  gemini: 'Gemini',
  anthropic: 'Anthropic',
};

test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/session') {
      return route.fulfill({
        json: {
          enabled: true,
          user: { id: 'a'.repeat(32), username: 'isolated-reviewer', role: 'admin' },
          csrf_token: 'isolated-contract-not-a-real-session',
        },
      });
    }
    if (path === '/api/settings/serving-connections') {
      return route.fulfill({ json: { connections: [], providers } });
    }
    if (path === '/api/capabilities') {
      return route.fulfill({ json: { execution_enabled: false } });
    }
    return route.fulfill({ status: 404, json: { detail: 'Unconfigured isolated contract' } });
  });
});

test('Gemini 선택은 필수 주소와 네이티브 연결 방식을 함께 채운다', async ({ page }) => {
  await page.goto('/#/serving/connections/new');
  await page.getByRole('combobox', { name: '공급자', exact: true }).selectOption('gemini');
  await page.getByLabel('이름', { exact: true }).fill('격리 Gemini 등록');
  await expect
    .soft(page.getByLabel('API 기본 주소', { exact: true }))
    .toHaveValue('https://generativelanguage.googleapis.com/v1beta');
  await expect
    .soft(page.getByRole('combobox', { name: 'API 프로토콜', exact: true }))
    .toHaveValue('gemini');
  expect(
    await page
      .locator('form.connection-form')
      .evaluate((form: HTMLFormElement) => form.checkValidity()),
  ).toBe(true);
});

for (const [provider, endpoint, protocol] of [
  ['openai', 'https://api.openai.com/v1', 'openai'],
  ['anthropic', 'https://api.anthropic.com', 'anthropic'],
] as const) {
  test(`${provider} 선택도 공식 기본 주소와 연결 방식을 채운다`, async ({ page }) => {
    await page.goto('/#/serving/connections/new');
    await page.getByRole('combobox', { name: '공급자', exact: true }).selectOption(provider);
    await expect(page.getByLabel('API 기본 주소', { exact: true })).toHaveValue(endpoint);
    await expect(page.getByRole('combobox', { name: 'API 프로토콜', exact: true })).toHaveValue(
      protocol,
    );
    await page
      .getByRole('combobox', { name: '공급자', exact: true })
      .selectOption('openai_compatible');
    await expect(page.getByLabel('API 기본 주소', { exact: true })).toHaveValue('');
    await page.getByLabel('API 기본 주소', { exact: true }).fill('http://127.0.0.1:9000/custom/v1');
    await expect(page.getByLabel('API 기본 주소', { exact: true })).toHaveValue(
      'http://127.0.0.1:9000/custom/v1',
    );
  });
}

test('기존 Gemini 사용자 주소·방식·개정을 자동 변경하지 않고 이름만 수정한다', async ({ page }) => {
  const id = 'b'.repeat(32);
  let current = {
    id,
    name: '기존 사용자 연결',
    provider: 'gemini',
    protocol: 'openai_compatible',
    endpoint: 'https://custom.invalid/private/v1',
    revision: 6,
    credential: 'reference_set',
  };
  const writes: object[] = [];
  await page.route('**/api/settings/serving-connections', (route) =>
    route.fulfill({ json: { connections: [current], providers } }),
  );
  await page.route('**/api/settings/serving-connections/' + id, async (route) => {
    const body = route.request().postDataJSON();
    writes.push(body);
    expect(body).toMatchObject({
      revision: 6,
      provider: 'gemini',
      protocol: 'openai_compatible',
      endpoint: 'https://custom.invalid/private/v1',
    });
    expect(body).not.toHaveProperty('secret');
    current = { ...current, ...body, revision: 7 };
    return route.fulfill({ json: current });
  });
  await page.goto('/#/serving/connections/' + id + '/edit');
  await expect(page.getByLabel('API 기본 주소', { exact: true })).toHaveValue(current.endpoint);
  await expect(page.getByRole('combobox', { name: 'API 프로토콜', exact: true })).toHaveValue(
    'openai_compatible',
  );
  await expect(page.getByLabel('API 키', { exact: true })).toHaveValue('');
  expect(writes).toEqual([]);
  await page.getByLabel('이름', { exact: true }).fill('이름만 수정');
  await page.getByRole('button', { name: '저장', exact: true }).click();
  await expect(page.getByRole('button', { name: '수정', exact: true })).toBeVisible();
  expect(writes).toHaveLength(1);
  expect(current.credential).toBe('reference_set');
});

test('새로 입력한 키를 다른 공급자로 자동 이동시키지 않는다', async ({ page }) => {
  await page.goto('/#/serving/connections/new');
  await page.getByRole('combobox', { name: '공급자', exact: true }).selectOption('gemini');
  await page.getByLabel('API 키', { exact: true }).fill('isolated-not-real-pending-key');
  await page.getByRole('combobox', { name: '공급자', exact: true }).selectOption('anthropic');
  await expect(page.getByLabel('API 키', { exact: true })).toHaveValue('');
});
