// Fully offline synthetic frozen-v1 wire fixtures; no provider or runtime access.
import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { chromium, expect } from '@playwright/test';
import { readFile, mkdir } from 'node:fs/promises';
import { join } from 'node:path';

const fixture = (role = 'transcription') => ({
  version: 1,
  supported: true,
  blocked_reason: null,
  job_id: 'job',
  run_id: 'run',
  task_id: 'task',
  role,
  job_revision: 3,
  recovery_revision: 0,
  context_sha256: 'a'.repeat(64),
  access: { can_manage: true },
  counts: { succeeded: 1, failed: 2, unattempted: 1, unknown: 0, active: 0, manual: 0, skipped: 0 },
  recovery: null,
  units: ['succeeded', 'failed', 'failed', 'unattempted'].map((status, index) => ({
    index,
    status,
    input_sha256: 'b'.repeat(64),
    error_code: status === 'failed' ? 'invalid_response' : null,
    source_ranges: [{ packed_start: 0, packed_end: 10, source_start: 120, source_end: 130 }],
    source_rows:
      role === 'translation'
        ? [{ id: 17, start: 120, end: 130, text: 'Original', speaker: 'A' }]
        : [],
    manual_schema: { duration_seconds: 10 },
    allowed_actions: index ? ['retry', 'skip', 'manual'] : [],
    attempts: [],
    provenance: { kind: index ? 'unresolved' : 'original' },
  })),
});
const setup = async (browser, role = 'transcription', manage = true, overrides = {}) => {
  const bundle = await build({
    stdin: {
      resolveDir: process.cwd(),
      loader: 'tsx',
      contents: `
    import React,{useState} from 'react';import{createRoot}from'react-dom/client';
    import{UnitRecoveryPanel}from'./src/UnitRecoveryPanel';
    window.__view=${JSON.stringify({ ...fixture(role), ...overrides })};window.__calls=[];window.__mode='ok';window.__changed=0;window.__preview={};
    function App(){const[run,setRun]=useState('run');const[show,setShow]=useState(true);window.__run=setRun;window.__show=setShow;
    return show?<UnitRecoveryPanel jobId="job" runId={run} canManage={${manage}} onChanged={()=>{window.__changed++}}/>:null}createRoot(document.getElementById('root')).render(<App/>);`,
    },
    bundle: true,
    write: false,
    outdir: 'offline',
    platform: 'browser',
    format: 'iife',
    plugins: [
      {
        name: 'offline',
        setup(p) {
          p.onResolve({ filter: /^\.\/api$/ }, () => ({ path: 'api', namespace: 'offline' }));
          p.onLoad({ filter: /.*/, namespace: 'offline' }, () => ({
            loader: 'js',
            contents: `
      export async function request(path,init={}){const body=init.body?JSON.parse(init.body):null;window.__calls.push({path,method:init.method||'GET',body});
      if(window.__mode==='defer'&&init.method==='POST')return new Promise(r=>window.__resolve=r);
      if(!init.method)return structuredClone(window.__view);
      if(path.endsWith('/preview')&&window.__mode==='preview-error')throw Error('invalid');
      if(path.endsWith('/preview'))return {...body,preview_sha256:'c'.repeat(64),ready:true,retained_units:[{index:0}],execution_units:[{index:1}],additional_call_limit:body.decisions.filter(d=>d.action==='retry').length,models:[{model_id:'frozen-model',revision:7}],warnings:[],blocked_reasons:[],...window.__preview};
      if(path.endsWith('/decisions')&&window.__mode==='lost-not-found')throw Error('unconfirmed');
      if(path.endsWith('/decisions')){window.__view.decisions=structuredClone(body.decisions);window.__view.recovery_revision++;window.__view.recovery={id:'rec',request_id:body.request_id,status:'approved',revision:window.__view.recovery_revision,additional_call_limit:body.decisions.filter(d=>d.action==='retry').length,executed_calls:0,can_continue:false};if(window.__mode==='lost')throw Error('lost response');}
      if(path.endsWith('/execute')){window.__view.recovery.executed_calls=window.__view.recovery.additional_call_limit;window.__view.recovery.can_continue=!window.__partial;if(window.__mode==='lost-execute')throw Error('lost execute');}
      if(path.endsWith('/continue')){if(window.__mode==='lost-continue')throw Error('lost continue');window.__view.recovery.status='applied';window.__view.recovery.can_continue=false;if(['lost-applied','dispatch-failed'].includes(window.__mode)){window.__view.blocked_reason='unit_recovery_root_not_held';throw Error(window.__mode==='dispatch-failed'?'downstream dispatch failed after adoption':'lost applied response');}}
      return structuredClone(window.__view);}`,
          }));
        },
      },
    ],
  });
  const context = await browser.newContext({
    offline: true,
    viewport: { width: 390, height: 844 },
  });
  await context.route('**/*', (r) => r.abort());
  const page = await context.newPage();
  await page.setContent('<html lang="ko"><body><div id="root"></div></body></html>');
  await page.clock.install();
  const css = process.env.UNIT_RECOVERY_BUILT_CSS
    ? await readFile(process.env.UNIT_RECOVERY_BUILT_CSS, 'utf8')
    : bundle.outputFiles.find((f) => f.path.endsWith('.css')).text;
  assert.ok(css.includes('unit-recovery'));
  await page.addStyleTag({ content: css });
  await page.addScriptTag({ content: bundle.outputFiles.find((f) => f.path.endsWith('.js')).text });
  return page;
};
test('lost save reconciles pending approval; only explicit resume uses the SAME request', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await setup(browser);
    await choices(page, 'transcription');
    await page.getByLabel('추가 호출 및 복구 결정을 승인합니다').check();
    await page.evaluate(() => (window.__mode = 'lost'));
    await page.getByRole('button', { name: '승인 후 저장·실행', exact: true }).click();
    const resume = page.getByRole('button', { name: '승인한 구간 실행', exact: true });
    await expect(resume).toBeEnabled();
    await page.clock.runFor(24000);
    assert.deepEqual(
      await page.evaluate(() =>
        window.__calls.filter((c) => c.method === 'POST').map((c) => c.path.split('/').at(-1)),
      ),
      ['preview', 'decisions'],
    );
    await resume.evaluate((el) => {
      el.click();
      el.click();
    });
    await expect(page.getByRole('button', { name: '후속 단계 계속', exact: true })).toBeEnabled();
    const posts = await page.evaluate(() => window.__calls.filter((c) => c.method === 'POST'));
    assert.deepEqual(
      posts.map((c) => c.path.split('/').at(-1)),
      ['preview', 'decisions', 'execute'],
    );
    assert.equal(posts[1].body.request_id, posts[2].body.request_id);
  } finally {
    await browser.close();
  }
});
test('MT finite selected retry permits unresolved later units, but never hard evidence blockers', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await setup(browser, 'translation');
    await page.evaluate(() => {
      window.__partial = true;
      window.__preview = { ready: false, blocked_reasons: ['unit:3:unresolved'] };
    });
    await page.getByLabel('구간 2 처리').selectOption('retry');
    await page.getByRole('button', { name: '복구 미리보기', exact: true }).click();
    await page.getByLabel('추가 호출 및 복구 결정을 승인합니다').check();
    await page.getByRole('button', { name: '승인 후 저장·실행', exact: true }).click();
    await expect(page.getByRole('button', { name: '후속 단계 계속', exact: true })).toBeDisabled();
    await expect
      .poll(() => page.evaluate(() => window.__calls.filter((c) => c.method === 'POST').length))
      .toBe(3);
    const posts = await page.evaluate(() => window.__calls.filter((c) => c.method === 'POST'));
    assert.deepEqual(
      posts.map((c) => c.path.split('/').at(-1)),
      ['preview', 'decisions', 'execute'],
    );
    assert.deepEqual(posts[1].body.decisions, [
      { unit_index: 1, action: 'retry', candidate_index: 0 },
    ]);
    for (const reason of [
      'unit:3:unknown',
      'unit:3:active',
      'invalid_evidence',
      'unit_recovery_empty_output_unsupported',
    ]) {
      await page.evaluate(
        (reason) => (window.__preview = { ready: false, blocked_reasons: [reason] }),
        reason,
      );
      await page.getByLabel('구간 3 처리').selectOption('skip');
      await page.getByRole('button', { name: '복구 미리보기', exact: true }).click();
      await expect(page.getByLabel('추가 호출 및 복구 결정을 승인합니다')).toBeDisabled();
    }
  } finally {
    await browser.close();
  }
});
test('ASR rows default to local duration, add/remove, text input only and no arbitrary IDs', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await setup(browser);
    await page.getByLabel('구간 2 처리').selectOption('manual');
    await expect(page.getByLabel('구간 2 행 1 시작')).toHaveValue('0');
    await expect(page.getByLabel('구간 2 행 1 종료')).toHaveValue('10');
    await expect(page.getByLabel('구간 2 행 1 텍스트')).toHaveValue('');
    await expect(page.locator('[data-unit="1"]')).toContainText('원본 시간: 120–130초');
    await page.getByRole('button', { name: '행 추가', exact: true }).click();
    await expect(page.getByLabel('구간 2 행 2 텍스트')).toBeVisible();
    await page.getByLabel('구간 2 행 2 삭제').click();
    await expect(page.getByLabel('구간 2 행 2 텍스트')).toHaveCount(0);
    await page.getByLabel('구간 2 행 1 텍스트').fill('직접 입력');
    await page.getByRole('button', { name: '복구 미리보기', exact: true }).click();
    await expect(page.getByText('추가 모델 호출 상한: 0', { exact: true })).toBeVisible();
    assert.deepEqual(
      await page.evaluate(
        () => window.__calls.find((c) => c.method === 'POST').body.decisions[0].value,
      ),
      [{ start: 0, end: 10, text: '직접 입력' }],
    );
  } finally {
    await browser.close();
  }
});
test('unconfirmed missing mutation stays held; unknown/sending evidence cannot resume', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await setup(browser);
    await choices(page, 'transcription');
    await page.getByLabel('추가 호출 및 복구 결정을 승인합니다').check();
    await page.evaluate(() => (window.__mode = 'lost-not-found'));
    await page.getByRole('button', { name: '승인 후 저장·실행', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('확정 증거');
    await expect(page.getByLabel('구간 2 처리')).toBeDisabled();
    for (const status of ['unknown', 'sending']) {
      await page.evaluate((status) => {
        const id = window.__calls.find((c) => c.path.endsWith('/decisions')).body.request_id;
        window.__view.recovery = {
          id: 'rec',
          request_id: id,
          status: 'approved',
          additional_call_limit: 1,
          executed_calls: 0,
          can_continue: false,
        };
        window.__view.units[1].attempts = [{ status }];
      }, status);
      await page.getByRole('button', { name: '상태 새로고침' }).click();
      await expect(
        page.getByRole('button', { name: '승인한 구간 실행', exact: true }),
      ).toBeDisabled();
    }
    await page.clock.runFor(120000);
    assert.deepEqual(
      await page.evaluate(() =>
        window.__calls.filter((c) => c.method === 'POST').map((c) => c.path.split('/').at(-1)),
      ),
      ['preview', 'decisions'],
    );
  } finally {
    await browser.close();
  }
});
test('preview error and cancelled/unmounted save never start execution', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await setup(browser);
    await page.getByLabel('구간 2 처리').selectOption('retry');
    await page.evaluate(() => (window.__mode = 'preview-error'));
    await page.getByRole('button', { name: '복구 미리보기', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('invalid');
    await page.clock.runFor(24000);
    assert.deepEqual(
      await page.evaluate(() =>
        window.__calls.filter((c) => c.method === 'POST').map((c) => c.path.split('/').at(-1)),
      ),
      ['preview'],
    );
    await page.evaluate(() => (window.__mode = 'ok'));
    await choices(page, 'transcription');
    await page.getByLabel('추가 호출 및 복구 결정을 승인합니다').check();
    await page.evaluate(() => (window.__mode = 'defer'));
    await page.getByRole('button', { name: '승인 후 저장·실행', exact: true }).click();
    await expect(page.getByLabel('구간 2 처리')).toBeDisabled();
    await page.evaluate(() => window.__show(false));
    await expect(page.locator('.unit-recovery')).toHaveCount(0);
    await page.evaluate(() => window.__resolve(window.__view));
    assert.deepEqual(
      await page.evaluate(() =>
        window.__calls.filter((c) => c.method === 'POST').map((c) => c.path.split('/').at(-1)),
      ),
      ['preview', 'preview', 'decisions'],
    );
  } finally {
    await browser.close();
  }
});
const choices = async (page, role) => {
  await page.getByLabel('구간 2 처리').selectOption('retry');
  await page.getByLabel('구간 3 처리').selectOption('skip');
  await page.getByLabel('구간 4 처리').selectOption('manual');
  if (role === 'translation') {
    await page.getByLabel('구간 4 행 17 번역').fill('Translated');
  } else {
    await page.getByLabel('구간 4 행 1 종료').fill('2');
    await page.getByLabel('구간 4 행 1 텍스트').fill('Manual');
  }
  await page.getByRole('button', { name: '복구 미리보기', exact: true }).click();
  await expect(page.getByText('추가 모델 호출 상한: 1', { exact: true })).toBeVisible();
};
for (const role of ['transcription', 'translation']) {
  test(`${role}: retain success, all actions, exact approval and separate continuation; responsive CSS`, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
      const page = await setup(browser, role);
      await expect(
        page.getByText('기존 성공 결과는 보존하며 다시 호출하지 않습니다.'),
      ).toBeVisible();
      await expect(page.getByLabel('구간 1 처리')).toHaveCount(0);
      await choices(page, role);
      await expect(page.getByText(/frozen-model/)).toBeVisible();
      if (role === 'transcription') {
        await expect(page.getByText(/청크 로컬 시계/).first()).toBeVisible();
      } else {
        await expect(page.locator('[data-unit="3"]')).toContainText('120');
        assert.equal(await page.locator('[data-unit="3"] input').count(), 0);
      }
      for (const width of [320, 390, 1280]) {
        await page.setViewportSize({ width, height: 844 });
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
        const captures = process.env.UNIT_RECOVERY_SCREENSHOTS;
        if (captures) {
          await mkdir(captures, { recursive: true });
          await page.screenshot({ path: join(captures, `${role}-${width}.png`), fullPage: true });
        }
      }
      await expect(
        page.getByRole('button', { name: '승인 후 저장·실행', exact: true }),
      ).toBeDisabled();
      await page.getByLabel('추가 호출 및 복구 결정을 승인합니다').check();
      await page.getByRole('button', { name: '승인 후 저장·실행', exact: true }).evaluate((el) => {
        el.click();
        el.click();
      });
      await expect(page.getByRole('button', { name: '후속 단계 계속', exact: true })).toBeEnabled();
      const calls = await page.evaluate(() => window.__calls.filter((c) => c.method === 'POST'));
      assert.deepEqual(
        calls.map((c) => c.path.split('/').at(-1)),
        ['preview', 'decisions', 'execute'],
      );
      assert.deepEqual(
        calls[1].body.decisions.map((d) => d.action),
        ['retry', 'skip', 'manual'],
      );
      assert.equal(calls[1].body.approve_calls, true);
      assert.equal(
        calls[1].body.decisions.some((d) => d.unit_index === 0),
        false,
      );
      if (role === 'translation') {
        assert.deepEqual(calls[1].body.decisions[2].value, [
          { id: 17, start: 120, end: 130, text: 'Translated', speaker: 'A' },
        ]);
      }
      await page.getByRole('button', { name: '후속 단계 계속', exact: true }).click();
      await expect
        .poll(() =>
          page.evaluate(() => window.__calls.filter((c) => c.path.endsWith('/continue')).length),
        )
        .toBe(1);
      await expect.poll(() => page.evaluate(() => window.__changed)).toBe(1);
    } finally {
      await browser.close();
    }
  });
}
test('lost save response: GET only, no replay on refresh/remount; cross-run completion fenced', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await setup(browser);
    await choices(page, 'transcription');
    await page.getByLabel('추가 호출 및 복구 결정을 승인합니다').check();
    await page.evaluate(() => (window.__mode = 'lost'));
    await page.getByRole('button', { name: '승인 후 저장·실행', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('GET으로');
    await page.getByRole('button', { name: '상태 새로고침' }).click();
    await page.evaluate(() => window.__show(false));
    await expect(page.locator('.unit-recovery')).toHaveCount(0);
    await page.evaluate(() => window.__show(true));
    await expect(page.locator('.unit-recovery')).toBeVisible();
    assert.deepEqual(
      await page.evaluate(() =>
        window.__calls.filter((c) => c.method === 'POST').map((c) => c.path.split('/').at(-1)),
      ),
      ['preview', 'decisions'],
    );
    await page.evaluate(() => (window.__view.recovery = null));
    await page.getByRole('button', { name: '상태 새로고침' }).click();
    await choices(page, 'transcription');
    await page.getByLabel('추가 호출 및 복구 결정을 승인합니다').check();
    await page.evaluate(() => (window.__mode = 'defer'));
    await page.getByRole('button', { name: '승인 후 저장·실행', exact: true }).click();
    await page.evaluate(() => window.__run('other'));
    await page.evaluate(() =>
      window.__resolve({
        ...window.__view,
        recovery: { id: 'old', request_id: 'old', status: 'approved' },
      }),
    );
    await expect(page.getByRole('alert')).toContainText('상태');
    assert.equal(
      await page.evaluate(() => window.__calls.some((c) => c.path.endsWith('/execute'))),
      false,
    );
  } finally {
    await browser.close();
  }
});
for (const mode of ['lost-execute', 'lost-continue']) {
  test(`${mode}: ambiguous mutations never replay, even on double clicks and refresh`, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
      const page = await setup(browser);
      await choices(page, 'transcription');
      await page.getByLabel('추가 호출 및 복구 결정을 승인합니다').check();
      await page.evaluate((m) => (window.__mode = m), mode);
      await page.getByRole('button', { name: '승인 후 저장·실행', exact: true }).click();
      if (mode === 'lost-continue') {
        await expect(
          page.getByRole('button', { name: '후속 단계 계속', exact: true }),
        ).toBeEnabled();
        await page.getByRole('button', { name: '후속 단계 계속', exact: true }).evaluate((el) => {
          el.click();
          el.click();
        });
      }
      await expect(page.getByRole('alert')).toContainText(
        mode === 'lost-execute' ? 'GET으로' : '결과 미확인',
      );
      await page.getByRole('button', { name: '상태 새로고침' }).click();
      const continuation = page.getByRole('button', { name: '후속 단계 계속', exact: true });
      if (mode === 'lost-execute') {
        await expect(continuation).toBeEnabled();
      } else {
        await expect(continuation).toBeDisabled();
      }
      const before = await page.evaluate(
        () => window.__calls.filter((c) => c.method === 'POST').length,
      );
      await page.clock.runFor(120000);
      assert.equal(
        await page.evaluate(() => window.__calls.filter((c) => c.method === 'POST').length),
        before,
      );
    } finally {
      await browser.close();
    }
  });
}
test('invalid ASR local timestamps never POST; dirty drafts invalidate approval', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await setup(browser);
    await page.getByLabel('구간 2 처리').selectOption('manual');
    await page.getByLabel('구간 2 행 1 시작').fill('120');
    await page.getByLabel('구간 2 행 1 종료').fill('130');
    await page.getByLabel('구간 2 행 1 텍스트').fill('wrong clock');
    await page.getByRole('button', { name: '복구 미리보기', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('시간 범위');
    assert.equal(await page.evaluate(() => window.__calls.some((c) => c.method === 'POST')), false);
    await choices(page, 'transcription');
    await page.getByLabel('추가 호출 및 복구 결정을 승인합니다').check();
    await page.getByLabel('구간 2 처리').selectOption('skip');
    await expect(page.getByRole('button', { name: '승인 후 저장·실행', exact: true })).toHaveCount(
      0,
    );
  } finally {
    await browser.close();
  }
});
test('partial retry keeps saved manual rows on remount and never reselects retained success', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await setup(browser, 'translation');
    await page.evaluate(() => {
      window.__partial = true;
      window.__preview = { ready: false, blocked_reasons: ['unit:3:unresolved'] };
    });
    await page.getByLabel('구간 2 처리').selectOption('retry');
    await page.getByLabel('구간 3 처리').selectOption('manual');
    await page.getByLabel('구간 3 행 17 번역').fill('saved manual remains');
    await page.getByRole('button', { name: '복구 미리보기', exact: true }).click();
    await page.getByLabel('추가 호출 및 복구 결정을 승인합니다').check();
    await page.getByRole('button', { name: '승인 후 저장·실행', exact: true }).click();
    await expect
      .poll(() => page.evaluate(() => window.__calls.filter((c) => c.method === 'POST').length))
      .toBe(3);
    await page.evaluate(() => {
      window.__view.units[1].status = 'succeeded';
      window.__view.units[1].allowed_actions = [];
      window.__view.units[1].provenance = { kind: 'model_retry' };
      window.__view.counts.succeeded = 2;
      window.__view.counts.failed = 1;
      window.__show(false);
    });
    await expect(page.locator('.unit-recovery')).toHaveCount(0);
    await page.evaluate(() => window.__show(true));
    await expect(page.getByLabel('구간 3 처리')).toHaveValue('manual');
    await expect(page.getByLabel('구간 3 행 17 번역')).toHaveValue('saved manual remains');
    await expect(page.getByLabel('구간 2 처리')).toHaveCount(0);
    await page.getByLabel('구간 4 처리').selectOption('skip');
    await page.evaluate(() => {
      window.__preview = {};
    });
    await page.getByRole('button', { name: '복구 미리보기', exact: true }).click();
    const preview = await page.evaluate(() =>
      window.__calls.filter((c) => c.path.endsWith('/preview')).at(-1),
    );
    assert.deepEqual(preview.body.decisions, [
      {
        unit_index: 2,
        action: 'manual',
        value: [{ id: 17, start: 120, end: 130, text: 'saved manual remains', speaker: 'A' }],
      },
      { unit_index: 3, action: 'skip' },
    ]);
    assert.equal(preview.body.recovery_revision, 1);
    assert.equal(
      await page.evaluate(() => window.__calls.filter((c) => c.path.endsWith('/execute')).length),
      1,
    );
  } finally {
    await browser.close();
  }
});

