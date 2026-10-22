import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

const origin = process.env.MIDEAGENT_TRANSLATION_TEST_URL;
const evidence = process.env.MIDEAGENT_TRANSLATION_EVIDENCE;
const password = process.env.MIDEAGENT_TRANSLATION_TEST_PASSWORD;

test('실제 격리 HTTP에서 번역 모델·언어·선택 폴백을 티켓 실행 결과로 연결한다', async ({
  page,
}) => {
  test.setTimeout(120000);
  test.skip(!origin || !evidence || !password, 'Explicit disposable fixture required');
  expect(new URL(origin!).hostname).toBe('127.0.0.1');
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/*', (route) =>
    new URL(route.request().url()).origin === origin ? route.continue() : route.abort(),
  );
  const meta = await (await page.request.get(origin + '/fixture-state')).json();
  await page.goto(origin + '/#/start');
  await page.getByLabel('사용자 이름', { exact: false }).fill('translation-fixture-admin');
  await page.getByLabel('비밀번호', { exact: false }).fill(password!);
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.goto(origin + '/#/workflows/' + meta.workflow_id);
  await page.getByText('자막 번역', { exact: true }).first().click();
  await page
    .getByLabel('호환 등록 모델', { exact: true })
    .selectOption(`${meta.refs[0].model_id}@1`);
  await expect(page.getByRole('heading', { name: '번역 폴백', exact: true })).toBeVisible({
    timeout: 5000,
  });
  while (await page.getByRole('button', { name: '폴백 1 삭제', exact: true }).count()) {
    await page.getByRole('button', { name: '폴백 1 삭제', exact: true }).click();
  }
  await page.getByRole('button', { name: '폴백 추가', exact: true }).click();
  await page.getByLabel('폴백 1 모델', { exact: true }).selectOption(`${meta.refs[1].model_id}@1`);
  await page.getByRole('button', { name: '폴백 추가', exact: true }).click();
  await page.getByLabel('폴백 2 모델', { exact: true }).selectOption(`${meta.refs[2].model_id}@1`);
  await page.getByRole('button', { name: '폴백 2 삭제', exact: true }).click();
  await expect(page.getByLabel('폴백 2 모델', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '폴백 추가', exact: true }).click();
  await page.getByLabel('폴백 2 모델', { exact: true }).selectOption(`${meta.refs[2].model_id}@1`);
  await page.getByRole('button', { name: '폴백 2 위로', exact: true }).click();
  await expect(page.getByLabel('폴백 1 모델', { exact: true })).toHaveValue(
    `${meta.refs[2].model_id}@1`,
  );
  await page.getByRole('button', { name: '폴백 1 아래로', exact: true }).click();
  await page.getByRole('button', { name: '저장', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: /^저장됨$/ })).toBeVisible();
  await page.reload();
  await page.getByText('자막 번역', { exact: true }).first().click();
  await expect(page.getByLabel('폴백 1 모델', { exact: true })).toHaveValue(
    `${meta.refs[1].model_id}@1`,
  );
  await expect(page.getByLabel('폴백 2 모델', { exact: true })).toHaveValue(
    `${meta.refs[2].model_id}@1`,
  );
  await fs.mkdir(evidence!, { recursive: true });
  await page.screenshot({ path: evidence + '/translation-fallback-desktop.png' });
  await page.goto(origin + '/#/start');
  await page.getByLabel('원본', { exact: true }).selectOption(meta.asset_id);
  await page.getByLabel('워크플로우', { exact: true }).selectOption(meta.workflow_id);
  await page.getByLabel('원문 언어', { exact: true }).selectOption('en');
  await page.getByLabel('대상 언어', { exact: true }).selectOption('ko');
  await page
    .getByLabel('번역할 자막 JSON', { exact: true })
    .fill(JSON.stringify([{ start: 0, end: 0.5, text: 'Synthetic input' }]));
  await page.getByRole('button', { name: '실행 전 확인', exact: true }).click();
  await page.getByRole('button', { name: '작업 생성', exact: true }).click();
  await expect(page).toHaveURL(/#\/jobs\/[a-f0-9]{32}/);
  const jobId = (await page.evaluate(() => location.hash)).split('/').pop()!;
  await page.reload();
  await expect(page.getByText('en → ko', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: '실행 계획 확인', exact: true }).click();
  await page.getByRole('button', { name: '계획 동의 저장', exact: true }).click();
  await page.getByRole('button', { name: '실행 요청', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: /^완료$/ })).toBeVisible();
  await page.getByText('자막 번역', { exact: true }).first().click();
  await expect(page.getByText('최종 채택: success', { exact: false })).toBeVisible();
  const state = await (await page.request.get(origin + '/api/renewal/jobs/' + jobId)).json();
  expect(state.status).toBe('completed');
  expect(
    state.runs[0].result.translation.attempts.map((a: { status: string }) => a.status),
  ).toEqual(['failed', 'failed', 'completed']);
  const artifact = await page.request.get(
    origin + `/api/renewal/jobs/${jobId}/artifacts/${state.runs[0].id}/transcript`,
  );
  expect(await artifact.json()).toEqual([{ start: 0, end: 0.5, text: '통제된 번역' }]);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('region', { name: '번역 실행 기록', exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: evidence + '/translation-result-mobile.png' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  await fs.writeFile(
    evidence + '/translation-browser-result.json',
    JSON.stringify(
      {
        jobId,
        status: state.status,
        snapshot: state.snapshot,
        translation: state.runs[0].result.translation,
        errors,
      },
      null,
      2,
    ),
  );
});

test('실행 중 화면 취소는 다음 모델을 호출하지 않고 원 시도 기록을 보존한다', async ({ page }) => {
  test.setTimeout(60000);
  test.skip(!origin || !evidence || !password, 'Explicit disposable fixture required');
  const meta = await (await page.request.get(origin + '/fixture-state')).json();
  await page.goto(origin + '/#/start');
  await page.getByLabel('사용자 이름', { exact: false }).fill('translation-fixture-admin');
  await page.getByLabel('비밀번호', { exact: false }).fill(password!);
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect
    .poll(
      async () => (await (await page.request.get(origin + '/api/auth/session')).json()).user?.role,
    )
    .toBe('admin');
  const session = await (await page.request.get(origin + '/api/auth/session')).json();
  const graph = await (
    await page.request.get(origin + '/api/settings/workflow-definitions/' + meta.workflow_id)
  ).json();
  const { catalog_version, revision, name, inputs, nodes, edges } = graph;
  nodes[0].model_ref = meta.refs[3];
  nodes[0].fallback_refs = [meta.refs[2]];
  const changed = await page.request.put(
    origin + '/api/settings/workflow-definitions/' + meta.workflow_id,
    {
      headers: { Origin: origin!, 'X-CSRF-Token': session.csrf_token },
      data: { catalog_version, revision, name, inputs, nodes, edges },
    },
  );
  expect(changed.ok()).toBe(true);
  await page.reload();
  await page.getByLabel('원본', { exact: true }).selectOption(meta.asset_id);
  await page.getByLabel('워크플로우', { exact: true }).selectOption(meta.workflow_id);
  await page
    .getByLabel('번역할 자막 JSON', { exact: true })
    .fill(JSON.stringify([{ start: 0, end: 0.5, text: 'Synthetic cancellation' }]));
  await page.getByRole('button', { name: '실행 전 확인', exact: true }).click();
  await page.getByRole('button', { name: '작업 생성', exact: true }).click();
  await expect(page).toHaveURL(/#\/jobs\/[a-f0-9]{32}/);
  const id = (await page.evaluate(() => location.hash)).split('/').pop()!;
  await page.getByRole('button', { name: '실행 계획 확인', exact: true }).click();
  await page.getByRole('button', { name: '계획 동의 저장', exact: true }).click();
  await page.getByRole('button', { name: '실행 요청', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: /^처리 중$/ })).toBeVisible({
    timeout: 8000,
  });
  await expect(page.getByRole('button', { name: '작업 취소', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '작업 취소', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '취소 접수' })).toBeVisible();
  const released = await page.request.post(origin + '/fixture-release', {
    data: {},
    headers: { Origin: origin!, 'X-CSRF-Token': session.csrf_token },
  });
  expect(released.ok()).toBe(true);
  await expect(page.getByRole('status').filter({ hasText: /^취소 · 기록 보존$/ })).toBeVisible({
    timeout: 10000,
  });
  const done = await (await page.request.get(origin + '/api/renewal/jobs/' + id)).json();
  expect(done.status).toBe('cancelled');
  expect(done.runs[0].translation.attempts).toHaveLength(1);
  expect(done.runs[0].translation.selected).toBeNull();
  expect(done.runs[0].result).toBeNull();
  await page.getByText('자막 번역', { exact: true }).first().click();
  await expect(page.getByText('최종 채택: 없음', { exact: true })).toBeVisible();
  await page.screenshot({ path: evidence + '/translation-cancel-desktop.png' });
  await fs.writeFile(
    evidence + '/translation-cancellation-browser.json',
    JSON.stringify(
      { jobId: id, status: done.status, translation: done.runs[0].translation },
      null,
      2,
    ),
  );
});
