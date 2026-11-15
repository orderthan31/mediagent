// Offline synthetic public projections; never connects to a job API.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

const agents = [
  {
    id: 'speech',
    type: 'transcription_agent',
    label: '음성 전사',
    state: 'failed',
    reason: '응답 형식 확인 필요',
    selected_tool_id: 'asr',
    tools: [
      {
        node_id: 'asr',
        role: 'transcription',
        label: '음성 인식',
        state: 'running',
        run_id: 'run-a',
      },
    ],
  },
  { id: 'translate', type: 'translation_agent', label: '번역', state: 'waiting', tools: [] },
  { id: 'render', type: 'subtitle_video_agent', label: '자막 영상', state: 'waiting', tools: [] },
];
const definition = {
  nodes: agents.map(({ id, type }) => ({ id, type })),
  edges: [
    { id: 'a', source: { node: 'speech' }, target: { node: 'translate' } },
    { id: 'b', source: { node: 'translate' }, target: { node: 'render' } },
  ],
};
const progress = {
  'run-a': {
    run_id: 'run-a',
    state: 'running',
    display_state: 'failed',
    progress: {
      planned_segments: 96,
      completed_segments: 95,
      failed_segments: 1,
      finished_segments: 96,
      active_segments: [],
    },
  },
};

test('job-only cards keep real progress, blocker focus and user selection at every viewport', async () => {
  const bundle = await build({
    stdin: {
      resolveDir: process.cwd(),
      loader: 'tsx',
      contents: `
    import React,{useState} from 'react';import{createRoot}from'react-dom/client';
    import{JobExecutionFlow}from'./src/JobExecutionFlow';
    const initial=${JSON.stringify({ agents, definition, progress })};
    function App(){const[data,setData]=useState(initial);window.update=setData;window.initial=initial;
      return <JobExecutionFlow executionId="synthetic-job" definition={data.definition} agents={data.agents} progressByRunId={data.progress}/>;}
    createRoot(document.getElementById('root')).render(<App/>);`,
    },
    bundle: true,
    write: false,
    format: 'iife',
    loader: { '.css': 'empty' },
  });
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ offline: true, reducedMotion: 'reduce' });
    await context.route('**/*', (route) => route.abort());
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.setContent(
      '<!doctype html><html lang="ko"><body><div id="root"></div></body></html>',
    );
    await page.addStyleTag({ content: fs.readFileSync('src/job-execution-flow.css', 'utf8') });
    await page.addScriptTag({ content: bundle.outputFiles[0].text });
    const speech = page.getByRole('button', { name: '음성 전사 선택', exact: true });
    const translate = page.getByRole('button', { name: '번역 선택', exact: true });
    await expect(speech).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('[data-task-id="speech"]')).toContainText('처리 96 / 96');
    await expect(page.locator('[data-task-id="speech"]')).toContainText('성공 95 · 실패 1');
    await expect(page.locator('[data-task-id="speech"]')).toContainText('실패');
    await expect(page.getByRole('progressbar')).toHaveAttribute('value', '96');
    await expect(page.getByRole('progressbar')).toHaveAttribute(
      'aria-valuetext',
      '96개 처리, 성공 95개, 실패 1개, 전체 96개',
    );
    await translate.click();
    await page.evaluate(() => window.update(structuredClone(window.initial)));
    await expect(translate).toHaveAttribute('aria-pressed', 'true');
    await page.evaluate(() =>
      window.update({
        ...window.initial,
        agents: window.initial.agents.map((a, i) => ({
          ...a,
          state: i === 2 ? 'running' : 'completed',
        })),
        progress: {},
      }),
    );
    await expect(translate).toHaveAttribute('aria-pressed', 'true');
    await page.getByRole('button', { name: '현재 단계로 이동' }).click();
    await expect(page.getByRole('button', { name: '자막 영상 선택', exact: true })).toBeFocused();
    await page.evaluate(() => window.update(structuredClone(window.initial)));
    await expect(speech).toHaveAttribute('aria-pressed', 'true');
    await speech.focus();
    await page.keyboard.press('ArrowDown');
    await expect(translate).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(translate).toHaveAttribute('aria-pressed', 'true');
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 720 });
      await page.getByRole('button', { name: '현재 단계로 이동' }).click();
      assert.equal(
        await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
        false,
      );
      const rect = await speech.boundingBox();
      assert.ok(rect.width >= 240 && rect.height >= 44);
      await page.screenshot({
        path: `${process.env.TMPDIR || '/root/.hermes/cache/scratch'}/job-execution-flow-${width}.png`,
      });
    }
    await page.evaluate(() =>
      window.update({
        ...window.initial,
        progress: {
          'run-a': {
            run_id: 'run-a',
            progress: { planned_segments: null, completed_segments: 5, failed_segments: 1 },
          },
        },
      }),
    );
    await expect(page.locator('[data-task-id="speech"]')).toContainText('처리 6 / 전체 미정');
    await expect(page.getByRole('progressbar')).toHaveCount(0);
    await page.evaluate(() =>
      window.update({
        ...window.initial,
        definition: {
          nodes: [...window.initial.definition.nodes, { id: 'branch', type: 'condition' }],
          edges: [
            { id: 'c', source: { node: 'branch' }, target: { node: 'speech' } },
            { id: 'd', source: { node: 'branch' }, target: { node: 'render' } },
          ],
        },
        agents: [
          ...window.initial.agents,
          {
            id: 'branch',
            type: 'condition',
            label: '조건 분기',
            state: 'held',
            reason: '승인 대기',
            tools: [],
          },
        ],
      }),
    );
    await expect(page.getByRole('button', { name: '조건 분기 선택', exact: true })).toBeVisible();
    await expect(page.locator('[data-task-id="branch"]')).toContainText('음성 전사');
    await expect(page.locator('[data-task-id="branch"]')).toContainText('자막 영상');
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
});
