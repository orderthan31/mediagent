import test from 'node:test';import assert from 'node:assert/strict';import{readFileSync}from 'node:fs';
const source=n=>readFileSync(new URL('../src/'+n,import.meta.url),'utf8');
test('provider completion rereads collection rather than nonexistent detail GET',()=>{const s=source('ProviderConnections.tsx');assert.match(s,/connectionsEndpoint\);/);assert.match(s,/await onSaved\(current\)/);assert.doesNotMatch(s,/request<ServingConnection>\(connectionsEndpoint \+ '\/' \+ id\)/)});
test('inline registration never has to navigate away from the node',()=>{const s=source('NodeModelBinding.tsx');assert.match(s,/createPortal/);assert.match(s,/onRegistered/);assert.match(s,/supportsModelRole\(current, role\)/);assert.match(s,/modelRegistration/);assert.match(s,/type="search"/);assert.doesNotMatch(s,/localStorage|sessionStorage/)});
test('touch gestures are captured before node and wire handlers',()=>{const s=source('WorkflowCanvas.tsx');assert.match(s,/onPointerDownCapture=\{captureTouch\}/);assert.match(s,/onPointerMoveCapture=\{moveTouch\}/);assert.doesNotMatch(s,/panel\.scrollIntoView/);assert.match(s,/window\.history\.state\?\.workflowPanel/)});

test('portalled model form retains the existing design-system theme boundary',()=>{assert.match(source('NodeModelBinding.tsx'),/registration-backdrop[\s\S]*?data-hangyeol/)});
