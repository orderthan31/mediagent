import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
for (const width of [390, 920, 1440]) {
  test(`UI02 consumer density ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 960 });
    await page.route('**/api/**', route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith('/session') ? { enabled:false,user:null } : { definitions:[],nodes:[],videos:[],jobs:[],uploads:[],order:[],revision:0,paused:false } }));
    await page.goto('/#/workflows/new');
    await expect(page.getByLabel('워크플로우 이름',{exact:true})).toBeVisible();
    const values=await page.evaluate(() => {
      const read=(selector:string) => { const e=document.querySelector(selector)!; const s=getComputedStyle(e); return {font:parseFloat(s.fontSize),height:e.getBoundingClientRect().height,padding:s.padding,line:s.lineHeight}; };
      return {root:parseFloat(getComputedStyle(document.documentElement).fontSize),theme:read('.workspace-theme'),button:read('.editor-toolbar button'),input:read('[aria-label="워크플로우 이름"]')};
    });
    const beforePath=`docs/evidence/UI02-screen/control-before-${width}.json`;
    await fs.mkdir('docs/evidence/UI02-screen',{recursive:true});
    try { await fs.access(beforePath); } catch { await fs.writeFile(beforePath,JSON.stringify(values,null,2)); }
    const before=JSON.parse(await fs.readFile(beforePath,'utf8'));
    await fs.writeFile(`docs/evidence/UI02-screen/control-after-${width}.json`,JSON.stringify(values,null,2));
    expect(values.root).toBe(before.root);
    expect(values.theme.font).toBe(before.theme.font-2);
    expect(values.button.font).toBe(before.button.font-2);
    expect(values.input.font).toBe(before.input.font-2);
    if(width>390) expect(values.button.height).toBeLessThan(before.button.height);
    else expect(values.button.height).toBeGreaterThanOrEqual(44);
  });
}
