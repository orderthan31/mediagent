import test from 'node:test';
import assert from 'node:assert/strict';
import { buildSync } from 'esbuild';
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const source = buildSync({
  entryPoints: ['src/StorageOverview.tsx'],
  bundle: true,
  write: false,
  platform: 'browser',
  format: 'esm',
  loader: { '.css': 'empty' },
  define: { 'import.meta.env': '{}' },
}).outputFiles[0].text;
const { formatStorageGB } = await import(
  'data:text/javascript;base64,' +
    Buffer.from(source + '\n//# sourceURL=storage-gb-helper.mjs').toString('base64')
);
const videoSource = buildSync({
  entryPoints: ['src/video-api.ts'],
  bundle: true,
  write: false,
  platform: 'browser',
  format: 'esm',
  define: { 'import.meta.env': '{}' },
}).outputFiles[0].text;
const { sizeLabel } = await import(
  'data:text/javascript;base64,' +
    Buffer.from(videoSource + '\n//# sourceURL=video-size-helper.mjs').toString('base64')
);

test('shared original/file/upload formatter uses fixed decimal GB for sub-GB and larger files', () => {
  assert.equal(sizeLabel(674758656), '0.67 GB'); // Previously 643.5 MB.
  assert.equal(sizeLabel(2147483648), '2.15 GB'); // Binary divisor must not be labelled GB.
  assert.equal(sizeLabel(512), '0.00 GB');
  assert.equal(sizeLabel(0), '0.00 GB');
  for (const value of [undefined, null, NaN, Infinity, -1]) {
    assert.equal(sizeLabel(value), '미확인');
  }
});

test('real original cards/detail and upload counters use GB while filenames, raw progress and limits stay unchanged', () => {
  const scratch = process.env.MIDEAGENT_TEST_SCRATCH || process.env.TMPDIR || process.env.TEMP;
  const directory = fs.mkdtempSync(path.join(scratch, 'storage-gb-render-'));
  const outfile = path.join(directory, 'render.cjs');
  try {
    buildSync({
      stdin: {
        resolveDir: process.cwd(),
        loader: 'tsx',
        contents: `
        import React from 'react';import{renderToStaticMarkup}from'react-dom/server';import assert from'node:assert/strict';
        import{StorageAssetRow,StorageVideoInfo}from'./src/StorageVideo';import{StorageUploads}from'./src/StorageUploads';
        const name='literal_643.5 MB_16MiB.mp4';
        const video=Object.freeze({asset_id:'a'.repeat(32),original_filename:name,size_bytes:674758656,created_at:'2026-01-01T00:00:00Z',provenance:{kind:'original'},media:{duration:12,width:640,height:360,has_audio:true}});
        const before=JSON.stringify(video);
        const row=renderToStaticMarkup(<StorageAssetRow video={video} thumbnail={null}/>);
        const detail=renderToStaticMarkup(<StorageVideoInfo video={video} assetId={video.asset_id}/>);
        assert.ok(row.includes('>0.67 GB<'));assert.ok(detail.includes('>0.67 GB<'));
        assert.ok(row.includes(name));assert.ok(detail.includes('영상 정보'));
        assert.equal(video.original_filename,name);assert.equal(JSON.stringify(video),before);
        const action=()=>{throw new Error('render must not invoke upload or product actions')};
        const props={online:true,busy:'',onPause:action,onResume:action,onRemove:action,onRegister:action,onChooseResume:action,onDeleteSession:action};
        const item=Object.freeze({key:'unit-upload',name,size:1024,progress:512,payload:{},createdAt:0,state:'uploading'});
        const itemBefore=JSON.stringify(item);
        const upload=renderToStaticMarkup(<StorageUploads {...props} uploads={[item]} sessions={[]}/>).replace(/<!--.*?-->/g,'');
        assert.ok(upload.includes(name));assert.ok(upload.includes('0.00 GB / 0.00 GB'));assert.match(upload,/50%/);
        assert.match(upload,/aria-valuenow="512"/);assert.match(upload,/aria-valuemax="1024"/);assert.equal(JSON.stringify(item),itemBefore);
        const session=Object.freeze({upload_id:'unit-session',filename:name,expected_size:674758656,uploaded_bytes:335544320,status:'PAUSED',created_at:'2026-01-01T00:00:00Z'});
        const sessionBefore=JSON.stringify(session);
        const resumed=renderToStaticMarkup(<StorageUploads {...props} online={false} uploads={[]} sessions={[session]}/>).replace(/<!--.*?-->/g,'');
        assert.ok(resumed.includes('0.34 GB / 0.67 GB'));assert.match(resumed,/49%/);assert.match(resumed,/최신 상태 미확인/);
        assert.match(resumed,/aria-valuenow="335544320"/);assert.match(resumed,/aria-valuemax="674758656"/);assert.equal(JSON.stringify(session),sessionBefore);
        const empty=renderToStaticMarkup(<StorageUploads {...props} uploads={[]} sessions={[]}/>);
        assert.match(empty,/원본 파일당 최대 4 GiB/);
      `,
      },
      outfile,
      bundle: true,
      platform: 'node',
      format: 'cjs',
      loader: { '.css': 'empty' },
      define: { 'import.meta.env': '{"VITE_RENEWAL_BACKEND":"1"}' },
    });
    const result = spawnSync(process.execPath, [outfile], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
  } finally {
    assert.ok(path.resolve(directory).startsWith(path.resolve(scratch) + path.sep));
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test('storage capacity is decimal GB with exactly two decimals, including small/zero totals', () => {
  for (const [raw, expected] of [
    ['0', '0.00 GB'],
    ['3072', '0.00 GB'],
    ['4999999', '0.00 GB'],
    ['5000000', '0.01 GB'],
    ['999999999', '1.00 GB'],
    [1000000000, '1.00 GB'],
    ['34212632653', '34.21 GB'],
    ['34214999999', '34.21 GB'],
    ['34215000000', '34.22 GB'],
    [10737418240, '10.74 GB'],
    [3221225472, '3.22 GB'],
    [7516192768, '7.52 GB'],
  ]) {
    assert.equal(formatStorageGB(raw), expected);
  }
});

test('logical decimal strings retain BigInt precision at rounding boundaries beyond Number safety', () => {
  assert.equal(formatStorageGB('9007199254999999'), '9007199.25 GB');
  assert.equal(formatStorageGB('9007199255000000'), '9007199.26 GB');
  assert.equal(formatStorageGB('9999999999999999999999999999'), '10000000000000000000.00 GB');
});

test('formatting does not change raw byte calculations and never coerces unknown values to zero', () => {
  const disk = Object.freeze({ total: 1004000000, free: 6000000 });
  assert.equal(formatStorageGB(disk.total), '1.00 GB');
  assert.equal(formatStorageGB(disk.free), '0.01 GB');
  assert.equal(formatStorageGB(disk.total - disk.free), '1.00 GB');
  assert.deepEqual(disk, { total: 1004000000, free: 6000000 });
  for (const value of [
    '',
    '-1',
    'NaN',
    'Infinity',
    NaN,
    Infinity,
    -1,
    1.5,
    Number.MAX_SAFE_INTEGER + 1,
  ]) {
    assert.throws(() => formatStorageGB(value), RangeError);
  }
});
