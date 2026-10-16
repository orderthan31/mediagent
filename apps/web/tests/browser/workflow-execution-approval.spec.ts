import { test, expect as baseExpect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
const expect = baseExpect.configure({ timeout: 30000 });
for (const width of [1440, 390]) {
  test(`server approval expiry, unknown cost and separate continuation ${width}`, async ({ page }) => {
    test.setTimeout(600000);
    page.setDefaultTimeout(30000);
    page.setDefaultNavigationTimeout(30000);
    const E = 'docs/evidence/WF-08';
    await fs.mkdir(E, { recursive: true });
    const root = path.resolve('test-results/wf08-' + randomUUID());
    await fs.mkdir(root, { recursive: true });
    const errors: string[] = [], events: { path: string; method: string; payload: any; response: any; status: number }[] = [];
    let advanceNext = false, costError = false;
    page.on('pageerror', e => errors.push(e.message));
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await page.addInitScript(() => document.addEventListener('DOMContentLoaded', () => {
      const p = document.createElement('p');
      p.textContent = '격리 실제 ASGI·영속 승인 / 합성 CPU 영상·통제 응답 / 실GPU·추론·과금 아님';
      p.style.cssText = 'background:#fff3c4;color:#403214;padding:6px;text-align:center;font-size:12px';
      document.body.prepend(p);
    }));
    await page.route('**/api/**', async route => {
      const request = route.request(), p = new URL(request.url()).pathname;
      if (!p.startsWith('/api/settings/') && !p.startsWith('/api/execution-approvals/') && !p.startsWith('/api/videos') && p !== '/api/jobs') {
        return route.fulfill({ json: p.endsWith('session') ? { enabled: false, user: null } : p.endsWith('video-uploads') ? { uploads: [] } : { jobs: [] } });
      }
      const payload = request.method() === 'GET' ? undefined : request.postDataJSON();
      const advance = advanceNext && p.endsWith('/start') ? 901 : 0;
      if (advance) advanceNext = false;
      const headers = Object.fromEntries(Object.entries(request.headers()).filter(([name]) => name.startsWith('x-execution-')));
      const data = await new Promise<{status:number;body:any;binary?:string;content_type?:string}>((resolve,reject) => {
        const child = spawn('docker', ['run','--rm','-i','--network','none','--read-only','--tmpfs','/tmp:rw,size=256m','-v',path.resolve('../..')+':/src:ro','-v',root+':/fixture:rw','-e','PYTHONDONTWRITEBYTECODE=1','-e','MIN_FREE_SPACE_BYTES=0','-e','AUTH_ENABLED=false','-e','PAID_LLM_ENABLED=false','-e','VIDEO_STORAGE_ROOT=/tmp/runtime','-e','JOB_DATABASE_DIR=/tmp/db','-e','PYTHONPATH=/src/packages/shared:/src/apps/api:/src/workers/media',process.env.WF08_TEST_IMAGE || 'video-subtitle-api:renewal-ad1eaa82','python','/src/apps/web/tests/browser/wf08_bridge.py']);
        let output='', error='';
        child.stdout.on('data', v => output+=v); child.stderr.on('data', v => error+=v);
        child.on('error',reject); child.on('close',code => { if(code) reject(new Error(error)); else { try {resolve(JSON.parse(output));} catch(e) {reject(e);} } });
        child.stdin.end(JSON.stringify({method:request.method(),path:p,payload,headers,advance_clock:advance,cost_error:costError && p.startsWith('/api/execution-approvals/')}));
      });
      events.push({path:p,method:request.method(),payload,response:data.body,status:data.status});
      return data.binary ? route.fulfill({status:data.status,body:Buffer.from(data.binary,'base64'),contentType:data.content_type}) : route.fulfill({status:data.status,json:data.body});
    });
    const prepare = async () => {
      await page.goto('/#/start'); await page.reload();
      await page.getByLabel('입력 영상',{exact:true}).selectOption('b'.repeat(32));
      await page.getByLabel('저장 워크플로우',{exact:true}).selectOption('a'.repeat(32));
      await page.getByRole('button',{name:'계획·비용 확인으로',exact:true}).click();
      await page.getByLabel('계획의 모델 호출 확인',{exact:true}).check();
      await page.getByRole('button',{name:'확인하고 티켓 만들기',exact:true}).click();
      await page.getByRole('button',{name:'실행 계획 불러오기',exact:true}).click();
    };
    await prepare();
    await expect(page.getByRole('heading',{name:'서버 실행 승인',exact:true})).toBeVisible();
    const panel = page.locator('.execution-approval');
    await panel.getByRole('button',{name:'서버 실행 계획 조회',exact:true}).click();
    await expect(panel).toContainText('금액 미산정');
    await expect(panel).toContainText('무료/0원');
    await panel.getByLabel('유료가능·금액미산정 비용 확인',{exact:true}).check();
    await panel.getByRole('button',{name:'서버 실행 승인 저장',exact:true}).click();
    await expect(panel).toContainText('15분');
    await panel.scrollIntoViewIfNeeded();
    await page.screenshot({path:`${E}/paid-unpriced-${width}.png`});
    advanceNext = true;
    await panel.getByRole('button',{name:'확인한 계획 실행 요청',exact:true}).click();
    await expect(page.getByText(/미소비 승인 15분이 만료/).first()).toBeVisible();
    expect(await fs.readFile(path.join(root,'actual-trace.jsonl'),'utf8').catch(()=> '')).toBe('');
    await panel.scrollIntoViewIfNeeded(); await page.screenshot({path:`${E}/expired-${width}.png`});
    await panel.getByRole('button',{name:'서버 실행 계획 조회',exact:true}).click();
    await panel.getByLabel('유료가능·금액미산정 비용 확인',{exact:true}).check();
    await panel.getByRole('button',{name:'서버 실행 승인 저장',exact:true}).click();
    await panel.getByRole('button',{name:'확인한 계획 실행 요청',exact:true}).click();
    await expect(page.locator('.ticket-detail .ticket-state')).toContainText('판단 완료');
    await page.getByRole('button',{name:'실행 계획 불러오기',exact:true}).click();
    await page.getByRole('button',{name:'계획 확인 저장',exact:true}).click();
    await panel.getByRole('button',{name:'서버 실행 계획 조회',exact:true}).click();
    await expect(panel).toContainText('외부 provider 호출 없음');
    await panel.getByRole('button',{name:'서버 실행 승인 저장',exact:true}).click();
    await panel.getByRole('button',{name:'확인한 계획 이어 실행 요청',exact:true}).click();
    await expect(page.locator('.ticket-detail .ticket-state')).toContainText('사람 검수 대기');
    const trace = (await fs.readFile(path.join(root,'actual-trace.jsonl'),'utf8')).trim().split('\n').map(l=>JSON.parse(l));
    expect(trace.filter(row=>row.node==='judge')).toHaveLength(1);
    await prepare(); costError=true;
    await panel.getByRole('button',{name:'서버 실행 계획 조회',exact:true}).click();
    await expect(panel).toContainText('비용 분류');
    await expect(panel.getByRole('button',{name:'서버 실행 승인 저장',exact:true})).toBeDisabled();
    await expect(panel.getByRole('button',{name:'확인한 계획 실행 요청',exact:true})).toBeDisabled();
    await panel.scrollIntoViewIfNeeded(); await page.screenshot({path:`${E}/classification-blocked-${width}.png`});
    expect(errors).toEqual([]);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
    await fs.writeFile(`${E}/journey-${width}.json`,JSON.stringify({scope:'Actual isolated ASGI/ledger and controlled adapter; NO live provider/GPU/payment',width,errors,trace,events},null,2));
  });
}
