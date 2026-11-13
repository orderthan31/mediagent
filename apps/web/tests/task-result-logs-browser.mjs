// Offline synthetic API projections only; no production/session access.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

const fixture = {
  run_id: 'run-a',
  node_id: 'speech',
  state: 'running',
  display_state: 'running',
  received_responses: 31,
  shown_calls: 33,
  total_calls: 33,
  has_more: false,
  progress: {
    planned_segments: 96,
    completed_segments: 31,
    failed_segments: 1,
    active_segments: [33],
    unresolved_segments: 0,
    observed_segments: 33,
    total_calls: 33,
    finished_segments: 32,
  },
  entries: [
    { at: '2026-01-01T00:00:00Z', level: 'info', message: '태스크 처리를 시작했습니다.' },
    ...Array.from({ length: 33 }, (_, i) => ({
      at: `2026-01-01T00:00:${String(i + 1).padStart(2, '0')}Z`,
      level: 'info',
      message: `구간 ${i + 1} 모델 요청을 기록했습니다.`,
    })),
    { at: null, level: 'error', message: '구간 1: 모델 응답 형식이 맞지 않습니다.' },
    ...Array.from({ length: 31 }, (_, i) => ({
      at: null,
      level: 'info',
      message: `구간 ${i + 2} 모델 응답을 확인했습니다.`,
    })),
  ],
  console: { available: false, truncated: false, lines: [] },
};