const savedFixture = (role, action = 'manual') => {
  const v = fixture(role);
  v.recovery_revision = 1;
  v.decisions = [
    {
      unit_index: 1,
      action,
      ...(action === 'manual'
        ? {
            value:
              role === 'translation'
                ? [{ ...v.units[1].source_rows[0], text: 'SAVED' }]
                : [{ start: 0, end: 10, text: 'SAVED' }],
          }
        : { candidate_index: 0 }),
    },
  ];
  v.recovery = {
    id: 'rec',
    request_id: 'saved-request',
    status: 'approved',
    revision: 1,
    additional_call_limit: action === 'retry' ? 1 : 0,
    executed_calls: 0,
    can_continue: action !== 'retry',
  };
  return v;
};
const posts = (page) => page.evaluate(() => window.__calls.filter((c) => c.method === 'POST'));
const reapprove = async (page) => {
  await page.getByRole('button', { name: '복구 미리보기', exact: true }).click();
  await page.getByLabel('추가 호출 및 복구 결정을 승인합니다').check();
  await page.getByRole('button', { name: '승인 후 저장·실행', exact: true }).click();
};
// Invoke captured React handlers in one JS turn, before a render can disable
// the old button. This exercises the synchronous fence, not just DOM disabled.
const editAndInvokeSaved = (page, action, text) =>
  page.evaluate(
    ({ action, text }) => {
      const props = (el) => el[Object.keys(el).find((k) => k.startsWith('__reactProps$'))];
      const button = [...document.querySelectorAll('button')].find(
        (el) => el.textContent.trim() === action,
      );
      const invoke = props(button).onClick;
      if (text) {
        props(document.querySelector('textarea')).onChange({ target: { value: text } });
      } else {
        props(document.querySelector('select')).onChange({ target: { value: 'skip' } });
      }
      invoke();
      invoke();
    },
    { action, text },
  );
