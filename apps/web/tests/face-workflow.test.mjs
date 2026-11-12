// SOURCE-only eligibility, production helpers; no API or native calls.
import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
const bundle = await build({
  stdin: {
    contents: "export {normalInputReady} from './src/normal-inputs'",
    resolveDir: process.cwd(),
    loader: 'ts',
  },
  bundle: true,
  write: false,
  platform: 'node',
  format: 'esm',
});
const { normalInputReady } = await import(
  'data:text/javascript;base64,' + Buffer.from(bundle.outputFiles[0].text).toString('base64')
);
test('face preparation requires a photo, actual engine pin and reference frame', () => {
  const definition = {
    catalog_version: 2,
    input_profile: 'face_workflow_v1',
    inputs: { photo: 'image' },
  };
  assert.equal(normalInputReady(definition, {}), false);
  const input = {
    face_input: {
      photo_asset_id: 'a'.repeat(32),
      engine_revision: 2,
      engine_sha256: 'b'.repeat(64),
      settings_revision: 1,
      reference_frame: 1,
    },
  };
  assert.equal(normalInputReady(definition, input), true);
  assert.equal(
    normalInputReady(definition, { face_input: { ...input.face_input, engine_revision: null } }),
    false,
  );
  assert.equal(
    normalInputReady(definition, { face_input: { ...input.face_input, reference_frame: 0 } }),
    false,
  );
});
