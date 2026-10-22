import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { test } from 'node:test';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { buildSync } from 'esbuild';

// Render the real component; no business API or runtime response is fabricated.
test('preserved originals disclose unknown uploader and bounded excerpt', () => {
  const code = `
    import React from 'react';
    import {renderToStaticMarkup} from 'react-dom/server';
    import {StorageVideoInfo,StorageAssetRow} from './src/StorageVideo';
    import assert from 'node:assert/strict';
    const video={asset_id:'a'.repeat(32),original_filename:'preserved.mp4',uploaded_by:null,
      size_bytes:340261063,created_at:'2026-10-21T00:00:00Z',media:{duration:1000,width:1280,height:720,has_audio:true},
      provenance:{kind:'preserved_legacy'},web_preview:{status:'ready',excerpt_seconds:30}};
    const html=renderToStaticMarkup(<><StorageAssetRow video={video} thumbnail={null}/><StorageVideoInfo video={video} assetId={video.asset_id}/></>);
    assert.ok(html.includes('보존 이관 원본'));
    assert.ok(html.includes('기록 없음'));
    assert.ok(html.includes('앞부분 30초'));
    assert.ok(!html.includes('파일 업로드'));
  `;
  const compiled = buildSync({
    stdin: { contents: code, resolveDir: process.cwd(), loader: 'tsx' },
    bundle: true,
    platform: 'node',
    format: 'cjs',
    write: false,
    define: { 'import.meta.env': '{}' },
    loader: { '.css': 'empty' },
  });
  const dir = mkdtempSync(
    join(process.env.MIDEAGENT_TEST_SCRATCH || process.env.TMPDIR, 'preserved-view-'),
  );
  try {
    const file = join(dir, 'render.cjs');
    writeFileSync(file, compiled.outputFiles[0].text);
    const result = spawnSync(process.execPath, [file], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr || String(result.error || 'render failed'));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
