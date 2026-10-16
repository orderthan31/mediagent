import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
for (const width of [390, 920, 1440]) {
  test(`UI02 five destinations and workflow list at CSS width ${width}`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewportSize({ width, height: 960 });
    await page.route('**/api/**', route => {
      const p = new URL(route.request().url()).pathname;
      if (route.request().method() !== 'GET') return route.fulfill({ status: 409, json: { detail: 'Read-only UI checkpoint fixture' } });
      const body = p.endsWith('/session') ? { enabled: false, user: null }
        : p.endsWith('/workflow-definitions') ? { definitions: [{ id: 'a'.repeat(32), name: '인터뷰 자막', revision: 3 }, { id: 'b'.repeat(32), name: '원본 분석', revision: 1 }] }
        : p.endsWith('/videos') ? { videos: [] } : p.endsWith('/video-uploads') ? { uploads: [] }
        : p.endsWith('/queue') ? { jobs: [], order: [], revision: 0, paused: false }
        : p.endsWith('/jobs') ? { jobs: [] } : { nodes: [], models: [], definitions: [], workers: [], jobs: [] };
      return route.fulfill({ json: body });
    });
    await page.goto('/#/');
    const toggle = page.getByRole('button', { name: '메뉴 열기', exact: true });
    if (width === 390) await toggle.click();
    const nav = page.getByRole('navigation', { name: '주 메뉴', exact: true });
    await expect(nav.getByRole('link')).toHaveText(['작업', '원본', '워크플로우', '서빙', '시스템']);
    await expect(page.locator('.ui02-gnb .workspace-connection')).toHaveCount(0);
    await nav.getByRole('link', { name: '워크플로우', exact: true }).click();
    await expect(page.getByRole('heading', { name: '워크플로우', exact: true })).toBeVisible();
    await expect(page.getByText('인터뷰 자막', { exact: true })).toBeVisible();
    await expect(page.locator('.workflow-canvas')).toHaveCount(0);
    await expect(page.getByText('보관된 영상을 찾고, 필요한 작업을 이어가세요.')).toHaveCount(0);
    if (width !== 390) {
      await page.getByRole('button', { name: '메뉴 접기', exact: true }).click();
      await expect(page.locator('.ui02-lnb')).toHaveAttribute('data-collapsed', 'true');
      await page.getByRole('button', { name: '메뉴 펼치기', exact: true }).click();
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    expect(errors).toEqual([]);
    await fs.mkdir('docs/evidence/UI02-screen', { recursive: true });
    const metrics = await page.evaluate(() => {
      const sample = (selector: string) => { const element = document.querySelector(selector); if (!element) return null; const style = getComputedStyle(element); const rect = element.getBoundingClientRect(); return {font:style.fontSize,line:style.lineHeight,height:rect.height,padding:style.padding,gap:style.gap}; };
      return {root:getComputedStyle(document.documentElement).fontSize,theme:sample('.workspace-theme'),title:sample('.ui02-catalog h1'),menu:sample('.ui02-lnb a, .ui02-drawer a'),input:sample('.ui02-search input'),row:sample('.ui02-workflow-row')};
    });
    await fs.writeFile(`docs/evidence/UI02-screen/metrics-before-density-${width}.json`, JSON.stringify(metrics,null,2));
    await page.screenshot({ path: `docs/evidence/UI02-screen/workflows-${width}.png` });
    if (width === 390) {
      await page.getByRole('button', { name: '메뉴 열기', exact: true }).click();
      await page.screenshot({ path: 'docs/evidence/UI02-screen/drawer-390.png' });
    }
  });
}