for (const role of ['transcription', 'translation']) {
  test(`${role}: hydrated manual edits fence same-turn Continue; only fresh approval restores it`, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
      const page = await setup(browser, role, true, savedFixture(role));
      const continuation = page.getByRole('button', { name: '후속 단계 계속', exact: true });
      await expect(continuation).toBeEnabled();
      await editAndInvokeSaved(page, '후속 단계 계속', 'UNSAVED CORRECTION');
      await expect(continuation).toBeDisabled();
      await page.getByRole('button', { name: '상태 새로고침' }).click();
      await page.clock.runFor(24000);
      await expect(page.locator('textarea')).toHaveValue('UNSAVED CORRECTION');
      await expect(continuation).toBeDisabled();
      assert.deepEqual(await posts(page), []);
      await reapprove(page);
      await expect(continuation).toBeEnabled();
      const approvedPosts = await posts(page);
      assert.deepEqual(
        approvedPosts.map((c) => c.path.split('/').at(-1)),
        ['preview', 'decisions', 'execute'],
      );
      assert.equal(approvedPosts[1].body.decisions[0].value[0].text, 'UNSAVED CORRECTION');
      assert.notEqual(approvedPosts[1].body.request_id, 'saved-request');
      await continuation.click();
      const all = await posts(page);
      assert.equal(all.at(-1).body.request_id, approvedPosts[1].body.request_id);
    } finally {
      await browser.close();
    }
  });
}
for (const nextAction of ['skip', 'manual']) {
  test(`saved retry changed to ${nextAction} cannot resume old spend; reapproval uses new request`, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
      const page = await setup(
        browser,
        'transcription',
        true,
        savedFixture('transcription', 'retry'),
      );
      const resume = page.getByRole('button', { name: '승인한 구간 실행', exact: true });
      await expect(resume).toBeEnabled();
      await editAndInvokeSaved(page, '승인한 구간 실행');
      if (nextAction === 'manual') {
        await page.getByLabel('구간 2 처리').selectOption('manual');
        await page.getByLabel('구간 2 행 1 텍스트').fill('new manual');
      }
      await page.getByRole('button', { name: '상태 새로고침' }).click();
      await expect(resume).toBeDisabled();
      assert.deepEqual(await posts(page), []);
      // A lost save may release dirty only after GET confirms this exact new approval.
      await page.evaluate(() => (window.__mode = 'lost'));
      await reapprove(page);
      await expect(page.getByRole('alert')).toContainText('GET으로');
      assert.equal(
        await page.getByText('저장하지 않은 변경이 있습니다.', { exact: false }).count(),
        0,
      );
      const calls = await posts(page);
      assert.deepEqual(
        calls.map((c) => c.path.split('/').at(-1)),
        ['preview', 'decisions'],
      );
      assert.equal(calls[1].body.decisions[0].action, nextAction);
      assert.notEqual(calls[1].body.request_id, 'saved-request');
      await page.evaluate(() => window.__show(false));
      await expect(page.locator('.unit-recovery')).toHaveCount(0);
      await page.evaluate(() => window.__show(true));
      await expect(page.getByLabel('구간 2 처리')).toHaveValue(nextAction);
      assert.deepEqual(await posts(page), calls);
    } finally {
      await browser.close();
    }
  });
}
test('hydrated Continue action changes stay dirty through GET; remount only hydrates saved choices', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await setup(browser, 'translation', true, savedFixture('translation'));
    const continuation = page.getByRole('button', { name: '후속 단계 계속', exact: true });
    await expect(continuation).toBeEnabled();
    await page.getByLabel('구간 2 처리').selectOption('skip');
    await expect(continuation).toBeDisabled();
    await page.getByRole('button', { name: '상태 새로고침' }).click();
    await expect(page.getByLabel('구간 2 처리')).toHaveValue('skip');
    await expect(continuation).toBeDisabled();
    await page.evaluate(() => window.__show(false));
    await expect(page.locator('.unit-recovery')).toHaveCount(0);
    await page.evaluate(() => window.__show(true));
    await expect(page.locator('textarea')).toHaveValue('SAVED');
    await expect(continuation).toBeEnabled();
    assert.deepEqual(await posts(page), []);
  } finally {
    await browser.close();
  }
});
for (const mode of ['lost-applied', 'dispatch-failed']) {
  test(`${mode}: matching applied GET reconciles adoption despite root-not-held, never dispatch replay`, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
      const page = await setup(browser, 'transcription', true, savedFixture('transcription'));
      await page.evaluate((mode) => (window.__mode = mode), mode);
      await page.getByRole('button', { name: '후속 단계 계속', exact: true }).click();
      await expect.poll(() => page.evaluate(() => window.__changed)).toBe(1);
      await expect(page.getByRole('alert')).toContainText('채택을 확인');
      await expect(page.getByRole('alert')).toContainText('후속 단계 상태는 작업 상세');
      await expect(
        page.getByRole('button', { name: '후속 단계 계속', exact: true }),
      ).toBeDisabled();
      await page.getByRole('button', { name: '상태 새로고침' }).click();
      await page.clock.runFor(24000);
      assert.equal(await page.evaluate(() => window.__changed), 1);
      assert.deepEqual(
        (await posts(page)).map((c) => c.path.split('/').at(-1)),
        ['continue'],
      );
    } finally {
      await browser.close();
    }
  });
}
test('lost Continue remains held for missing/mismatched/non-applied/unknown/sending evidence', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await setup(browser, 'transcription', true, savedFixture('transcription'));
    await page.evaluate(() => (window.__mode = 'lost-continue'));
    await page.getByRole('button', { name: '후속 단계 계속', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('확정 증거');
    for (const evidence of ['missing', 'mismatch', 'approved', 'unknown', 'sending']) {
      await page.evaluate((evidence) => {
        window.__view.recovery =
          evidence === 'missing'
            ? null
            : {
                id: 'rec',
                request_id: evidence === 'mismatch' ? 'other' : 'saved-request',
                status: evidence === 'approved' ? 'approved' : 'applied',
                additional_call_limit: 0,
                executed_calls: 0,
                can_continue: false,
              };
        window.__view.blocked_reason = 'unit_recovery_root_not_held';
        window.__view.units[1].attempts = ['unknown', 'sending'].includes(evidence)
          ? [{ status: evidence }]
          : [];
      }, evidence);
      await page.getByRole('button', { name: '상태 새로고침' }).click();
      await expect(page.getByRole('alert')).toContainText('확정 증거');
      assert.equal(await page.evaluate(() => window.__changed), 0);
    }
    assert.deepEqual(
      (await posts(page)).map((c) => c.path.split('/').at(-1)),
      ['continue'],
    );
  } finally {
    await browser.close();
  }
});

