import { test, expect } from '@playwright/test';
const providers = {
  openai: 'OpenAI',
  gemini: 'Google Gemini',
  anthropic: 'Anthropic Claude',
  xai: 'Grok (xAI)',
  openai_compatible: 'Custom OpenAI-compatible',
};
const ids = Object.keys(providers)
  .slice(0, 4)
  .map((_, i) => String(i + 1).repeat(32));
const profile = {
  model_types: ['text'],
  input_modalities: ['text'],
  output_modalities: ['text'],
  capabilities: ['text_generation'],
};
const connections = ids.map((id, i) => ({
  id,
  name: Object.values(providers)[i],
  provider: Object.keys(providers)[i],
  current_revision: 2,
  revision: 2,
  active: true,
  address_mode: 'official',
  credential: 'reference_set',
  endpoint: '',
  protocol: i === 1 ? 'gemini' : i === 2 ? 'anthropic' : 'openai',
}));

test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/session') {
      return route.fulfill({
        json: {
          enabled: true,
          user: { id: 'a'.repeat(32), username: 'isolated-contract-fixture', role: 'admin' },
          csrf_token: 'synthetic-fixture-not-operating',
        },
      });
    }
    if (path === '/api/capabilities') {
      return route.fulfill({ json: { execution_enabled: false } });
    }
    if (path === '/api/settings/serving-connections') {
      return route.fulfill({ json: { connections, providers } });
    }
    if (path === '/api/settings/registered-models') {
      return route.fulfill({ json: { models: [], providers } });
    }
    return route.fulfill({
      status: 404,
      json: { detail: 'Unconfigured isolated API-contract fixture' },
    });
  });
});

for (const width of [1440, 390]) {
  test(`공급자 전환 중 늦은 목록 응답을 버린다 ${width}px (API contract fixture)`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => {
      const original = window.fetch.bind(window);
      window.fetch = (input, init) =>
        original(
          input,
          String(input).includes('/model-catalog') ? { ...init, signal: undefined } : init,
        );
    });
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    let started = false;
    await page.route('**/api/settings/serving-connections/*/model-catalog', async (route) => {
      const first = route.request().url().includes(ids[0]);
      if (first) {
        started = true;
        await held;
      }
      return route.fulfill({
        json: {
          connection_id: first ? ids[0] : ids[1],
          connection_revision: 2,
          complete: true,
          inference_verified: false,
          models: [
            {
              id: first ? 'old-provider-model' : 'gemini-3.8-flash',
              label: first ? 'old-provider-model' : 'gemini-3.8-flash',
              profile,
              runtime_uses: ['translation'],
              evidence: [],
              registration_token: first ? 'old-token' : 'new-token',
              reason: 'isolated contract',
            },
          ],
        },
      });
    });
    try {
      await page.goto('/#/serving/new');
      await page.getByRole('combobox', { name: '공급자 연결', exact: true }).selectOption(ids[0]);
      await page.getByRole('button', { name: '공식 모델 목록 조회', exact: true }).click();
      await expect.poll(() => started).toBe(true);
      await page.getByRole('combobox', { name: '공급자 연결', exact: true }).selectOption(ids[1]);
      await page.getByRole('button', { name: '공식 모델 목록 조회', exact: true }).click();
      await page
        .getByRole('combobox', { name: '공식 모델', exact: true })
        .selectOption('gemini-3.8-flash');
      release();
      await page.waitForTimeout(150);
      await expect(page.getByRole('combobox', { name: '공식 모델', exact: true })).toHaveValue(
        'gemini-3.8-flash',
      );
      await expect(
        page.getByRole('combobox', { name: '공식 모델', exact: true }).locator('option'),
      ).not.toContainText(['old-provider-model']);
      await expect(page.getByRole('alert')).toHaveCount(0);
    } finally {
      release();
    }
  });
  test(`4개 공식 공급자는 주소·protocol 입력 없이 등록한다 ${width}px (API contract fixture)`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto('/#/serving/connections/new');
    for (const provider of ['openai', 'gemini', 'anthropic', 'xai']) {
      await page.getByRole('combobox', { name: '공급자', exact: true }).selectOption(provider);
      await expect(page.getByLabel('API 기본 주소', { exact: true })).toHaveCount(0);
      await expect(page.getByRole('combobox', { name: 'API 프로토콜', exact: true })).toHaveCount(
        0,
      );
    }
    await page.getByLabel('이름', { exact: true }).fill('Isolated Grok');
    const writes: object[] = [];
    await page.route('**/api/settings/serving-connections/*', async (route) => {
      const body = route.request().postDataJSON();
      writes.push(body);
      expect(body.provider).toBe('xai');
      expect(body).not.toHaveProperty('endpoint');
      expect(body).not.toHaveProperty('protocol');
      return route.fulfill({
        json: {
          ...connections[3],
          id: route.request().url().split('/').at(-1),
          ...body,
          revision: 1,
        },
      });
    });
    await page.getByRole('button', { name: '저장', exact: true }).click();
    await expect.poll(() => writes.length).toBe(1);
    expect(errors).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });

  test(`공식 조회 모델·용도 선택 뒤 등록 payload를 묶는다 ${width}px (API contract fixture)`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    let queries = 0;
    await page.route('**/api/settings/serving-connections/*/model-catalog', (route) => {
      queries++;
      expect(route.request().method()).toBe('POST');
      expect(route.request().postDataJSON()).toEqual({ connection_revision: 2 });
      return route.fulfill({
        json: {
          connection_id: ids[0],
          connection_revision: 2,
          complete: true,
          inference_verified: false,
          models: [
            {
              id: 'gpt-5.5',
              label: 'gpt-5.5',
              profile,
              runtime_uses: ['translation'],
              evidence: ['official-contract-fixture'],
              registration_token: 'opaque-isolated-catalog-token',
              inference_verified: false,
              reason: '실제 추론 미검증',
            },
            {
              id: 'unknown-id',
              label: 'unknown-id',
              profile: null,
              runtime_uses: [],
              evidence: [],
              reason: '용도 미확인',
            },
          ],
        },
      });
    });
    await page.goto('/#/serving/new');
    await page.getByRole('combobox', { name: '공급자 연결', exact: true }).selectOption(ids[0]);
    await page.getByRole('button', { name: '공식 모델 목록 조회', exact: true }).click();
    await page
      .getByRole('combobox', { name: '모델 용도', exact: true })
      .selectOption('translation');
    await page.getByRole('combobox', { name: '공식 모델', exact: true }).selectOption('gpt-5.5');
    await page.getByLabel('등록 이름', { exact: true }).fill('Isolated discovered GPT');
    const writes: object[] = [];
    await page.route('**/api/settings/registered-models/*', async (route) => {
      const body = route.request().postDataJSON();
      writes.push(body);
      expect(body).toMatchObject({
        model: 'gpt-5.5',
        connection_id: ids[0],
        connection_revision: 2,
        discovery_token: 'opaque-isolated-catalog-token',
        ...profile,
      });
      return route.fulfill({
        json: {
          id: 'f'.repeat(32),
          revision: 1,
          active: true,
          current_revision: 1,
          versions: { '1': { ...body, provider: 'openai' } },
        },
      });
    });
    await page.getByRole('button', { name: '저장', exact: true }).click();
    await expect.poll(() => writes.length).toBe(1);
    expect(queries).toBe(1);
    expect(errors).toEqual([]);
  });
}
