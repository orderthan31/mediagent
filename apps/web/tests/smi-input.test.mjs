import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { buildSync } from 'esbuild';

const source = buildSync({
  entryPoints: ['src/direct-subtitle.ts'],
  bundle: true,
  write: false,
  platform: 'browser',
  format: 'esm',
  define: { 'import.meta.env': '{}' },
}).outputFiles[0].text;
const direct = await import(
  'data:text/javascript;base64,' +
    Buffer.from(source + '\n//# sourceURL=smi-input-helper.mjs').toString('base64')
);
const raw = (text) => Buffer.from(text, 'utf8');
const decode = (bytes) => new TextDecoder('utf-8', { ignoreBOM: true }).decode(bytes);
const file = (name, bytes) => ({
  name,
  size: bytes.length,
  arrayBuffer: async () => new Uint8Array(bytes).buffer,
});
const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');
const wrap = (body) => `<SAMI><BODY>${body}</BODY></SAMI>`;
const simple =
  '\ufeff<SAMI><HEAD><META charset="UTF-8"></HEAD><BODY><SYNC Start=0><P Class=KRCC>한국어 &amp; &#xBB38;&#44396;<BR>둘째 줄<SYNC Start=800><P>&nbsp;<SYNC Start=1000><P Class=KRCC>다음 자막<SYNC Start=1800><P>&nbsp;</BODY></SAMI>';

test('UTF-8 BOM SMI/SAMI imports normal open P/SYNC tags, clear gaps, BR and entities into the same cues', async () => {
  const bytes = raw(simple),
    before = hash(bytes);
  for (const name of ['short.smi', 'short.SAMI']) {
    const document = await direct.readDirectSubtitle(file(name, bytes));
    assert.deepEqual(
      document.cues.map(({ start, end, text }) => ({ start, end, text })),
      [
        { start: 0, end: 800, text: '한국어 & 문구\n둘째 줄' },
        { start: 1000, end: 1800, text: '다음 자막' },
      ],
    );
    const srt = decode(
      direct.serializeDirectSubtitle(
        document,
        { 0: { text: '수정 <문구>', start: '00:00:00,125', end: '00:00:00,750' } },
        'srt',
      ),
    );
    assert.equal(
      srt,
      '1\n00:00:00,125 --> 00:00:00,750\n수정 <문구>\n\n2\n00:00:01,000 --> 00:00:01,800\n다음 자막\n',
    );
    const smi = direct.serializeDirectSubtitle(document, {}, 'smi');
    const reopened = await direct.readDirectSubtitle(file('reopened.smi', smi));
    assert.deepEqual(
      reopened.cues.map(({ start, end, text }) => ({ start, end, text })),
      document.cues.map(({ start, end, text }) => ({ start, end, text })),
    );
    assert.equal(direct.directDownloadName(name, 'srt'), 'short-수정본.srt');
  }
  assert.equal(hash(bytes), before);
});

test('SMI source whitespace is soft HTML spacing while BR alone creates caption linebreaks', async () => {
  for (const [caption, expected] of [
    ['첫 줄<BR>\n둘째 줄', '첫 줄\n둘째 줄'],
    ['\r\n  첫 줄\r\n  <BR>\r\n\t둘째 줄\r\n', '첫 줄\n둘째 줄'],
    ['첫 줄\n   둘째 줄', '첫 줄 둘째 줄'],
    ['첫 줄\r\n\t둘째 줄', '첫 줄 둘째 줄'],
    ['  첫 줄  <BR> 둘째 &amp; 줄 ', '  첫 줄  \n 둘째 & 줄 '],
  ]) {
    const input = raw(wrap(`<SYNC Start=0><P>${caption}<SYNC Start=1000><P>&nbsp;`));
    const before = hash(input);
    const document = await direct.readDirectSubtitle(file('ordinary.smi', input));
    assert.equal(document.cues.length, 1);
    assert.equal(document.cues[0].text, expected);
    assert.equal(document.cues[0].start, 0);
    assert.equal(document.cues[0].end, 1000);
    const srt = decode(direct.serializeDirectSubtitle(document, {}, 'srt'));
    assert.equal(srt, `1\n00:00:00,000 --> 00:00:01,000\n${expected}\n`);
    const reopened = await direct.readDirectSubtitle(
      file('copy.smi', direct.serializeDirectSubtitle(document, {}, 'smi')),
    );
    assert.equal(reopened.cues[0].text, expected);
    assert.equal(hash(input), before);
  }
  for (const caption of ['첫 줄<BR><BR>둘째 줄', '<BR>문구', '문구<BR>']) {
    await assert.rejects(
      direct.readDirectSubtitle(
        file('blank.smi', raw(wrap(`<SYNC Start=0><P>${caption}<SYNC Start=1000><P>&nbsp;`))),
      ),
      /SMI.*빈 줄/,
    );
  }
});

