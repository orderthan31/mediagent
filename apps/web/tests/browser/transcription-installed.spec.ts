import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

const origin = process.env.MIDEAGENT_ASR_TEST_URL;
const evidence = process.env.MIDEAGENT_ASR_EVIDENCE;
const password = process.env.MIDEAGENT_ASR_TEST_PASSWORD;

for (const cancel of [false, true]) {
  test(
    cancel
      ? '실제 음성 전사 중 화면 취소는 후속 후보·번역을 시작하지 않는다'
      : '화면 전사 선택·언어·폴백→고정 티켓→실제 음성 요청→번역·다운로드',
    async ({ page }) => {
      test.setTimeout(90000);
      test.skip(!origin || !evidence || !password, 'Explicit disposable fixture required');
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.route('**/*', (route) =>
        new URL(route.request().url()).origin === origin ? route.continue() : route.abort(),
      );
      const meta = await (await page.request.get(origin + '/fixture-state')).json();
      const beforeCalls = meta.calls.length;
      await page.goto(origin + '/#/start');
      await page.getByLabel('사용자 이름', { exact: false }).fill('asr-fixture-admin');
      await page.getByLabel('비밀번호', { exact: false }).fill(password!);
      await page.getByRole('button', { name: '로그인', exact: true }).click();
      await expect
        .poll(
          async () =>
            (await (await page.request.get(origin + '/api/auth/session')).json()).user?.role,
        )
        .toBe('admin');
      await page.goto(origin + '/#/workflows/' + meta.workflow_id);
      await page.getByText('음성 전사', { exact: true }).first().click();
      const primary = page.getByLabel('호환 등록 모델', { exact: true });
      await expect(primary.locator(`option[value="${meta.unsupported_id}@1"]`)).toHaveAttribute(
        'disabled',
        '',
      );
      await primary.selectOption(`${(cancel ? meta.cancel_ref : meta.refs[0]).model_id}@1`);
      await expect(page.getByRole('heading', { name: '전사 폴백', exact: true })).toBeVisible();
      while (await page.getByRole('button', { name: '폴백 1 삭제', exact: true }).count()) {
        await page.getByRole('button', { name: '폴백 1 삭제', exact: true }).click();
      }
      await page.getByRole('button', { name: '폴백 추가', exact: true }).click();
      await page
        .getByLabel('폴백 1 모델', { exact: true })
        .selectOption(`${meta.refs[1].model_id}@1`);
      await page.getByRole('button', { name: '저장', exact: true }).click();
      await expect(page.getByRole('status').filter({ hasText: /^저장됨$/ })).toBeVisible();
      await page.reload();
      await page.getByText('음성 전사', { exact: true }).first().click();
      await expect(page.getByLabel('폴백 1 모델', { exact: true })).toHaveValue(
        `${meta.refs[1].model_id}@1`,
      );
      await fs.mkdir(evidence!, { recursive: true });
      if (!cancel) {
        await page.screenshot({ path: evidence + '/asr-model-selection-desktop.png' });
      }
      await page.goto(origin + '/#/start');
      await page.getByLabel('원본', { exact: true }).selectOption(meta.asset_id);
      await page.getByLabel('워크플로우', { exact: true }).selectOption(meta.workflow_id);
      await page.getByLabel('원문 언어', { exact: true }).selectOption('en');
      await page.getByLabel('대상 언어', { exact: true }).selectOption('ko');
      await expect(page.getByLabel('번역할 자막 JSON', { exact: true })).toHaveCount(0);
      await page.getByRole('button', { name: '실행 전 확인', exact: true }).click();
      await page.getByRole('button', { name: '작업 생성', exact: true }).click();
      await expect(page).toHaveURL(/#\/jobs\/[a-f0-9]{32}/);
      const id = (await page.evaluate(() => location.hash)).split('/').pop()!;
      await page.reload();
      await expect(page.getByText('en → ko', { exact: false })).toBeVisible();
      await page.getByRole('button', { name: '실행 계획 확인', exact: true }).click();
      await page.getByRole('button', { name: '계획 동의 저장', exact: true }).click();
      await page.getByRole('button', { name: '실행 요청', exact: true }).click();
      if (cancel) {
        await expect
          .poll(
            async () => (await (await page.request.get(origin + '/fixture-state')).json()).entered,
          )
          .toBe(true);
        await expect(page.getByRole('status').filter({ hasText: /^처리 중$/ })).toBeVisible();
        await page.getByRole('button', { name: '작업 취소', exact: true }).click();
        await expect(page.getByRole('status').filter({ hasText: '취소 접수' })).toBeVisible();
        const session = await (await page.request.get(origin + '/api/auth/session')).json();
        const released = await page.request.post(origin + '/fixture-release', {
          data: {},
          headers: { Origin: origin!, 'X-CSRF-Token': session.csrf_token },
        });
        expect(released.ok()).toBe(true);
      }
      await expect(
        page.getByRole('status').filter({ hasText: cancel ? /^취소 · 기록 보존$/ : /^완료$/ }),
      ).toBeVisible({ timeout: 15000 });
      const state = await (await page.request.get(origin + '/api/renewal/jobs/' + id)).json();
      const asr = state.runs.find((r: { node_type: string }) => r.node_type === 'transcribe');
      const trace = asr.result?.transcription || asr.transcription;
      const after = await (await page.request.get(origin + '/fixture-state')).json();
      const calls = after.calls.slice(beforeCalls);
      expect(calls.map((c: { stage: string }) => c.stage)).toEqual(
        cancel ? ['transcription'] : ['transcription', 'transcription', 'translation'],
      );
      expect(trace.attempts.map((a: { status: string }) => a.status)).toEqual(
        cancel ? ['cancelled'] : ['failed', 'completed'],
      );
      if (cancel) {
        expect(trace.selected).toBeNull();
        expect(state.runs.some((r: { node_type: string }) => r.node_type === 'translate')).toBe(
          false,
        );
      } else {
        expect(trace.selected.remote_model).toBe('whisper-1');
        const translated = state.runs.find(
          (r: { node_type: string }) => r.node_type === 'translate',
        );
        expect(translated.inputs.transcript).toEqual(asr.result.outputs.transcript);
        const output = await page.request.get(
          origin + `/api/renewal/jobs/${id}/artifacts/${translated.id}/transcript`,
        );
        expect(await output.json()).toEqual([{ start: 0.1, end: 0.4, text: '통제된 번역' }]);
        expect(calls[0].audio_sha256).toBe(asr.inputs.audio.sha256);
        expect(calls[1].audio_sha256).toBe(asr.inputs.audio.sha256);
      }
      await page.getByText('음성 전사', { exact: true }).first().click();
      await expect(
        page.getByRole('heading', { name: '전사 실행 기록', exact: true }),
      ).toBeVisible();
      await page.setViewportSize({ width: 390, height: 844 });
      await page
        .getByRole('region', { name: '전사 실행 기록', exact: true })
        .scrollIntoViewIfNeeded();
      await page.screenshot({ path: evidence + `/asr-${cancel ? 'cancel' : 'result'}-mobile.png` });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      expect(errors).toEqual([]);
      await fs.writeFile(
        evidence + `/asr-${cancel ? 'cancel' : 'result'}-browser.json`,
        JSON.stringify(
          {
            id,
            status: state.status,
            snapshot: state.snapshot,
            transcription: trace,
            calls,
            errors,
          },
          null,
          2,
        ),
      );
    },
  );
}
