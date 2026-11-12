// Explicit offline browser gate. All responses are synthetic; no service/session.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

test('renewal execution popover reads genuine phases, reopens and links to existing detail without mutation', async () => {
  const apiPath = path.resolve('src/api.ts');
  const bundle = await build({
    stdin: {
      resolveDir: process.cwd(),
      loader: 'tsx',
      contents: `
      import React,{useEffect,useState} from 'react';import {createRoot} from 'react-dom/client';
      import {ExecutionPopover} from './src/ExecutionPopover';import {RenewalJobDetail} from './src/RenewalJobDetail';
      const id='11111111111111111111111111111111';
      const definition={id:'unit-definition',catalog_version:2,revision:1,inputs:{},nodes:[{id:'convert',type:'video_conversion_agent',position:{x:0,y:0},options:{}}],edges:[]};
      const job={id,ticket_number:42,revision:7,status:'waiting',display_status:'waiting',parent_id:null,access:{can_manage:true},snapshot:{asset:{asset_id:'unit-asset',original_filename:'literal waiting filename.mp4'},definition,tool_definition:{nodes:[{id:'convert__encode',type:'encode',options:{subtitle_mode:'none'}}]}},runs:[],reviews:[],artifact_manifest:{entry_count:0},agent_workflow:{definition,nodes:[],edges:{}}};
      window.__calls=[];window.__mode='defer';window.__empty={jobs:[],has_more:false,limit:100};
      window.__value={jobs:[{job_id:id,ticket_number:'42',status:'waiting',original_filename:'literal waiting filename.mp4',workflow_name:'literal saved workflow',queued_at:'2026-01-01T00:00:00Z',access:{can_manage:true},deliveries:[{phase:'pending',run_status:'waiting',count:2},{phase:'sending',run_status:'waiting',count:1},{phase:'sent',run_status:'waiting',count:1},{phase:'received',run_status:'running',count:1},{phase:'unknown',run_status:'failed',count:1}]}],has_more:false,limit:100};
      window.__fixtures={['/renewal/jobs/'+id]:job,'/work-entry/catalog':{nodes:[{id:'video_conversion_agent',label:'영상 변환',inputs:{},outputs:{video:'video'},options:{}}]}};
      const bait={job_id:'unadmitted-ledger',status:'QUEUED',original_filename:'NOT AN ACTUAL DELIVERY',metadata:{}};
      function App(){const[route,setRoute]=useState(location.hash);useEffect(()=>{const handler=()=>setRoute(location.hash);window.addEventListener('hashchange',handler);return()=>window.removeEventListener('hashchange',handler);},[]);
        return <div className="video-workspace renewed-workspace ui02-workspace">{route.startsWith('#/jobs/'+id)?<RenewalJobDetail key={route} id={id}/>:<ExecutionPopover jobs={[bait]} onChanged={async()=>{throw new Error('read must not refresh/mutate ledger')}}/>}</div>;}
      createRoot(document.getElementById('root')).render(<App/>);
    `,
    },
    bundle: true,
    write: false,
    platform: 'browser',
    format: 'iife',
    define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
    loader: { '.css': 'empty' },
    plugins: [
      {
        name: 'offline-api',
        setup(plugin) {
          plugin.onResolve({ filter: /api$/ }, (args) =>
            path.resolve(path.dirname(args.importer), args.path + '.ts') === apiPath
              ? { path: 'api', namespace: 'offline' }
              : undefined,
          );
          plugin.onLoad({ filter: /.*/, namespace: 'offline' }, () => ({
            loader: 'js',
            contents: `
        export const base='/api';export const mediaUrl=(path)=>'/api'+path;export class ApiError extends Error{}
        export const request=async(path,init={})=>{const method=init.method||'GET';window.__calls.push({path,method});
          if(method!=='GET')throw new Error('unit forbids mutation');
          if(path==='/queue')return {revision:0,paused:false,order:[],jobs:[],details:[],progression:'ready'};
          if(path==='/renewal/execution-waiting'){
            if(window.__mode==='error')throw new Error('unit waiting query failed');
            if(window.__mode==='defer')return new Promise((resolve,reject)=>{window.__release=resolve;init.signal?.addEventListener('abort',()=>{window.__aborted=true;reject(new DOMException('aborted','AbortError'));});});
            return structuredClone(window.__mode==='empty'?window.__empty:window.__value);
          }
          if(!(path in window.__fixtures))throw new Error('unexpected GET '+path);
          return structuredClone(window.__fixtures[path]);};
        export const uploadRequest=request;export const resumeUpload=()=>{throw new Error('unit forbids upload')};
      `,
          }));
        },
      },
    ],
  });
  const browser = await chromium.launch({
    channel: process.platform === 'win32' ? 'msedge' : undefined,
    headless: true,
  });
  try {
    const context = await browser.newContext({ offline: true });
    await context.route('**/*', (route) => route.abort());
    const page = await context.newPage();
    await page.route('https://waiting-unit.invalid/', (route) =>
      route.fulfill({
        contentType: 'text/html',
        body: '<!doctype html><html lang="ko"><body><div id="root"></div></body></html>',
      }),
    );
    await page.goto('https://waiting-unit.invalid/');
    const builtCss = fs
      .readdirSync('dist/assets')
      .filter((name) => name.endsWith('.css'))
      .map((name) => fs.readFileSync(path.join('dist/assets', name), 'utf8'))
      .join('\n');
    assert.ok(builtCss, 'build current frontend before the offline browser gate');
    const css = [
      'ui02-shell.css',
      'pagination.css',
      'renewal-waiting.css',
      'workflow-canvas.css',
      'job-execution.css',
    ]
      .map((name) => fs.readFileSync(path.join('src', name), 'utf8'))
      .join('\n');
    await page.addStyleTag({ content: builtCss + '\n' + css });
    await page.addScriptTag({ content: bundle.outputFiles[0].text });
    for (const width of [390, 1440]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await page.evaluate(() => {
        location.hash = '#/jobs';
        window.__mode = 'defer';
      });
      await page.getByRole('button', { name: '실행 관리', exact: true }).click();
      const panel = page.getByRole('region', { name: '전달 현황' });
      await expect(panel).toContainText('확인 중');
      assert.equal(await panel.getByText(/0개|대기 중인 전달이 없습니다/).count(), 0);
      await page.evaluate(() => window.__release(window.__empty));
      await expect(panel).toContainText('대기 중인 전달이 없습니다.');
      await page.evaluate(() => {
        window.__mode = 'error';
      });
      await panel.getByRole('button', { name: '다시 확인', exact: true }).click();
      await expect(panel).toContainText('unit waiting query failed');
      await expect(panel).toContainText('마지막 확인');
      assert.equal(await panel.getByText('대기 중인 전달이 없습니다.', { exact: true }).count(), 0);
      await page.evaluate(() => {
        window.__mode = 'success';
      });
      await panel.getByRole('button', { name: '다시 확인', exact: true }).click();
      await expect(panel).toContainText('literal waiting filename.mp4');
      await expect(panel).not.toContainText('NOT AN ACTUAL DELIVERY');
      await expect(panel.locator('[data-phase="pending"]')).toHaveText('전송 대기 · 2건');
      await expect(panel.locator('[data-phase="sending"]')).toHaveText('전송 중 · 1건');
      await expect(panel.locator('[data-phase="sent"]')).toHaveText('수신 확인 대기 · 1건');
      await expect(panel.locator('[data-phase="received"]')).toHaveText('처리 중 · 1건');
      await expect(panel.locator('[data-phase="unknown"]')).toHaveText('전송 결과 확인 필요 · 1건');
      await expect(panel).toContainText('자동으로 다시 보내지 않습니다.');
      assert.equal(await panel.getByRole('checkbox').count(), 0);
      assert.equal(
        await panel.getByRole('button', { name: /취소|일시정지|위로|아래로|재전송/ }).count(),
        0,
      );
      const bounds = await panel.boundingBox();
      assert.ok(
        bounds && bounds.x >= 0 && bounds.x + bounds.width <= width,
        JSON.stringify(bounds),
      );
      const link = panel.getByRole('link', { name: '상세 · 취소 확인' });
      await expect(link).toHaveAttribute('href', '#/jobs/11111111111111111111111111111111');
      await link.click();
      await expect(page.locator('.job-detail-toolbar')).toContainText(
        'literal waiting filename.mp4',
      );
      await expect(page.getByRole('button', { name: '작업 취소', exact: true })).toBeVisible();
      assert.equal(await page.getByRole('button', { name: '작업 시작', exact: true }).count(), 0);
      await page.evaluate(() => {
        location.hash = '#/jobs';
        window.__mode = 'defer';
        window.__aborted = false;
      });
      await page.getByRole('button', { name: '실행 관리', exact: true }).click();
      await expect(page.getByRole('region', { name: '전달 현황' })).toContainText('확인 중');
      await page.getByRole('button', { name: '실행 관리 닫기', exact: true }).click();
      await expect.poll(() => page.evaluate(() => window.__aborted)).toBe(true);
      await page.evaluate(() => {
        window.__mode = 'empty';
      });
      await page.getByRole('button', { name: '실행 관리', exact: true }).click();
      await expect(page.getByRole('region', { name: '전달 현황' })).toContainText(
        '대기 중인 전달이 없습니다.',
      );
      await page.getByRole('button', { name: '실행 관리 닫기', exact: true }).click();
    }
    const calls = await page.evaluate(() => window.__calls);
    assert.ok(calls.length > 0 && calls.every(({ method }) => method === 'GET'));
    assert.ok(calls.some(({ path }) => path === '/renewal/execution-waiting'));
    assert.ok(calls.some(({ path }) => path === '/queue'));
    assert.ok(!calls.some(({ path }) => path.endsWith('/cancel')));
    const workspace = fs.readFileSync('src/VideoWorkspace.tsx', 'utf8');
    assert.ok(!workspace.includes('{!renewalBackend && <ExecutionPopover'));
  } finally {
    await browser.close();
  }
});
