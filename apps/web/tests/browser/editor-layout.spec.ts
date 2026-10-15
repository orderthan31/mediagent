import { expect, test } from '@playwright/test';
import fs from 'node:fs/promises';

test('default placement remains within server coordinate bounds at the node limit', async ({
  page,
}) => {
  const fixture = JSON.parse(await fs.readFile('tests/browser/fixtures/serving.json', 'utf8'));
  await page.route('**/api/**', (route) => {
    const p = new URL(route.request().url()).pathname;
    return route.fulfill({
      json: p.endsWith('node-catalog')
        ? fixture.catalog
        : p.endsWith('workflow-definitions')
          ? { definitions: [] }
          : p.endsWith('session')
            ? { enabled: false, user: null }
            : p.endsWith('videos')
              ? { videos: [] }
              : p.endsWith('video-uploads')
                ? { uploads: [] }
                : { jobs: [] },
    });
  });
  await page.goto('/#/workflow-editor');
  const add = page.getByRole('button', { name: '영상 분석 추가', exact: true });
  for (let n = 0; n < 100; n++) {
    await add.click();
  }
  expect(Number(await page.getByLabel('노드 Y', { exact: true }).inputValue())).toBeLessThanOrEqual(
    3000,
  );
  expect(Number(await page.getByLabel('노드 X', { exact: true }).inputValue())).toBeLessThanOrEqual(
    4000,
  );
  expect(
    await page.locator('.canvas-node').evaluateAll((nodes) =>
      nodes.every((n) => {
        const s = (n as HTMLElement).style;
        return Number.parseInt(s.left) <= 4000 && Number.parseInt(s.top) <= 3000;
      }),
    ),
  ).toBe(true);
  await expect(add).toBeDisabled();
});