test('API events survive empty console, with honest counts, issues, polling and run isolation', async () => {
  const bundle = await build({
    stdin: {
      resolveDir: process.cwd(),
      loader: 'tsx',
      contents: `
      import React,{useState} from 'react';import{createRoot}from'react-dom/client';
      import{TaskResultTabs}from'./src/TaskResultTabs';
      window.__fixture=${JSON.stringify(fixture)};window.__mode='success';window.__calls=[];window.__deferred=[];
      function App(){const[run,setRun]=useState('run-a');window.__select=setRun;
      return <TaskResultTabs jobId="job" runId={run} initialState="running" initialTab="logs"><p>output</p></TaskResultTabs>}
      createRoot(document.getElementById('root')).render(<App/>);`,
    },
    bundle: true,
    write: false,
    platform: 'browser',
    format: 'iife',
    loader: { '.css': 'empty' },
    plugins: [
      {
        name: 'offline-api',
        setup(plugin) {
          plugin.onResolve({ filter: /^\.\/api$/ }, () => ({ path: 'api', namespace: 'offline' }));
          plugin.onLoad({ filter: /.*/, namespace: 'offline' }, () => ({
            loader: 'js',
            contents: `
        export async function request(path,init){window.__calls.push({path,signal:init.signal});
          if(window.__mode==='error')throw new Error('synthetic refresh failure');
          if(window.__mode==='defer')return new Promise(resolve=>window.__deferred.push(resolve));
          if(window.__mode==='slow'){const value=structuredClone(window.__fixture);return new Promise(resolve=>setTimeout(()=>resolve(value),5000));}
          return structuredClone(window.__fixture);}`,
          }));
        },
      },
    ],
  });
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      offline: true,
      viewport: { width: 390, height: 844 },
    });
    await context.route('**/*', (route) => route.abort());
    const page = await context.newPage();
    await page.setContent(
      '<!doctype html><html lang="ko"><body><div id="root"></div></body></html>',
    );
    await page.clock.install();
    await page.addStyleTag({ content: fs.readFileSync('src/task-result-tabs.css', 'utf8') });
    await page.addScriptTag({ content: bundle.outputFiles[0].text });
    const panel = page.getByRole('tabpanel', { name: '로그' });
    const progress = page.getByRole('progressbar', { name: '청크 처리 진행' });
    await expect(progress).toHaveAttribute('max', '96');
    await expect(progress).toHaveAttribute('value', '32');
    await expect(page.locator('.task-chunk-progress')).toContainText('완료 31');
    await expect(page.locator('.task-chunk-progress')).toContainText('실패 1');
    await expect(page.locator('.task-chunk-progress')).toContainText('현재 33번 청크');
    await expect(panel.getByRole('heading', { name: '에이전트·툴 원본 로그' })).toBeVisible();
    await expect(panel.getByRole('heading', { name: '실행 기록 · 상태·요청 이력' })).toBeVisible();
    await expect(panel.locator('.task-log-list')).toContainText(
      '구간 33 모델 요청을 기록했습니다.',
    );
    await expect(panel).toContainText('응답 확인 31건');
    await expect(panel).toContainText('기록된 요청 33건');
    await expect(panel).toContainText(
      '전체 예정 구간 수나 현재 실행 중인 구간 수를 뜻하지 않습니다.',
    );
    await expect(panel.locator('.task-log-issues')).toContainText(
      '구간 1: 모델 응답 형식이 맞지 않습니다.',
    );
    await expect(page.getByRole('status')).toHaveText('처리 중');
    await expect(panel.locator('.task-log-latest')).toContainText('구간 33');
    await expect(panel.locator('.task-log-list li')).toHaveCount(fixture.entries.length);
    await expect(panel.locator('.task-log-list li[data-level="error"]')).toContainText(
      '시각 미기록',
    );
    await expect(panel).not.toContainText('1970');
    await expect(panel).not.toContainText('Invalid Date');
    await expect(panel).toContainText('수집된 에이전트·툴 원본 로그가 없습니다.');
    await expect(panel).not.toContainText('보존된 처리 기록이 없습니다.');
    await expect(panel.locator('.task-console-policy')).toHaveCount(0);
    for (const width of [320, 390, 1440]) {
      await page.setViewportSize({ width, height: 844 });
      assert.ok(
        await page
          .getByRole('tab', { name: '로그', exact: true })
          .evaluate((el) => el.getBoundingClientRect().height >= 44),
      );
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    }
    // The backend exposes unresolved_segments as an integer count, not an index list.
    await page.evaluate(() => {
      window.__fixture.state = 'held';
      window.__fixture.display_state = 'held';
      window.__fixture.progress.unresolved_segments = 1;
      window.__fixture.progress.active_segments = [];
    });
    await page.clock.runFor(4000);
    await expect(page.locator('.task-chunk-progress')).toContainText('결과 미확인 1');
    await expect(page.locator('.task-chunk-progress')).not.toContainText('현재 33번 청크');
    await page.evaluate(() => {
      window.__fixture.state = 'running';
      window.__fixture.display_state = 'running';
      window.__fixture.progress.unresolved_segments = 0;
      window.__fixture.progress.active_segments = [33];
    });
    await page.clock.runFor(4000);
    // A recorded zero-work plan is valid, but has no determinate progress bar.
    await page.evaluate(() => {
      window.__beforeZeroPlan = structuredClone(window.__fixture);
      window.__fixture.progress = {
        planned_segments: 0,
        completed_segments: 0,
        failed_segments: 0,
        active_segments: [],
        unresolved_segments: 0,
        observed_segments: 0,
        total_calls: 0,
        finished_segments: 0,
      };
    });
    await page.clock.runFor(4000);
    await expect(page.locator('.task-chunk-progress')).toContainText('처리할 청크가 없습니다.');
    await expect(page.getByRole('progressbar', { name: '청크 처리 진행' })).toHaveCount(0);
    await page.evaluate(() => {
      window.__fixture = window.__beforeZeroPlan;
    });
    await page.clock.runFor(4000);
    // A refresh failure keeps last known records, clearly marked stale.
    await page.evaluate(() => {
      window.__mode = 'error';
    });
    await page.clock.runFor(4000);
    await expect(panel.getByRole('alert')).toContainText('마지막으로 확인한 기록');
    await expect(panel.locator('.task-log-list')).toContainText('구간 33');
    // Truncation and console are independent, and null console times remain absent.
    await page.evaluate(() => {
      window.__mode = 'success';
      window.__fixture.has_more = true;
      window.__fixture.total_calls = 233;
      window.__fixture.entries.push({ at: null, level: 'warning', message: '응답 확인 필요' });
      window.__fixture.console = {
        available: true,
        truncated: true,
        lines: [{ at: null, stream: 'stderr', text: 'native diagnostic ' + 'x'.repeat(500) }],
      };
    });
    await page.clock.runFor(4000);
    await expect(panel).toContainText('표시된 요청 33건');
    await expect(panel).toContainText('기록된 요청 233건');
    await expect(panel).toContainText('이전 요청 기록은 생략되었습니다.');
    await expect(panel.locator('.task-log-issues')).toContainText('응답 확인 필요');
    await expect(panel.locator('.task-console-text')).toContainText('시각 미기록 [stderr]');
    await expect(panel).toContainText('콘솔 로그 표시 상한');
    await page.evaluate(() => {
      window.__fixture.console.content_policy = 'private_diagnostics_v1';
    });
    await page.clock.runFor(4000);
    await expect(panel.locator('.task-console-policy')).toContainText(
      '요청·응답·인증 본문과 자유형 출력은 숨깁니다.',
    );

    await page.setViewportSize({ width: 320, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    // Only one request per scope may remain outstanding, regardless of latency.
    await page.evaluate(() => {
      window.__mode = 'defer';
      window.__select('run-b');
    });
    await expect(panel).toContainText('처리 기록을 불러오는 중');
    await expect(panel).not.toContainText('구간 33');
    assert.ok(await page.evaluate(() => window.__calls[0].signal.aborted));
    await page.clock.runFor(4000);
    assert.equal(await page.evaluate(() => window.__deferred.length), 1);
    // A new run may load while the aborted older run's promise is unresolved.
    await page.evaluate(() => window.__select('run-c'));
    await expect.poll(() => page.evaluate(() => window.__deferred.length)).toBe(2);
    await page.evaluate(() =>
      window.__deferred[1]({
        ...window.__fixture,
        run_id: 'run-c',
        entries: [],
        progress: null,
        received_responses: 0,
        shown_calls: 0,
        total_calls: 0,
        has_more: false,
        console: { available: false, truncated: false, lines: [] },
      }),
    );
    await expect(panel).toContainText('보존된 처리 기록이 없습니다.');
    await page.evaluate(() => window.__deferred[0](window.__fixture));
    await expect(panel).not.toContainText('구간 33');
    // Wrong identity fails closed rather than rendering another task's records.
    await page.evaluate(() => {
      window.__mode = 'success';
    });
    await page.clock.runFor(4000);
    await expect(panel.getByRole('alert')).toContainText('최근 처리 기록을 불러오지 못했습니다.');
    await expect(panel).not.toContainText('구간 33');
    // Consistent 5s latency must not be starved by 4s polling.
    await page.evaluate(() => {
      window.__mode = 'slow';
      window.__fixture = { ...window.__fixture, run_id: 'run-slow' };
      window.__select('run-slow');
    });
    await expect(panel).toContainText('처리 기록을 불러오는 중');
    await page.clock.runFor(13000);
    await expect(panel.locator('.task-log-list')).toContainText('구간 33');
    await expect(panel).not.toContainText('처리 기록을 불러오는 중');
    await page.evaluate(() => window.__select(undefined));
    await expect(panel).not.toContainText('기록된 요청');
  } finally {
    await browser.close();
  }
});
