import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = (name) => readFile(new URL(`../src/${name}`, import.meta.url), 'utf8');

test('new operator panels consume Hangyeol buttons, not legacy native actions', async () => {
  for (const name of ['FaceSwapDialog.tsx', 'QueuePanel.tsx', 'StorageSettings.tsx']) {
    const text = await source(name);
    assert.match(text, /import \{ Button \} from '.\/hangyeol\/primitives\/button'/, name);
    assert.doesNotMatch(text, /<button\b/, name);
  }
});

test('integrated settings retain secret guidance and expose bounded STT providers', async () => {
  const text = await source('SettingsPage.tsx');
  assert.match(text, /transcription_fallback_provider/);
  assert.match(text, /sttModels\[provider as SttProvider\]/);
  assert.match(text, /일반 설정과 삭제 예정은 실패 시 유지/);
  assert.doesNotMatch(text, /현재 전사는 Gemini를 사용합니다/);
});

test('workflow confirmation and feature queue hooks coexist in the renewal shell', async () => {
  const workflow = await source('WorkflowDialog.tsx');
  const workspace = await source('VideoWorkspace.tsx');
  assert.match(workflow, /approval\.current !== confirmationKey/);
  assert.match(workflow, /request_id: key\.current/);
  assert.match(workspace, /hasConfirmedList/);
  assert.match(workspace, /<StorageUploads/);
  assert.match(workspace, /<FaceSwapDialog/);
  assert.match(workspace, /<QueuePanel/);
});