test('actual Python SAMI producer roundtrips clear intervals and escaped text without inventing timing', async () => {
  const rows = [
    { start: 0.125, end: 0.75, text: '  한국어 & <문구>  \n둘째 줄' },
    { start: 1, end: 1.8, text: '다음 자막' },
  ];
  const producer = spawnSync(
    process.platform === 'win32' ? 'C:/Python314/python.exe' : 'python',
    [
      '-I',
      '-B',
      '-X',
      'utf8',
      '-c',
      "import sys,json; sys.path.insert(0,sys.argv[1]); from video_service.sami import segments_to_sami; from video_service.transcript import TranscriptSegment; rows=json.loads(sys.stdin.read()); sys.stdout.buffer.write(segments_to_sami([TranscriptSegment.from_dict(row) for row in rows],language='ko',preserve_text=True).encode('utf-8'))",
      path.resolve('../../packages/shared'),
    ],
    { input: JSON.stringify(rows) },
  );
  assert.equal(producer.status, 0, producer.stderr?.toString());
  const before = hash(producer.stdout);
  const document = await direct.readDirectSubtitle(file('native.smi', producer.stdout));
  assert.deepEqual(
    document.cues.map(({ start, end, text }) => ({ start: start / 1000, end: end / 1000, text })),
    rows,
  );
  const output = direct.serializeDirectSubtitle(document, {}, 'smi');
  const reopened = await direct.readDirectSubtitle(file('native-copy.smi', output));
  assert.deepEqual(
    reopened.cues.map(({ start, end, text }) => ({ start: start / 1000, end: end / 1000, text })),
    rows,
  );
  assert.equal(hash(producer.stdout), before);
});

test('empty, invalid or unclosed final cues and unsupported encodings are explicit errors', async () => {
  for (const body of [
    '',
    '<P>시각 없음',
    '<SYNC Start=0><P>마지막 종료 없음',
    '<SYNC Start=0><P>&nbsp;',
    '<SYNC Start=-1><P>음수<SYNC Start=10><P>&nbsp;',
    '<SYNC Start=NaN><P>비유한<SYNC Start=10><P>&nbsp;',
    '<SYNC Start=100><P>역순<SYNC Start=50><P>&nbsp;',
  ]) {
    await assert.rejects(direct.readDirectSubtitle(file('invalid.smi', raw(wrap(body)))));
  }
  await assert.rejects(
    direct.readDirectSubtitle(file('missing.smi', raw(wrap('<SYNC Start=0><P>문구')))),
    /종료 시각/,
  );
  await assert.rejects(
    direct.readDirectSubtitle(file('encoding.smi', new Uint8Array([0xbe, 0xc8]))),
    /UTF-8/,
  );
  await assert.rejects(
    direct.readDirectSubtitle(
      file(
        'encoding.smi',
        raw(
          '<SAMI><HEAD><META charset=EUC-KR></HEAD><BODY><SYNC Start=0><P>A<SYNC Start=10><P>&nbsp;</BODY></SAMI>',
        ),
      ),
    ),
    /UTF-8/,
  );
});

test('multiple languages and active HTML/resources are never mixed, rendered or fetched', async () => {
  const multi = wrap(
    '<SYNC Start=0><P Class=KRCC>한국어<P Class=ENCC>English<SYNC Start=100><P Class=KRCC>&nbsp;',
  );
  await assert.rejects(direct.readDirectSubtitle(file('multi.smi', raw(multi))), /여러 언어/);
  await assert.rejects(
    direct.readDirectSubtitle(
      file(
        'multi.smi',
        raw(
          wrap(
            '<SYNC Start=0><P Class=KRCC>한국어<SYNC Start=100><P Class=ENCC>English<SYNC Start=200><P Class=ENCC>&nbsp;',
          ),
        ),
      ),
    ),
    /여러 언어/,
  );
  for (const tag of [
    '<script>run()</script>',
    '<img src="https://not-requested.invalid/a">',
    '<iframe src="https://not-requested.invalid/">',
  ]) {
    await assert.rejects(
      direct.readDirectSubtitle(
        file('html.smi', raw(wrap(`<SYNC Start=0><P>${tag}<SYNC Start=100><P>&nbsp;`))),
      ),
    );
  }
  const escaped = wrap(
    '<SYNC Start=0><P>&lt;script&gt;run()&lt;/script&gt; &quot;문구&quot;<SYNC Start=100><P>&nbsp;',
  );
  const document = await direct.readDirectSubtitle(file('escaped.smi', raw(escaped)));
  assert.equal(document.cues[0].text, '<script>run()</script> "문구"');
  assert.doesNotMatch(decode(direct.serializeDirectSubtitle(document, {}, 'smi')), /<script>/i);
});

test('SMI keeps existing finite byte/cue budgets and does not reuse the 100-cue wire cap', async () => {
  const body = Array.from(
    { length: 121 },
    (_, i) =>
      `<SYNC Start=${i * 1000}><P>${'한국어 문구'.repeat(40)} ${i + 1}<SYNC Start=${i * 1000 + 800}><P>&nbsp;`,
  ).join('');
  const document = await direct.readDirectSubtitle(file('long.smi', raw(wrap(body))));
  assert.equal(document.cues.length, 121);
  await assert.rejects(
    direct.readDirectSubtitle({ ...file('large.smi', raw(simple)), size: 16 * 1024 * 1024 + 1 }),
    /16MiB/,
  );
  const tooMany =
    Array.from({ length: 10001 }, (_, i) => `<SYNC Start=${i}><P>A`).join('') +
    '<SYNC Start=10001><P>&nbsp;';
  await assert.rejects(direct.readDirectSubtitle(file('many.smi', raw(wrap(tooMany)))), /10000/);
});
