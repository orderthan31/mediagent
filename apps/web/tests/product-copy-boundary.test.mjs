import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';
test('job screens omit internal development/report descriptions',()=>{
 const detail=fs.readFileSync(new URL('../src/RenewalJobDetail.tsx',import.meta.url),'utf8');
 for(const text of ['티켓 고정 설정','검증된 완료 결과입니다.','bytes · SHA-256'])assert.ok(!detail.includes(text),text);
 const canvas=fs.readFileSync(new URL('../src/WorkflowCanvas.tsx',import.meta.url),'utf8');
 assert.ok(!canvas.includes('읽기 전용 · 화면 배치만 변경'));
});

test('controlled model outputs retain a concise truthful product label',()=>{const text=fs.readFileSync(new URL('../src/RenewalJobDetail.tsx',import.meta.url),'utf8');assert.ok(text.includes('통제 출력'));});

test('result drawer does not expose raw internal node options',()=>{const text=fs.readFileSync(new URL('../src/RenewalJobDetail.tsx',import.meta.url),'utf8');assert.ok(!text.includes('Object.entries(node.options)'));});
