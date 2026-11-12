import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
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
          define: { 'import.meta.env': '{}' },
        }).outputFiles[0].text + '\n//# sourceURL=direct-subtitle-helper.mjs',
      ).toString('base64')
  );
const direct = await load('src/direct-subtitle.ts');
const copy = await load('src/srt-copy.ts');
const bytes = (text) => new TextEncoder().encode(text);
const text = (raw) => new TextDecoder('utf-8', { ignoreBOM: true }).decode(raw);
const file = (name, value) => ({
  name,
  size: bytes(value).length,
  arrayBuffer: async () => bytes(value).buffer,
});
const original =
  '\ufeff90071992547409931234567890\r\n00:00:00,000 --> 00:00:00,800\r\n  첫 문구  \r\n둘째 줄\t\r\n\r\n \r\n00:00:01,000 --> 00:00:01,800\r\n그대로 남는 문구  \r\n';

test('direct File uses the real parser and changes only explicitly edited text/start/end spans', async () => {
  const raw = bytes(original);
  const document = await direct.readDirectSrt(file('original.srt', original));
  assert.deepEqual(document.raw, raw);
  assert.deepEqual(
    document.cues.map((cue) => cue.id),
    ['90071992547409931234567890', ' '],
  );
  assert.deepEqual(direct.serializeDirectSubtitle(document, {}, 'srt'), raw);
  for (const [changes, before, after] of [
    [{ text: '  수정 문구  \n둘째 줄\t' }, '  첫 문구  ', '  수정 문구  '],
    [{ start: '00:00:00,125' }, '00:00:00,000', '00:00:00,125'],
    [{ end: '00:00:00,789' }, '00:00:00,800', '00:00:00,789'],
  ]) {
    const serialized = direct.serializeDirectSubtitle(document, { 0: changes }, 'srt');
    assert.equal(text(serialized), original.replace(before, after));
    const reopened = await copy.parseSrtCopy(serialized);
    assert.equal(reopened.cues[1].id, ' ');
    assert.equal(reopened.cues[1].clock, document.cues[1].clock);
    assert.equal(reopened.cues[1].text, document.cues[1].text);
  }
  assert.deepEqual(document.raw, raw);
});

test('invalid/nonfinite/negative/submillisecond/inverted timing and empty text block export', async () => {
  const document = await direct.readDirectSrt(file('input.srt', original));
  for (const start of ['', 'NaN', 'Infinity', '-00:00:00,100', '00:00:00,0001', '00:60:00,000']) {
    assert.ok(direct.directCueIssues({ text: '문구', start, end: '00:00:01,000' }).start);
    assert.throws(() => direct.serializeDirectSubtitle(document, { 0: { start } }, 'srt'));
  }
  for (const format of ['srt', 'smi']) {
    assert.throws(
      () =>
        direct.serializeDirectSubtitle(
          document,
          { 0: { start: '00:00:01,000', end: '00:00:00,500' } },
          format,
        ),
      /종료/,
    );
    assert.throws(
      () => direct.serializeDirectSubtitle(document, { 0: { text: '  ' } }, format),
      /문구/,
    );
  }
  for (const bad of [file('input.smi', original), file('empty.srt', ''), file('bad.srt', '{}')]) {
    await assert.rejects(direct.readDirectSrt(bad));
  }
  await assert.rejects(
    direct.readDirectSrt({
      name: 'bad.srt',
      size: 1,
      arrayBuffer: async () => new Uint8Array([255]).buffer,
    }),
    /UTF-8/,
  );
});

