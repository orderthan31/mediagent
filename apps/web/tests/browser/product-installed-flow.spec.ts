import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import { createHash } from 'node:crypto';

const origin = process.env.MIDEAGENT_PRODUCT_UI_ORIGIN!;
const evidence = process.env.MIDEAGENT_PRODUCT_UI_EVIDENCE!;
const password = process.env.MIDEAGENT_PRODUCT_UI_PASSWORD!;

for (const width of [1440, 390]) {
  for (const cancel of [false, true]) {
    test(`installed product UI ${width} ${cancel ? 'cancel' : 'success'}`, async ({ page }) => {
      test.setTimeout(90000);
      expect(origin && evidence && password).toBeTruthy();
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      const errors: string[] = [];
      const writes: { path: string; method: string; body: unknown }[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      page.on('request', (request) => {
        const path = new URL(request.url()).pathname;
        if (
          path.startsWith('/api/') &&
          !path.startsWith('/api/auth/') &&
          !['GET', 'HEAD'].includes(request.method())
        ) {
          writes.push({ path, method: request.method(), body: request.postDataJSON() });
        }
      });
      await page.route('**/*', (route) =>
        new URL(route.request().url()).origin === origin ? route.continue() : route.abort(),
      );
      const meta = await (await page.request.get(origin + '/proof/meta')).json();
      expect(meta.initial_ticket_count).toBe(0);
      const workflow = meta.workflow_ids[cancel ? 'cancel' : 'success'];
      await page.goto(origin + '/#/workflows/' + workflow);
      await page.getByLabel('사용자 이름', { exact: false }).fill('registered-install-admin');
      await page.getByLabel('비밀번호', { exact: false }).fill(password);
      await page.getByRole('button', { name: '로그인', exact: true }).click();
      await expect(page.getByRole('button', { name: '저장', exact: true })).toBeVisible();
      for (const [label, primary, fallback] of [
        ['음성 전사', cancel ? 'cancel_first' : 'asr_first', 'asr_second'],
        ['자막 번역', 'text_first', 'text_second'],
      ]) {
        await page.getByText(label, { exact: true }).first().click();
        const selector = page.getByLabel('호환 등록 모델', { exact: true });
        await expect(selector).toBeEnabled();
        await selector.selectOption(meta.refs[primary].model_id + '@1');
        while (await page.getByRole('button', { name: '폴백 1 삭제', exact: true }).count()) {
          await page.getByRole('button', { name: '폴백 1 삭제', exact: true }).click();
        }
        await page.getByRole('button', { name: '폴백 추가', exact: true }).click();
        await page
          .getByLabel('폴백 1 모델', { exact: true })
          .selectOption(meta.refs[fallback].model_id + '@1');
      }
      const [saved] = await Promise.all([
        page.waitForResponse(
          (response) =>
            response.request().method() === 'PUT' &&
            response.url().includes('/settings/workflow-definitions/' + workflow),
        ),
        page.getByRole('button', { name: '저장', exact: true }).click(),
      ]);
      expect(saved.status()).toBe(200);
      if (width === 1440) {
        await expect(page.getByRole('status').filter({ hasText: /^저장됨$/ })).toBeVisible();
      }
      await page.reload();
      for (const [label, primary, fallback] of [
        ['음성 전사', cancel ? 'cancel_first' : 'asr_first', 'asr_second'],
        ['자막 번역', 'text_first', 'text_second'],
      ]) {
        await page.getByText(label, { exact: true }).first().click();
        const selector = page.getByLabel('호환 등록 모델', { exact: true });
        await expect(selector).toBeEnabled();
        await expect(selector).toHaveValue(meta.refs[primary].model_id + '@1');
        await expect(selector.locator('option:checked')).not.toContainText('미확인');
        await expect(page.getByLabel('폴백 1 모델', { exact: true })).toHaveValue(
          meta.refs[fallback].model_id + '@1',
        );
      }
      await fs.mkdir(evidence, { recursive: true });
      await page.screenshot({ path: `${evidence}/settings-${width}-${cancel}.png` });
      await page.goto(origin + '/#/start');
      await page.getByLabel('원본', { exact: true }).selectOption(meta.asset_id);
      await page.getByLabel('워크플로우', { exact: true }).selectOption(workflow);
      await page.getByLabel('원문 언어', { exact: true }).selectOption('en');
      await page.getByLabel('대상 언어', { exact: true }).selectOption('ko');
      await page.getByRole('button', { name: '실행 전 확인', exact: true }).click();
      await page.getByRole('button', { name: '작업 생성', exact: true }).click();
      await expect(page).toHaveURL(/#\/jobs\/[a-f0-9]{32}/);
      const id = (await page.evaluate(() => location.hash)).split('/').pop()!;
      await page.reload();
      await expect(page.getByText('en → ko', { exact: false })).toBeVisible();
      const path = origin + '/api/renewal/jobs/' + id;
      const before = await (await page.request.get(path)).json();
      expect(before.status).toBe('draft');
      await page.getByRole('button', { name: '실행 계획 확인', exact: true }).click();
      await page.getByRole('button', { name: '계획 동의 저장', exact: true }).click();
      await page.getByRole('button', { name: '실행 요청', exact: true }).click();
      if (cancel) {
        await expect
          .poll(async () => {
            const current = await (await page.request.get(path)).json();
            return current.runs.some(
              (run: { transcription?: { attempts: { status: string }[] } }) =>
                run.transcription?.attempts.some((attempt) => attempt.status === 'started'),
            );
          })
          .toBe(true);
        await page.waitForTimeout(200);
        await page.getByRole('button', { name: '작업 취소', exact: true }).click();
      }
      await expect(
        page.getByRole('status').filter({ hasText: cancel ? /^취소 · 기록 보존$/ : /^완료$/ }),
      ).toBeVisible({ timeout: 25000 });
      const state = await (await page.request.get(path)).json();
      const proof = await (await page.request.get(origin + '/proof/state')).json();
      const stored = proof.jobs.find((job: { id: string }) => job.id === id);
      const runs = proof.runs.filter((run: { job_id: string }) => run.job_id === id);
      const commands = runs
        .filter(
          (run: { request: { transcription?: unknown; translation?: unknown } }) =>
            run.request.transcription || run.request.translation,
        )
        .map((run: { id: string; request: unknown }) => ({
          node_run_id: run.id,
          request: run.request,
        }));
      expect(stored.snapshot_sha256).toBe(before.snapshot_sha256);
      expect(stored.snapshot.options.source_language).toBe('en');
      expect(stored.snapshot.options.target_language).toBe('ko');
      for (const [nodeId, primary, fallback] of [
        ['asr', cancel ? 'cancel_first' : 'asr_first', 'asr_second'],
        ['translate', 'text_first', 'text_second'],
      ]) {
        const node = stored.snapshot.definition.nodes.find(
          (node: { id: string }) => node.id === nodeId,
        );
        expect(node.model_ref).toEqual(meta.refs[primary]);
        expect(node.fallback_refs).toEqual([meta.refs[fallback]]);
      }
      expect(commands.length).toBe(cancel ? 1 : 2);
      const downloads = [];
      if (!cancel) {
        for (const label of ['음성 전사', '자막 번역']) {
          await page.getByText(label, { exact: true }).first().click();
          const region = page.getByRole('region', {
            name: label === '음성 전사' ? '전사 실행 기록' : '번역 실행 기록',
            exact: true,
          });
          await expect(region).toContainText('다음 후보');
          await expect(region).toContainText('최종 채택');
          const [download] = await Promise.all([
            page.waitForEvent('download'),
            page.getByRole('link', { name: '산출물 받기', exact: true }).click(),
          ]);
          const bytes = await fs.readFile((await download.path())!);
          const run = state.runs.find(
            (run: { node_type: string }) =>
              run.node_type === (label === '음성 전사' ? 'transcribe' : 'translate'),
          );
          const sha = createHash('sha256').update(bytes).digest('hex');
          expect(sha).toBe(run.result.outputs.transcript.sha256);
          downloads.push({
            node: run.node_id,
            sha256: sha,
            filename: download.suggestedFilename(),
          });
          await region.scrollIntoViewIfNeeded();
          await page.screenshot({ path: `${evidence}/trace-${width}-${run.node_id}.png` });
        }
        const [manifest] = await Promise.all([
          page.waitForEvent('download'),
          page.getByRole('link', { name: '산출물 manifest 받기', exact: true }).click(),
        ]);
        const body = JSON.parse(await fs.readFile((await manifest.path())!, 'utf8'));
        expect(body.ticket_id).toBe(id);
        expect(
          body.entries.filter((entry: { node_id: string }) =>
            ['asr', 'translate'].includes(entry.node_id),
          ),
        ).toHaveLength(2);
      } else {
        expect(
          proof.quarantine.filter((row: { job_id: string }) => row.job_id === id),
        ).toHaveLength(1);
        expect(runs.some((run: { node_type: string }) => run.node_type === 'translate')).toBe(
          false,
        );
        const manifest = await (await page.request.get(path + '/manifest')).json();
        expect(
          manifest.entries.some((entry: { node_id: string }) =>
            ['asr', 'translate'].includes(entry.node_id),
          ),
        ).toBe(false);
        await page.getByText('음성 전사', { exact: true }).first().click();
        await page.screenshot({ path: `${evidence}/cancel-${width}.png` });
      }
      expect(writes.some((write) => write.path === '/api/work-entry/create')).toBe(true);
      for (const action of ['confirm', 'admit', 'run']) {
        expect(writes.some((write) => write.path.endsWith('/' + id + '/' + action))).toBe(true);
      }
      expect(errors).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await fs.writeFile(
        `${evidence}/journey-${width}-${cancel}.json`,
        JSON.stringify(
          {
            id,
            width,
            cancel,
            writes,
            commands,
            downloads,
            snapshot: stored.snapshot,
            errors,
            actualHttpAudit: 'compared with controlled peer journal after graceful stop',
          },
          null,
          2,
        ),
      );
    });
  }
}
