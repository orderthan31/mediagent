import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { buildSync } from 'esbuild';

const scratch = process.env.MIDEAGENT_TEST_SCRATCH || process.env.TMPDIR || process.env.TEMP;
const id = '1'.repeat(32),
  runId = '2'.repeat(32);
const run = {
  id: runId,
  node_id: 'subtitle__generate',
  status: 'completed',
  result: {
    outputs: {
      subtitles: { type: 'subtitle' },
      sami: { type: 'subtitle' },
      transcript: { type: 'transcript' },
    },
  },
};
const helper = await import(
  'data:text/javascript;base64,' +
    Buffer.from(
      buildSync({
        entryPoints: ['src/srt-copy.ts'],
        bundle: true,
        write: false,
        format: 'esm',
        platform: 'browser',
        define: { 'import.meta.env': '{}' },
      }).outputFiles[0].text,
    ).toString('base64')
);
const render = (props, component = 'JobFiles') => {
  const directory = fs.mkdtempSync(path.join(scratch, 'subtitle-copy-unit-'));
  const outfile = path.join(directory, 'render.cjs');
  try {
    buildSync({
      stdin: {
        contents: `import React from 'react';import{renderToStaticMarkup}from'react-dom/server';import{${component}}from'./src/${component}';console.log(renderToStaticMarkup(<${component} {...${JSON.stringify(props)}}/>));`,
        loader: 'tsx',
        resolveDir: process.cwd(),
      },
      outfile,
      bundle: true,
      platform: 'node',
      format: 'cjs',
      loader: { '.css': 'empty' },
      define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
    });
    const output = spawnSync(process.execPath, [outfile], { encoding: 'utf8' });
    assert.equal(output.status, 0, output.stderr);
    return output.stdout;
  } finally {
    assert.ok(path.resolve(directory).startsWith(path.resolve(scratch) + path.sep));
    fs.rmSync(directory, { recursive: true, force: true });
  }
};

test('real accepted SRT file has a copy-edit entry beside original viewing and download', () => {
  const html = render({ base: '/renewal/jobs/' + id, runs: [run], manifest: { entry_count: 3 } });
  assert.match(html, /자막 수정/);
  assert.match(html, /자막 SRT 받기/);
  assert.match(html, /파일 목록\(JSON\) 받기/);
  assert.equal((html.match(/자막 수정/g) || []).length, 1);
});

test('goal result edit requires the same completed run, node, subtitle port and type', () => {
  const output = {
    name: 'subtitles',
    run_id: runId,
    node_id: run.node_id,
    port: 'subtitles',
    type: 'subtitle',
  };
  const props = {
    base: '/renewal/jobs/' + id,
    runs: [run],
    agents: [{ id: 'subtitle', label: '자막 파일', outputs: [output] }],
  };
  assert.equal((render(props).match(/자막 수정/g) || []).length, 1);
  for (const changed of [
    { run_id: '3'.repeat(32) },
    { node_id: 'other' },
    { type: 'artifact_manifest' },
    { port: 'sami' },
  ]) {
    // Original links remain; an unproven requested result cannot enable editing.
    const html = render(
      {
        ...props,
        agents: [{ ...props.agents[0], outputs: [{ ...output, ...changed }] }],
      },
      'GoalResults',
    );
    assert.doesNotMatch(html, /자막 수정/);
  }
  assert.doesNotMatch(render({ ...props, runs: [] }, 'GoalResults'), /자막 수정/);
  for (const status of ['waiting', 'failed', 'quarantined']) {
    assert.doesNotMatch(render({ base: props.base, runs: [{ ...run, status }] }), /자막 수정/);
  }
  assert.equal(helper.artifactSrtSource('https://untrusted.invalid', run, 'subtitles'), null);
});

const raw = (text) => new TextEncoder().encode(text);
const decode = (bytes) => new TextDecoder('utf-8', { ignoreBOM: true }).decode(bytes);
const sourceText =
  '\ufeff90071992547409931234567890\r\n00:00:00,001 --> 00:00:03,999\r\n  첫 줄  \r\n둘째 줄\t\r\n \t\r\n002\n00:00:01,000 --> 00:00:02,000\n<script>alert("text")</script>  \n\n3\r00:00:04,000 --> 00:00:05,000\r마지막\r\r';