test('SMI output matches real native SAMI event/text semantics and safely escapes caption HTML', async () => {
  const document = await direct.readDirectSrt(file('input.srt', original));
  const caption = '  <script>doNotRun()</script> & "문구"\n둘째 줄\t';
  const edits = { 0: { text: caption, start: '00:00:00,125', end: '00:00:00,750' } };
  const smi = text(direct.serializeDirectSubtitle(document, edits, 'smi'));
  assert.doesNotMatch(smi, /<script>|<img|<iframe/i);
  assert.match(smi, /&lt;script&gt;/);
  assert.match(smi, /<BR>/);
  const rows = [
    { start: 0.125, end: 0.75, text: caption },
    { start: 1, end: 1.8, text: '그대로 남는 문구  ' },
  ];
  const native = spawnSync(
    process.platform === 'win32' ? 'C:/Python314/python.exe' : 'python',
    [
      '-I',
      '-B',
      '-X',
      'utf8',
      '-c',
      `
import sys,json
from html.parser import HTMLParser
sys.path.insert(0,sys.argv[1])
from video_service.sami import segments_to_sami
from video_service.transcript import TranscriptSegment
class Events(HTMLParser):
 def __init__(self): super().__init__(convert_charrefs=True); self.events=[]; self.in_p=False
 def handle_starttag(self,tag,attrs):
  if tag=='sync': self.events.append([dict(attrs)['start'],''])
  if tag=='p': self.in_p=True
  if tag=='br' and self.in_p: self.events[-1][1]+='\\n'
 def handle_endtag(self,tag):
  if tag=='p': self.in_p=False
 def handle_data(self,value):
  if self.in_p: self.events[-1][1]+=value
value=json.loads(sys.stdin.read())
reference=segments_to_sami([TranscriptSegment.from_dict(row) for row in value['rows']],language='und',preserve_text=True)
actual,expected=Events(),Events()
actual.feed(value['smi']); expected.feed(reference)
assert actual.events==expected.events,(actual.events,expected.events)
print('native SAMI event/text parity: PASS')
`,
      path.resolve('../../packages/shared'),
    ],
    { input: JSON.stringify({ rows, smi }), encoding: 'utf8' },
  );
  assert.equal(native.status, 0, native.stderr);
  assert.match(native.stdout, /PASS/);
  assert.equal(direct.directDownloadName('../<script>.srt', 'smi'), '..__script_-수정본.smi');
});

test('normal overlap is retained in SRT and blocks only SMI, without reorder or retiming', async () => {
  const document = await direct.readDirectSrt(file('input.srt', original));
  const edits = { 0: { end: '00:00:01,500' } };
  assert.equal(
    text(direct.serializeDirectSubtitle(document, edits, 'srt')),
    original.replace('00:00:00,800', '00:00:01,500'),
  );
  assert.throws(() => direct.serializeDirectSubtitle(document, edits, 'smi'), /SMI.*겹치/);
  const reordered = { 0: { start: '00:00:02,000', end: '00:00:03,000' } };
  assert.throws(() => direct.serializeDirectSubtitle(document, reordered, 'smi'), /SMI.*순서/);
  assert.equal(direct.directCueValue(document, edits, 1).start, '00:00:01,000');
});

test('whole 121+ cues/16KB and finite native byte/cue budgets remain on direct input and exports', async () => {
  const raw = Array.from(
    { length: 121 },
    (_, i) =>
      `${i + 1}\n00:00:${String(i % 60).padStart(2, '0')},000 --> 00:00:${String(i % 60).padStart(2, '0')},800\n${'합성 문구'.repeat(80)}\n`,
  ).join('\n');
  assert.ok(bytes(raw).length > 16000);
  const document = await direct.readDirectSrt(file('long.srt', raw));
  assert.equal(document.cues.length, 121);
  assert.deepEqual(direct.serializeDirectSubtitle(document, {}, 'srt'), bytes(raw));
  await assert.rejects(
    direct.readDirectSrt({ ...file('large.srt', ''), size: 16 * 1024 * 1024 + 1 }),
    /16MiB/,
  );
  assert.throws(
    () =>
      direct.serializeDirectSubtitle(
        document,
        { 0: { text: 'x'.repeat(16 * 1024 * 1024) } },
        'srt',
      ),
    /16MiB/,
  );
});
