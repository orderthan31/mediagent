import { expect, test } from '@playwright/test';
import fs from 'node:fs/promises';
import contracts from './fixtures/serving.json' with { type: 'json' };

for (const width of [1440, 390]) {
  test(`serving storage and typed-node journey ${width}`, async ({ page }) => {
    const evidence = 'docs/evidence/WF-01';
    await fs.mkdir(evidence, { recursive: true });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    let saved = structuredClone(contracts.serving),
      unavailable = true,
      conflict = true;
    const events: { method: string; path: string; revision?: number; status: number }[] = [];
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.addInitScript(() =>
      document.addEventListener('DOMContentLoaded', () => {
        const p = document.createElement('p');
        p.textContent = '안전 API FIXTURE · 실제 설정·키·Agent·과금 변경 없음';
        p.style.cssText = 'background:#fff3c4;color:#403214;padding:8px;text-align:center';
        document.body.prepend(p);
      }),
    );
    await page.route('**/api/**', async (route) => {
      const request = route.request(),
        path = new URL(request.url()).pathname,
        method = request.method();
      if (path === '/api/auth/session') {
        return route.fulfill({ json: { enabled: false, user: null } });
      }
      if (path === '/api/health') {
        return route.fulfill({ json: { status: 'ok' } });
      }
      if (path === '/api/videos') {
        return route.fulfill({ json: { videos: [] } });
      }
      if (path === '/api/jobs') {
        return route.fulfill({ json: { jobs: [] } });
      }
      if (path === '/api/video-uploads') {
        return route.fulfill({ json: { uploads: [] } });
      }
      if(path==='/api/settings/registered-models'){
        return route.fulfill({json:{models:[],providers:{gemini:'Gemini',openai:'OpenAI',xai:'Grok',anthropic:'Claude',openrouter:'OpenRouter'},connection:'unverified'}});
      }
      if (path === '/api/settings/node-catalog') {
        return route.fulfill({ json: contracts.catalog });
      }
      if (path === '/api/settings/serving') {
        if (method === 'GET') {
          events.push({ method, path, status: unavailable ? 503 : 200 });
          return route.fulfill(
            unavailable
              ? { status: 503, json: { detail: 'fixture 서버 조회 실패' } }
              : { json: saved },
          );
        }
        const body = request.postDataJSON();
        if (conflict) {
          saved.revision++;
          conflict = false;
        }
        const status = body.revision === saved.revision ? 200 : 409;
        events.push({ method, path, revision: body.revision, status });
        if (status === 409) {
          return route.fulfill({
            status,
            json: {
              detail: '설정이 변경되었습니다. 새로 불러온 뒤 Agent 설정을 다시 선택하세요.',
            },
          });
        }
        saved = {
          ...saved,
          ...body,
          revision: saved.revision + 1,
          workers: Object.fromEntries(
            Object.entries(body.workers).map(([role, w]) => [
              role,
              {
                ...saved.workers[role as 'transcription' | 'translation'],
                ...(w as object),
                credential_provider: (w as { provider: string }).provider,
                fallback_credential_provider: (w as { fallback_provider: string })
                  .fallback_provider,
              },
            ]),
          ) as typeof saved.workers,
        };
        return route.fulfill({ json: saved });
      }
      if (path === '/api/settings/node-validation') {
        const body = request.postDataJSON();
        const node = contracts.catalog.nodes.find((n) => n.id === body.node);
        const valid =
          node &&
          Object.entries(node.inputs)
            .filter(([key]) => !(node.optional_inputs as string[]).includes(key))
            .every(([key, type]) => body.inputs[key] === type);
        events.push({ method, path, status: valid ? 200 : 422 });
        return route.fulfill(
          valid
            ? { json: { valid: true, notice: '유형·옵션만 확인. 실제 실행 성공 아님.' } }
            : { status: 422, json: { detail: '필수 입력 유형이 맞지 않습니다.' } },
        );
      }
      return route.fulfill({ status: 404, json: { detail: '안전 fixture 미지원 경로' } });
    });
    await page.goto('/#/serving');
    await page.getByText('기존 공유 역할 설정 · 이전 티켓 호환',{exact:true}).click();
    await expect(page.locator('.serving-heading').first()).toHaveCSS('position', 'static', {
      timeout: 1500,
    });
    await expect(page.getByRole('alert')).toContainText('fixture 서버 조회 실패');
    await expect(page.getByRole('button', { name: '서빙 설정 저장', exact: true })).toHaveCount(0);
    unavailable = false;
    await page.getByRole('button', { name: '서빙 설정 새로 불러오기' }).click();
    const provider = page.getByLabel('서빙 전사 공급자', { exact: true }),
      model = page.getByLabel('서빙 전사 모델', { exact: true });
    await expect(provider).toHaveValue('gemini');
    await provider.selectOption('openai');
    await expect(model).toHaveValue('');
    await expect(provider.locator('option[value="anthropic"]')).toHaveCount(0);
    await model.selectOption('whisper-1');
    await page.getByRole('button', { name: '서빙 설정 저장', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('설정이 변경');
    await expect(model).toHaveValue('whisper-1');
    await page.getByRole('button', { name: '서빙 설정 저장', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('설정이 변경');
    await page.getByRole('button', { name: '서빙 설정 새로 불러오기' }).click();
    await expect(provider).toHaveValue('gemini');
    await provider.selectOption('openai');
    await model.selectOption('whisper-1');
    await page.getByRole('button', { name: '서빙 설정 저장', exact: true }).click();
    await expect(
      page.getByRole('status').filter({ hasText: '서빙 설정을 저장했습니다' }),
    ).toBeVisible();
    await expect(page.getByText('마지막 조회한 OpenAI 기본 키:', { exact: false })).toBeVisible();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: `${evidence}/serving-${width}.png` });
    await page.getByRole('button', { name: '서빙 설정 새로 불러오기' }).click();
    await expect(model).toHaveValue('whisper-1');
    const nodeInput = page.getByLabel('노드 입력 video', { exact: true });
    await nodeInput.selectOption('audio');
    await page.getByRole('button', { name: '서버에서 입출력 유형 검증' }).click();
    await expect(page.getByRole('status').filter({ hasText: '유형 검증 실패' })).toBeVisible();
    await nodeInput.selectOption('video');
    await page.getByRole('button', { name: '서버에서 입출력 유형 검증' }).click();
    await expect(page.getByRole('status').filter({ hasText: '유형 검증 통과' })).toBeVisible();
    await page.screenshot({ path: `${evidence}/node-validation-${width}.png` });
    const puts = events.filter((e) => e.method === 'PUT');
    expect(puts.map((e) => [e.revision, e.status])).toEqual([
      [0, 409],
      [0, 409],
      [1, 200],
    ]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    expect(errors).toEqual([]);
    await fs.writeFile(
      `${evidence}/events-${width}.json`,
      JSON.stringify({ fixture: true, events, errors }, null, 2),
    );
  });
}
