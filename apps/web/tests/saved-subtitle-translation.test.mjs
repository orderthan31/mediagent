// Production result component with local URL/action boundaries, no job/API I/O.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { transform } from 'esbuild';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';

test('existing transcript download remains JSON and is labelled for its real producer', async () => {
  const transformed = await transform(fs.readFileSync('src/GoalResults.tsx', 'utf8'), {
    loader: 'tsx',
    format: 'cjs',
    jsx: 'automatic',
  });
  const module = { exports: {} },
    realRequire = createRequire(import.meta.url);
  const localRequire = (name) =>
    name === './api'
      ? { mediaUrl: (value) => '/api' + value }
      : name === './SrtCopyEditor'
        ? { SrtCopyAction: () => null }
        : name === './srt-copy'
          ? { artifactSrtSource: () => assert.fail('MT transcript must not become an SRT source') }
          : realRequire(name);
  new Function('require', 'module', 'exports', transformed.code)(
    localRequire,
    module,
    module.exports,
  );
  const outputs = [
    {
      name: 'transcript',
      type: 'transcript',
      port: 'transcript',
      node_id: 'mt__translate',
      run_id: 'b'.repeat(32),
    },
  ];
  const render = (type) =>
    renderToStaticMarkup(
      createElement(module.exports.GoalResults, {
        base: '/renewal/jobs/' + 'a'.repeat(32),
        agents: [{ id: 'mt', type, label: '합성 목표', outputs }],
      }),
    );
  const translated = render('translation_agent');
  assert.match(translated, /번역문\(JSON\) 받기/);
  assert.match(translated, /artifacts\/[b]{32}\/transcript\?download=true/);
  assert.doesNotMatch(translated, /MP4|자막 SRT/);
  assert.match(render('transcription_agent'), /전사문\(JSON\) 받기/);
});
