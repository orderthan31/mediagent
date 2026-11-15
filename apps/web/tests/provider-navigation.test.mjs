// Full production entry point with offline HTTP fixtures; never save or call a provider.
import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

const bundle = await build({
  entryPoints: ['src/main.tsx'],
  bundle: true,
  write: false,
  outdir: 'offline-app',
  format: 'iife',
  platform: 'browser',
  external: ['/fonts/*'],
  define: {
    'import.meta.env': '{"DEV":false,"VITE_RENEWAL_BACKEND":"1"}',
    'process.env.NODE_ENV': '"production"',
  },
});
const harness = async (run, role = 'admin', width = 1440) => {
  const browser = await chromium.launch({ headless: true });
  const unexpected = [];
  const errors = [];
  try {
    const context = await browser.newContext({ offline: true, viewport: { width, height: 1000 } });
    await context.route('**/*', async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin === 'https://provider-navigation.invalid' && request.method() === 'GET') {
        if (url.pathname === '/') {
          return route.fulfill({
            contentType: 'text/html',
            body: '<div id="root"></div><link rel="stylesheet" href="/main.css"><script src="/main.js"></script>',
          });
        }
        for (const extension of ['js', 'css']) {
          if (url.pathname === '/main.' + extension) {
            return route.fulfill({
              contentType: extension === 'js' ? 'text/javascript' : 'text/css',
              body: bundle.outputFiles.find((file) => file.path.endsWith('.' + extension)).text,
            });
          }
        }
        if (url.pathname.startsWith('/fonts/')) {
          return route.fulfill({ path: 'public' + url.pathname });
        }
        const fixtures = {
          '/api/auth/session': {
            enabled: true,
            user: role ? { id: 'offline-test-only', username: 'offline-test-only', role } : null,
          },
          '/api/capabilities': { features: ['verified_uploads'] },
          '/api/videos': { videos: [] },
          '/api/jobs': { jobs: [] },
          '/api/video-uploads': { uploads: [] },
          '/api/tool-hub/tools': { tools: [] },
          '/api/settings/registered-models': { models: [], providers: {} },
          '/api/settings/serving-connections': {
            connections: [],
            providers: { openai: 'OpenAI', vertex_ai: 'Google Vertex AI' },
          },
        };
        if (url.pathname in fixtures) {
          return route.fulfill({ json: fixtures[url.pathname] });
        }
      }
      unexpected.push(request.method() + ' ' + url.href);
      return route.abort();
    });
    const page = await context.newPage();
    page.setDefaultTimeout(5000);
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('https://provider-navigation.invalid/#/serving/connections');
    await run(page);
    assert.deepEqual(unexpected, [], 'No mutations or unconfigured/external requests');
    assert.deepEqual(errors, [], 'No uncaught application errors');
  } finally {
    await browser.close();
  }
};

for (const width of [1440, 390]) {
  test(`full app provider list → add → Vertex fields at ${width}px without saving`, () =>
    harness(
      async (page) => {
        await expect(page.getByText('등록된 공급자 없음', { exact: true })).toBeVisible();
        const add = page.getByRole('link', { name: '공급자 추가', exact: true });
        await expect(add).toBeVisible();
        await expect(add).toBeInViewport();
        await expect(add).toHaveAttribute('href', '#/serving/connections/new');
        await expect(page.getByRole('link', { name: '모델 추가', exact: true })).toHaveCount(0);
        await expect(page.getByRole('searchbox', { name: '서빙 검색' })).toBeVisible();
        await add.click();
        await expect(page).toHaveURL(/#\/serving\/connections\/new$/);
        await page.getByRole('combobox', { name: '공급자', exact: true }).selectOption('vertex_ai');
        await expect(page.getByLabel('프로젝트 ID', { exact: true })).toBeVisible();
        await page.getByLabel('프로젝트 ID', { exact: true }).fill('offline-project');
        await expect(page.getByLabel('리전', { exact: true })).toHaveValue('global');
        await page.getByLabel('리전', { exact: true }).fill('us-central1');
        await expect(page.getByLabel('서비스 계정 JSON 파일')).toBeVisible();
        await expect(page.getByLabel('서비스 계정 JSON 파일')).toHaveAttribute('type', 'file');
        await expect(page.getByLabel('API 키', { exact: true })).toHaveCount(0);
        await expect(page.getByLabel('API 기본 주소', { exact: true })).toHaveCount(0);
        await expect(add).toHaveCount(0);
        await page.goBack();
        await expect(add).toBeVisible();
      },
      'admin',
      width,
    ));
}

test('serving actions follow the route, not the inserted tools navigation index', () =>
  harness(async (page) => {
    await expect(page.getByText('등록된 공급자 없음', { exact: true })).toBeVisible();
    await page.getByRole('link', { name: '모델', exact: true }).click();
    const add = page.getByRole('link', { name: '모델 추가', exact: true });
    await expect(add).toBeVisible();
    await expect(add).toHaveAttribute('href', '#/serving/new');
    await page
      .getByRole('navigation', { name: '주 메뉴', exact: true })
      .getByRole('link', { name: '툴', exact: true })
      .click();
    await expect(page).toHaveURL(/#\/tools$/);
    await expect(page.getByRole('navigation', { name: '브레드크럼' })).toHaveText('툴');
    await expect(add).toHaveCount(0);
    await expect(page.getByRole('link', { name: '공급자 추가', exact: true })).toHaveCount(0);
    await expect(page.getByRole('searchbox')).toHaveCount(0);
  }));

test('ordinary users cannot open the provider list or create form', () =>
  harness(async (page) => {
    await expect(page.getByRole('alert')).toHaveText('관리자만 이용할 수 있는 화면입니다.');
    await expect(page.getByRole('link', { name: '공급자 추가', exact: true })).toHaveCount(0);
    await page.evaluate(() => {
      location.hash = '/serving/connections/new';
    });
    await expect(page).toHaveURL(/#\/serving\/connections\/new$/);
    await expect(page.getByRole('alert')).toHaveText('관리자만 이용할 수 있는 화면입니다.');
    await expect(page.getByRole('combobox', { name: '공급자', exact: true })).toHaveCount(0);
  }, 'user'));

test('full app keeps provider creation behind the existing authentication gate', () =>
  harness(async (page) => {
    await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: '공급자 추가', exact: true })).toHaveCount(0);
    await expect(page.getByLabel('서비스 계정 JSON 파일')).toHaveCount(0);
  }, null));
