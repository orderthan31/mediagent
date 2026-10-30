import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { buildSync } from 'esbuild';

test('task panel has accessible output and log tabs without losing output children', () => {
  const file = new URL('../src/TaskResultTabs.tsx', import.meta.url);
  assert.ok(fs.existsSync(file), 'task output/log tabs are missing');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'task-tabs-'));
  const output = path.join(root, 'render.cjs');
  buildSync({
    stdin: {
      contents: `import React from 'react'; import {renderToStaticMarkup} from 'react-dom/server'; import {TaskResultTabs} from './src/TaskResultTabs'; console.log(renderToStaticMarkup(<TaskResultTabs jobId="a" runId="b" initialState="completed"><a href="/actual-download">기존 출력 받기</a></TaskResultTabs>));`,
      resolveDir: process.cwd(),
      loader: 'tsx',
    },
    outfile: output,
    bundle: true,
    platform: 'node',
    format: 'cjs',
    define: { 'import.meta.env': '{}' },
    loader: { '.css': 'empty' },
  });
  const rendered = spawnSync(process.execPath, [output], { encoding: 'utf8' });
  assert.equal(rendered.status, 0, rendered.stderr);
  assert.match(rendered.stdout, /role="tablist"/);
  assert.match(rendered.stdout, />출력<\/button>/);
  assert.match(rendered.stdout, />로그<\/button>/);
  assert.match(rendered.stdout, /기존 출력 받기/);
  const detail = fs.readFileSync(new URL('../src/RenewalJobDetail.tsx', import.meta.url), 'utf8');
  assert.match(detail, /<TaskResultTabs/);
  assert.match(detail, /key=\{`\$\{id\}:\$\{selected\}`\}/);
});
