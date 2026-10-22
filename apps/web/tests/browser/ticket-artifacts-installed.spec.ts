import { expect, test } from '@playwright/test';
import fs from 'node:fs/promises';
import { createHash } from 'node:crypto';

const origin = process.env.MIDEAGENT_ARTIFACT_ORIGIN;
const password = process.env.MIDEAGENT_ARTIFACT_PASSWORD;
const evidence = process.env.MIDEAGENT_ARTIFACT_BROWSER_EVIDENCE;
for (const width of [1440, 390]) {
  test(`persisted ticket manifest and accepted bytes from actual UI (${width}px)`, async ({
    page,
  }) => {
    test.skip(!origin || !password || !evidence, 'Explicit disposable PG/CAS fixture required');
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.setViewportSize({ width, height: 900 });
    await page.route('**/*', (route) =>
      new URL(route.request().url()).origin === origin ? route.continue() : route.abort(),
    );
    // A normal login against the disposable API, not injected cookies or auth bypass.
    const login = await page.request.post(origin + '/api/auth/login', {
      data: { username: 'ticket-fixture-admin', password },
    });
    expect(login.status()).toBe(200);
    const meta = await (await page.request.get(origin + '/fixture-state')).json();
    for (const [index, id] of meta.jobs.entries()) {
      await page.goto(origin + '/#/jobs/' + id);
      const panel = page.getByRole('region', { name: '티켓별 산출물', exact: true });
      await expect(panel).toBeVisible();
      const state = await (await page.request.get(origin + '/api/renewal/jobs/' + id)).json();
      await expect(panel).toContainText(
        `정상 채택 산출물 ${state.artifact_manifest.entry_count}개`,
      );
      const download = page.waitForEvent('download');
      await panel.getByRole('link', { name: '산출물 manifest 받기', exact: true }).click();
      const manifest = await download;
      const raw = await fs.readFile((await manifest.path())!);
      expect(createHash('sha256').update(raw).digest('hex')).toBe(
        state.artifact_manifest.reference.sha256,
      );
      const document = JSON.parse(raw.toString('utf8'));
      expect(document.ticket_id).toBe(id);
      await page
        .getByText(index === 0 ? '음성 전처리' : '자막 번역', { exact: true })
        .first()
        .click();
      const link = page.getByRole('link', { name: '산출물 받기', exact: true }).first();
      await expect(link).toBeVisible();
      const entry = document.entries.find(
        (item: { node_id: string }) => item.node_id === (index === 0 ? 'prepare' : 'translated'),
      );
      const fileDownload = page.waitForEvent('download');
      await link.click();
      const artifact = await fileDownload;
      const artifactRaw = await fs.readFile((await artifact.path())!);
      expect(createHash('sha256').update(artifactRaw).digest('hex')).toBe(entry.storage.sha256);
      await panel.scrollIntoViewIfNeeded();
      // Capture from the document top: sticky headers can cover scrollIntoView targets.
      await page.evaluate(() => window.scrollTo(0, 0));
      await expect.poll(async () => (await panel.boundingBox())?.y ?? -1).toBeGreaterThan(64);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await fs.mkdir(evidence!, { recursive: true });
      await page.screenshot({ path: `${evidence}/ticket-${index}-${width}.png`, fullPage: true });
    }
    await page.goto(origin + '/#/jobs/' + meta.cancelled);
    await expect(page.getByRole('region', { name: '티켓별 산출물', exact: true })).toContainText(
      '정상 채택 산출물 0개',
    );
    await page.getByText('오디오 추출', { exact: true }).first().click();
    await expect(page.getByRole('link', { name: '산출물 받기', exact: true })).toHaveCount(0);
    expect(errors).toEqual([]);
  });
}