test('fresh retry approval after dirty action changes executes only the new request', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await setup(browser, 'translation', true, savedFixture('translation', 'retry'));
    await page.getByLabel('구간 2 처리').selectOption('skip');
    await page.getByLabel('구간 2 처리').selectOption('retry');
    await expect(
      page.getByRole('button', { name: '승인한 구간 실행', exact: true }),
    ).toBeDisabled();
    await reapprove(page);
    await expect(page.getByRole('button', { name: '후속 단계 계속', exact: true })).toBeEnabled();
    const calls = await posts(page);
    assert.deepEqual(
      calls.map((c) => c.path.split('/').at(-1)),
      ['preview', 'decisions', 'execute'],
    );
    assert.notEqual(calls[1].body.request_id, 'saved-request');
    assert.equal(calls[2].body.request_id, calls[1].body.request_id);
    assert.equal(calls[1].body.decisions[0].action, 'retry');
  } finally {
    await browser.close();
  }
});
test('captured preview cannot approve pre-edit drafts; unmatched save GET never cleans edits', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await setup(browser, 'transcription', true, savedFixture('transcription'));
    await expect(page.locator('textarea')).toHaveValue('SAVED');
    await editAndInvokeSaved(page, '복구 미리보기', 'CORRECTION');
    assert.deepEqual(await posts(page), []);
    await page.evaluate(() => (window.__mode = 'lost-not-found'));
    await reapprove(page);
    await expect(page.getByRole('alert')).toContainText('확정 증거');
    await page.getByRole('button', { name: '상태 새로고침' }).click();
    await expect(page.locator('textarea')).toHaveValue('CORRECTION');
    await expect(page.getByText('저장하지 않은 변경이 있습니다.', { exact: false })).toBeVisible();
    await expect(page.getByRole('button', { name: '후속 단계 계속', exact: true })).toBeDisabled();
    assert.deepEqual(
      (await posts(page)).map((c) => c.path.split('/').at(-1)),
      ['preview', 'decisions'],
    );
  } finally {
    await browser.close();
  }
});
test('newer local edit during pending save is not cleaned by old matching approval or GET', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await setup(browser, 'transcription', true, savedFixture('transcription'));
    await page.locator('textarea').fill('FIRST CORRECTION');
    await page.getByRole('button', { name: '복구 미리보기', exact: true }).click();
    await page.getByLabel('추가 호출 및 복구 결정을 승인합니다').check();
    await page.evaluate(() => (window.__mode = 'defer'));
    await page.getByRole('button', { name: '승인 후 저장·실행', exact: true }).click();
    await expect(page.locator('textarea')).toBeDisabled();
    await page.evaluate(() => {
      const el = document.querySelector('textarea');
      el[Object.keys(el).find((k) => k.startsWith('__reactProps$'))].onChange({
        target: { value: 'NEWER CORRECTION' },
      });
      const body = window.__calls.find((c) => c.path.endsWith('/decisions')).body;
      window.__view.decisions = body.decisions;
      window.__view.recovery.request_id = body.request_id;
      window.__view.recovery_revision++;
      window.__resolve(structuredClone(window.__view));
    });
    await expect(page.locator('textarea')).toBeEnabled();
    await page.getByRole('button', { name: '상태 새로고침' }).click();
    await expect(page.locator('textarea')).toHaveValue('NEWER CORRECTION');
    await expect(page.getByRole('button', { name: '후속 단계 계속', exact: true })).toBeDisabled();
    assert.deepEqual(
      (await posts(page)).map((c) => c.path.split('/').at(-1)),
      ['preview', 'decisions'],
    );
  } finally {
    await browser.close();
  }
});

test('read-only, API access, unsupported and unknown gates; bounded polling', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const [manage, overrides] of [
      [false, {}],
      [true, { access: { can_manage: false } }],
      [true, { counts: { ...fixture().counts, unknown: 1 } }],
      [true, { blocked_reason: 'context_changed' }],
    ]) {
      const page = await setup(browser, 'translation', manage, overrides);
      await expect(page.locator('.unit-recovery')).toBeVisible();
      await expect(page.getByLabel('구간 2 처리')).toBeDisabled();
      await page.clock.runFor(120000);
      assert.ok((await page.evaluate(() => window.__calls.length)) <= 7);
      assert.equal(
        await page.evaluate(() => window.__calls.some((c) => c.method === 'POST')),
        false,
      );
      await page.close();
    }
    const page = await setup(browser, 'transcription', true, { supported: false });
    await expect(page.locator('.unit-recovery')).toHaveCount(0);
    assert.equal(await page.getByRole('button').count(), 0);
  } finally {
    await browser.close();
  }
});
