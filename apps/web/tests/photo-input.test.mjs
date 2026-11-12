import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
test('photo source upload hints include only JPEG/PNG additions', async () => {
  const result = await build({
    entryPoints: ['src/video-file.ts'],
    bundle: true,
    write: false,
    platform: 'node',
    format: 'esm',
  });
  const { isOriginalFile } = await import(
    'data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text).toString('base64')
  );
  for (const name of ['new.JPG', 'new.jpeg', 'new.png']) {
    assert.equal(isOriginalFile({ name, type: '' }), true);
  }
  for (const name of ['new.gif', 'new.webp', 'new.tiff']) {
    assert.equal(isOriginalFile({ name, type: 'image/' + name.split('.').at(-1) }), false);
  }
});