test('actual preserve-cue producer literal IDs reopen and edit without renumbering', async () => {
  const rows = [
    { id: 'cue-a', start: 0.125, end: 2.875, text: '  첫 문구  ' },
    { id: '자막-②', start: 1.25, end: 3.5, text: '둘째 문구\n 그대로 ' },
    { id: -17, start: 4, end: 5, text: '음수 정수 ID' },
    { id: '😀'.repeat(128), start: 5, end: 6, text: '128자 literal ID' },
  ];
  const producer = spawnSync(
    process.platform === 'win32' ? 'C:/Python314/python.exe' : 'python',
    [
      '-I',
      '-B',
      '-X',
      'utf8',
      '-c',
      "import sys,json; sys.path.insert(0,sys.argv[1]); from video_service.timed_subtitles import preserved_files; rows=json.loads(sys.stdin.read()); rows.append({'id':10**140,'start':6,'end':7,'text':'큰 정수 ID'}); sys.stdout.buffer.write(preserved_files(rows,{'format':'srt'})['subtitles'])",
      path.resolve('../../packages/shared'),
    ],
    { input: JSON.stringify(rows) },
  );
  assert.equal(producer.status, 0, producer.stderr?.toString());
  const document = await helper.parseSrtCopy(producer.stdout);
  assert.deepEqual(
    document.cues.map((cue) => cue.id),
    [...rows.map((row) => String(row.id)), '1' + '0'.repeat(140)],
  );
  assert.deepEqual(Buffer.from(helper.serializeSrtCopy(document, {})), producer.stdout);
  assert.equal(
    decode(helper.serializeSrtCopy(document, { 0: '  수정 문구  ' })),
    producer.stdout.toString('utf8').replace('  첫 문구  ', '  수정 문구  '),
  );
  for (const invalidId of ['invalid\tID', 'x'.repeat(129)]) {
    await assert.rejects(
      helper.parseSrtCopy(raw(`${invalidId}\n00:00:00,000 --> 00:00:01,000\n문구\n`)),
    );
  }
});

test('actual producer space-only literal IDs are not discarded as cue separators', async () => {
  const rows = [
    { id: ' ', start: 0.125, end: 2.875, text: '  첫 문구  ' },
    { id: ' cue-b ', start: 1.25, end: 3.5, text: '둘째 문구\n 그대로 ' },
    { id: '  ', start: 4, end: 5, text: '마지막 문구' },
  ];
  const producer = spawnSync(
    process.platform === 'win32' ? 'C:/Python314/python.exe' : 'python',
    [
      '-I',
      '-B',
      '-X',
      'utf8',
      '-c',
      "import sys,json; sys.path.insert(0,sys.argv[1]); from video_service.timed_subtitles import preserved_files; sys.stdout.buffer.write(preserved_files(json.loads(sys.stdin.read()),{'format':'srt'})['subtitles'])",
      path.resolve('../../packages/shared'),
    ],
    { input: JSON.stringify(rows) },
  );
  assert.equal(producer.status, 0, producer.stderr?.toString());
  const document = await helper.parseSrtCopy(producer.stdout);
  assert.deepEqual(
    document.cues.map((cue) => cue.id),
    rows.map((row) => row.id),
  );
  assert.deepEqual(Buffer.from(helper.serializeSrtCopy(document, {})), producer.stdout);
  const edited = helper.serializeSrtCopy(document, { 1: '둘째 수정 문구\n 그대로 ' });
  assert.equal(
    decode(edited),
    producer.stdout.toString('utf8').replace('둘째 문구', '둘째 수정 문구'),
  );
  assert.deepEqual(
    (await helper.parseSrtCopy(edited)).cues.map((cue) => cue.id),
    rows.map((row) => row.id),
  );
});

test('lossless source parser preserves BOM, huge ID, mixed EOL, whitespace, overlap and one edited cue only', async () => {
  const doc = await helper.parseSrtCopy(raw(sourceText));
  assert.equal(doc.cues[0].id, '90071992547409931234567890');
  assert.equal(doc.cues[1].start, 1000); // Overlap is valid; never retime it.
  assert.deepEqual(helper.serializeSrtCopy(doc, {}), raw(sourceText));
  assert.deepEqual(
    helper.serializeSrtCopy(doc, { 0: helper.cueCopyText(doc.cues[0]) }),
    raw(sourceText),
  );
  assert.equal(
    decode(helper.serializeSrtCopy(doc, { 0: '  첫 문구 수정  \n둘째 줄\t' })),
    sourceText.replace('  첫 줄  ', '  첫 문구 수정  '),
  );
  assert.equal(
    decode(helper.serializeSrtCopy(doc, { 1: '  수정문구  ' })),
    sourceText.replace('<script>alert("text")</script>  ', '  수정문구  '),
  );
  assert.throws(() => helper.serializeSrtCopy(doc, { 0: '   ' }), /문구/);
  assert.throws(() => helper.serializeSrtCopy(doc, { 0: '첫 줄\n\n둘째 줄' }), /빈 줄/);
});

