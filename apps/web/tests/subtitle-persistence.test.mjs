import test from 'node:test';
import assert from 'node:assert/strict';
import { buildSync } from 'esbuild';

const load = async (entry) =>
  import(
    'data:text/javascript;base64,' +
      Buffer.from(
        buildSync({
          entryPoints: [entry],
          bundle: true,
          write: false,
          platform: 'browser',
          format: 'esm',
          define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
        }).outputFiles[0].text,
      ).toString('base64')
  );
const api = await load('src/subtitle-copies.ts'),
  routes = await load('src/workspace-access.ts');
const id = 'a'.repeat(32),
  text = '\ufeff  \r\n00:00:00,125 --> 00:00:00,750\r\n문구\r\n줄바꿈\r\n';
const body = { id, filename: '원본.smi', title: '제목', srt: text };
const metadata = {
  id,
  filename: body.filename,
  title: body.title,
  created_at: '2026-11-12T01:02:03+00:00',
  cue_count: 1,
};
const response = (value, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });

test('save acknowledgment requires exact persisted requery; no automatic POST replay', async () => {
  const original = globalThis.fetch;
  try {
    const calls = [];
    globalThis.fetch = async (url, init) => {
      calls.push([url, init]);
      return response(init.method === 'POST' ? metadata : { ...metadata, srt: text });
    };
    const actual = await api.saveSubtitleCopy(body);
    assert.deepEqual(
      calls.map(([url, init]) => [url, init.method || 'GET']),
      [
        ['/api/subtitle-copies', 'POST'],
        ['/api/subtitle-copies/' + id, 'GET'],
      ],
    );
    assert.equal(actual.srt, text);
    assert.equal(actual.document.cues[0].id, '  ');
    assert.equal(actual.document.cues[0].start, 125);
    assert.equal(actual.document.cues[0].end, 750);
    globalThis.fetch = async (url, init) =>
      response(
        init.method === 'POST' ? metadata : { ...metadata, srt: text.replace('문구', '다른 문구') },
      );
    await assert.rejects(api.saveSubtitleCopy(body), /일치하지/);
    let attempts = 0;
    globalThis.fetch = async () => {
      attempts++;
      return response({ detail: 'AccessDenied' }, 403);
    };
    await assert.rejects(api.saveSubtitleCopy(body), /AccessDenied/);
    assert.equal(attempts, 1);
    globalThis.fetch = async () => {
      throw new Error('connection lost');
    };
    await assert.rejects(api.saveSubtitleCopy(body), /connection lost/);
  } finally {
    globalThis.fetch = original;
  }
});

test('bounded saved-list page retains errors and permits only exact ordinary copy routes', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => response({ copies: [metadata], next_cursor: null });
    assert.deepEqual((await api.listSubtitleCopies()).copies, [metadata]);
    globalThis.fetch = async () => response({ copies: [], next_cursor: id });
    await assert.rejects(api.listSubtitleCopies(id), /確認|확인/);
    globalThis.fetch = async () => response({ detail: 'list unavailable' }, 503);
    await assert.rejects(api.listSubtitleCopies(), /list unavailable/);
    for (const route of ['#/subtitles', '#/subtitles/saved', '#/subtitles/saved/' + id]) {
      assert.equal(routes.isOrdinaryRoute(route), true);
    }
    for (const route of [
      '#/subtitles/admin',
      '#/subtitles/saved/../../settings',
      '#/subtitles/saved/' + id + '/edit',
      '#/settings',
    ]) {
      assert.equal(routes.isOrdinaryRoute(route), false);
    }
  } finally {
    globalThis.fetch = original;
  }
});
