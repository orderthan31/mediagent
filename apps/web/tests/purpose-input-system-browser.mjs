import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';

test('purpose inputs preserve saved graph; system rows remain aligned at 320, 390 and desktop', async () => {
  const definition = {
    id: 'test',
    catalog_version: 2,
    revision: 4,
    name: '입력 계약',
    inputs: { video: 'video' },
    nodes: [
      {
        id: 'asr',
        type: 'transcription_agent',
        position: { x: 100, y: 100 },
        options: { source_language: 'ja', audio_source: 'video' },
        model_ref: { model_id: 'pinned', revision: 9 },
      },
    ],
    edges: [
      {
        id: 'wire',
        source: { node: '$input', port: 'video' },
        target: { node: 'asr', port: 'video' },
      },
    ],
  };
  const apiPath = path.resolve('src/api.ts');
  const bundle = await build({
    stdin: {
      resolveDir: process.cwd(),
      loader: 'tsx',
      contents: `import React from 'react';import{createRoot}from'react-dom/client';import{SystemSettings}from'./src/SystemSettings';import{WorkflowEditor}from'./src/WorkflowEditor';
window.__saved=${JSON.stringify(definition)};window.__writes=[];window.__mode='connected';
const root=createRoot(document.getElementById('root'));window.render=(view)=>root.render(view==='editor'?<WorkflowEditor key={Math.random()} initialId="test"/>:<SystemSettings key={Math.random()} storage={view==='storage'}/>);window.render('system');`,
    },
    bundle: true,
    write: false,
    platform: 'browser',
    format: 'iife',
    define: { 'import.meta.env': '{}' },
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
            contents: `export const base='/api';export const mediaUrl=p=>p;export class ApiError extends Error{};export const request=async(p,init={})=>{
if(p==='/system/resources'){if(window.__mode==='error')throw Error('offline');return{status:window.__mode,observed_at:'2026-01-01T00:00:00Z',nodes:[{id:'host',name:'작업 컴퓨터',logical_processors:16,cpu_percent:null,memory_total:17179869184,memory_available:8589934592,gpu:['Test GPU, 12, 1024, 8192']}],storage:[{status:'connected',source:'Host physical disk',total:10000000000,free:4000000000}]};}
if(p==='/renewal/storage-overview')return{originals:{count:'23',bytes:'34212632653'},observed_at:'2026-01-01T00:00:00Z'};
if(p==='/settings/node-catalog')return{nodes:[{id:'transcription_agent',label:'전사',inputs:{video:'video',audio:'audio'},outputs:{transcript:'transcript'},options:{},model_role:'transcription'}]};
if(p.endsWith('/validate'))return{valid:true,issues:[]};
if(p==='/settings/workflow-definitions/test'){if(init.method==='PUT'){window.__writes.push(JSON.parse(init.body));window.__saved={id:'test',...JSON.parse(init.body)};}return structuredClone(window.__saved);}
throw Error('unexpected '+p);};export const uploadRequest=request;export const resumeUpload=()=>{throw Error('no upload')};`,
          }));
        },
      },
    ],
  });
  const css = [
    'system-settings.css',
    'storage-overview.css',
    'workflow-editor.css',
    'workflow-canvas.css',
  ]
    .map((f) => fs.readFileSync('src/' + f, 'utf8'))
    .join('\n');
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ offline: true });
    await context.route('**/*', (r) => r.abort());
    for (const width of [320, 390, 1440]) {
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.setViewportSize({ width, height: 1000 });
      await page.route('https://purpose.invalid/', (r) =>
        r.fulfill({
          contentType: 'text/html',
          body: '<html lang="ko"><body><div id="root"></div></body></html>',
        }),
      );
      await page.goto('https://purpose.invalid/');
      await page.addStyleTag({
        content:
          ':root{--g-line:#ddd;--g-ink:#222;--g-soft:#666}*{box-sizing:border-box}body{font:14px sans-serif;margin:16px}button{min-height:44px}' +
          css,
      });
      await page.addScriptTag({ content: bundle.outputFiles[0].text });
      await expect(page.locator('h1')).toHaveText('시스템');
      await expect(page.locator('.system-resource-node')).toHaveCount(1);
      await expect(page.getByRole('link')).toHaveCount(1);
      await expect(page.getByRole('link')).toHaveAttribute('href', '#/settings/storage');
      await expect(page.locator('.system-resource-node dd').nth(1)).toHaveText('미확인');
      if (process.env.TEST_SCREENSHOTS) {
        fs.mkdirSync(process.env.TEST_SCREENSHOTS, { recursive: true });
        await page.screenshot({ path: path.join(process.env.TEST_SCREENSHOTS, `system-${width}.png`) });
      }
      const positions = await page
        .locator('.system-resource-node dd')
        .evaluateAll((es) => es.map((e) => e.getBoundingClientRect().x));
      assert.ok(positions.every((x) => Math.abs(x - positions[0]) < 1));
      for (const mode of ['stale', 'unavailable', 'error']) {
        await page.evaluate((m) => {
          window.__mode = m;
          window.render('system');
        }, mode);
        await expect(page.locator('.system-resource-node')).toHaveCount(0);
        await expect(page.locator('.system-resources')).toContainText(
          mode === 'error' ? '확인하지 못했습니다' : '미확인',
        );
      }
      await page.evaluate(() => {
        window.__mode = 'connected';
        window.render('storage');
      });
      await expect(page.locator('h1')).toHaveText('저장소 현황');
      await expect(page.locator('.storage-totals dd').first()).toHaveText('23개');
      const metrics = await page
        .locator('.storage-overview dd')
        .evaluateAll((es) => es.map((e) => e.getBoundingClientRect().x));
      assert.ok(metrics.every((x) => Math.abs(x - metrics[0]) < 1));
      const actions = await page
        .locator('.storage-overview-heading button')
        .evaluateAll((es) =>
          es.map((e) => ({
            right: e.getBoundingClientRect().right,
            height: e.getBoundingClientRect().height,
          })),
        );
      assert.equal(actions[0].right, actions[1].right);
      assert.ok(actions.every((x) => x.height >= 44));
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.evaluate(() => window.render('editor'));
      const field = page.getByRole('group', { name: '워크플로우 선택 입력 설정' });
      await expect(field).toBeVisible();
      await expect(field.getByRole('checkbox')).toHaveCount(2);
      await field.getByRole('checkbox').nth(0).check();
      await field.getByRole('checkbox').nth(1).check();
      await expect(field).toContainText('시작할 때 선택 필수');
      if (process.env.TEST_SCREENSHOTS) {
        await field.screenshot({ path: path.join(process.env.TEST_SCREENSHOTS, `inputs-${width}.png`) });
      }
      assert.ok(
        (
          await field
            .locator('label')
            .evaluateAll((es) => es.map((e) => e.getBoundingClientRect().height))
        ).every((h) => h >= 44),
      );
      const bounds = await field.boundingBox();
      assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width);
      await page.getByRole('button', { name: '저장', exact: true }).click();
      await expect(page.getByText('저장됨', { exact: true })).toBeAttached();
      const saved = await page.evaluate(() => window.__writes.at(-1));
      assert.deepEqual(saved.inputs, { video: 'video', transcript: 'transcript', audio: 'audio' });
      assert.deepEqual(saved.edges, definition.edges);
      assert.deepEqual(saved.nodes, [
        {
          ...definition.nodes[0],
          options: { ...definition.nodes[0].options, audio_source: 'selected_audio' },
        },
      ]);
      await page.evaluate(() => window.render('editor'));
      await expect(field.getByRole('checkbox').nth(0)).toBeChecked();
      await expect(field.getByRole('checkbox').nth(1)).toBeChecked();
      await page.getByRole('button', { name: '저장', exact: true }).click();
      await expect(page.getByText('저장됨', { exact: true })).toBeAttached();
      assert.deepEqual(await page.evaluate(() => window.__writes.at(-1)), saved);
      await field.getByRole('checkbox').nth(0).uncheck();
      await field.getByRole('checkbox').nth(1).uncheck();
      await page.getByRole('button', { name: '저장', exact: true }).click();
      await expect(page.getByText('저장됨', { exact: true })).toBeAttached();
      const restored = await page.evaluate(() => window.__writes.at(-1));
      const { id, ...payload } = definition;
      assert.deepEqual(restored, payload);
      for (const profile of ['subtitle_file_v1', 'face_workflow_v1']) {
        await page.evaluate((p) => {
          window.__saved.input_profile = p;
          window.render('editor');
        }, profile);
        await expect(field).toHaveCount(0);
      }
      assert.deepEqual(errors, []);
      console.log(
        JSON.stringify({
          width,
          systemValueX: positions[0],
          storageValueX: metrics[0],
          actionRight: actions[0].right,
          persistedEquality: true,
        }),
      );
      await page.close();
    }
  } finally {
    await browser.close();
  }
});