test('whole 101+ cues and over 16KB text survive; native 10000/16MiB finite budgets remain', async () => {
  const make = (count) =>
    Array.from(
      { length: count },
      (_, i) => `${i + 1}\n00:00:00,000 --> 00:00:01,000\n${'문구'.repeat(100)}\n`,
    ).join('\n');
  const input = raw(make(121));
  assert.ok(input.length > 16000);
  const doc = await helper.parseSrtCopy(input);
  assert.equal(doc.cues.length, 121);
  assert.deepEqual(helper.serializeSrtCopy(doc, {}), input);
  await assert.rejects(helper.parseSrtCopy(raw(make(10001))), /10000/);
  await assert.rejects(helper.parseSrtCopy(new Uint8Array(16 * 1024 * 1024 + 1)), /16MiB/);
  assert.throws(() => helper.serializeSrtCopy(doc, { 0: 'x'.repeat(16 * 1024 * 1024) }), /16MiB/);
});

test('invalid file, incomplete or inverted time, duplicate ID and empty cue stay errors', async () => {
  for (const text of [
    '',
    '{}',
    '문구만',
    '1\n00:00:00 --> 00:00:01\n문구',
    '1\n00:00:02,000 --> 00:00:01,000\n문구',
    '1\n00:00:00,000 --> 00:00:01,000\n\n',
    '1\n00:00:00,000 --> 00:00:01,000\n문구\n\n1\n00:00:02,000 --> 00:00:03,000\n다음',
  ]) {
    await assert.rejects(helper.parseSrtCopy(raw(text)));
  }
  await assert.rejects(helper.parseSrtCopy(new Uint8Array([255])), /UTF-8/);
});

test('real authenticated read is bound to job/run/file, bounded and GET-only', async (t) => {
  const source = helper.artifactSrtSource('/renewal/jobs/' + id, run, 'subtitles');
  const headers = {
    'content-type': 'text/plain; charset=utf-8',
    'content-disposition': `attachment; filename="${runId}-subtitles.srt"`,
  };
  let response = () => new Response(raw(sourceText), { headers });
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    calls.push({ url, init });
    return response();
  });
  const document = await helper.readSrtCopy(source, new AbortController().signal);
  assert.deepEqual(document.raw, raw(sourceText));
  assert.equal(calls[0].url, `/api/renewal/jobs/${id}/artifacts/${runId}/subtitles?download=true`);
  assert.equal(calls[0].init.method, 'GET');
  assert.equal(calls[0].init.credentials, 'include');
  assert.equal(calls[0].init.redirect, 'error');
  assert.equal(calls[0].init.body, undefined);
  response = () =>
    new Response('{}', { headers: { ...headers, 'content-type': 'application/json' } });
  await assert.rejects(helper.readSrtCopy(source, new AbortController().signal), /SRT/);
  response = () =>
    new Response(raw(sourceText), {
      headers: { ...headers, 'content-disposition': 'attachment; filename="wrong.srt"' },
    });
  await assert.rejects(helper.readSrtCopy(source, new AbortController().signal), /SRT/);
  response = () => new Response('unavailable', { status: 404 });
  await assert.rejects(helper.readSrtCopy(source, new AbortController().signal), /불러오지/);
  response = () => new Response(new Uint8Array(16 * 1024 * 1024 + 1), { headers });
  await assert.rejects(helper.readSrtCopy(source, new AbortController().signal), /16MiB/);
  const track = helper.trackSrtSource(id, runId, 'translated.pt-BR', 'srt', {
    filename: 'translated.pt-BR.srt',
    reference: { type: 'subtitle' },
  });
  assert.equal(
    helper.srtSourcePath(track),
    `/renewal/jobs/${id}/subtitle-outputs/${runId}/translated.pt-BR/srt`,
  );
  assert.equal(
    helper.trackSrtSource(id, runId, 'original', 'smi', {
      filename: 'original.smi',
      reference: { type: 'subtitle' },
    }),
    null,
  );
});
