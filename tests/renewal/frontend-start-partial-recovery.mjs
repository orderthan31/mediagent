// New start/partial boundaries; actual API, native workers and generated media, no MQ.
import assert from "node:assert/strict";
import { readFile, writeFile, mkdir, rename } from "node:fs/promises";
import { chromium } from "../../apps/web/node_modules/@playwright/test/index.mjs";
assert.equal(process.env.MIDEAGENT_CONTROL_DISPOSABLE, "1");
const c = JSON.parse(await readFile(process.env.MIDEAGENT_SP_CONFIG, "utf8"));
assert(c.origin.startsWith("http://127.0.0.1:"));
await mkdir(c.evidence, { recursive: true });
const b = await chromium.launch({ headless: true, channel: "msedge" }),
  x = await b.newContext({ viewport: { width: 1440, height: 1000 } }),
  p = await x.newPage();
p.setDefaultTimeout(18000);
const errors = [],
  checks = [],
  ledger = [];
p.on("pageerror", (e) => errors.push(e.message));
p.on("request", (r) => {
  if (r.method() === "POST" && r.url().endsWith("/recovery/decisions"))
    ledger.push(r.postDataJSON());
});
async function wait(fn, timeout = 40000) {
  let end = Date.now() + timeout;
  while (Date.now() < end) {
    const v = await fn();
    if (v) return v;
    await p.waitForTimeout(120);
  }
  throw Error("new boundary wait failed");
}
async function runtime(g) {
  const q = await x.request.get(c.origin + "/api/admin/agents/" + g);
  assert.equal(q.status(), 200);
  return q.json();
}
async function cmd(kind, group) {
  const id = crypto.randomUUID();
  await writeFile(
    c.private_root + "/next.json",
    JSON.stringify({ id, kind, group }),
  );
  await rename(c.private_root + "/next.json", c.private_root + "/command.json");
  await wait(async () => {
    try {
      return (
        JSON.parse(
          await readFile(c.private_root + "/command-result.json", "utf8"),
        ).id === id
      );
    } catch {
      return false;
    }
  });
}
async function jobs() {
  try {
    return JSON.parse(await readFile(c.private_root + "/jobs.json", "utf8"));
  } catch {
    return null;
  }
}
async function open(g, w = 1440) {
  await p.setViewportSize({ width: w, height: w === 390 ? 844 : 1000 });
  await p.goto(c.origin + "/#/agents/" + g);
  const q = p.getByRole("region", { name: "에이전트 복구 확인", exact: true });
  await q.waitFor();
  return q;
}
async function plan(q) {
  const [response] = await Promise.all([
    p.waitForResponse(
      (res) =>
        res.url().endsWith("/recovery/preview") &&
        res.request().method() === "POST",
    ),
    q.getByRole("button", { name: "최신 근거 확인", exact: true }).click(),
  ]);
  assert.equal(response.status(), 200);
  const body = await response.json();
  await wait(
    async () =>
      (await q.getByLabel("가능한 판단").locator("option").count()) ===
        body.allowed.length && (await q.getByLabel("가능한 판단").isEnabled()),
  );
  await q.getByLabel("가능한 판단").waitFor();
}
async function decide(q, choice, reason, outcome) {
  await q.getByLabel("가능한 판단").selectOption(choice);
  await q.getByLabel("복구 판단 사유").fill(reason);
  await q.getByRole("button", { name: "판단 접수", exact: true }).click();
  await q.locator("li strong").filter({ hasText: outcome }).first().waitFor();
}
async function shot(name, q) {
  assert.equal(
    await q.evaluate((el) =>
      [el, ...el.querySelectorAll("code,input,button,select,textarea")].some(
        (n) => {
          const b = n.getBoundingClientRect();
          return b.width > 0 && (b.left < 0 || b.right > innerWidth + 1);
        },
      ),
    ),
    false,
  );
  await p.screenshot({
    path: c.evidence + "/" + name + ".png",
    fullPage: true,
  });
}
let out = {
  passed: false,
  scope:
    "actual isolated native start/partial recovery with synthetic FFmpeg tasks; not MQ/product tickets or operating",
};
try {
  const login = await x.request.post(c.origin + "/api/auth/login", {
    data: c.admin,
  });
  assert.equal(login.status(), 200);
  const headers = {
    Origin: c.origin,
    "X-CSRF-Token": (await login.json()).csrf_token,
  };
  let q = await open("analyze");
  if (!(await runtime("analyze")).observed_replicas)
    await p.getByRole("button", { name: "시작", exact: true }).click();
  const started = await wait(async () => {
    const v = await runtime("analyze");
    return v.observed_replicas === 1 &&
      v.control.phase === "unknown" &&
      v.workers[0].state === "ready"
      ? v
      : null;
  });
  await plan(q);
  await q.getByText("실행 회차 시작", { exact: true }).waitFor();
  await shot("pc-start-generation", q);
  await cmd("hide_ack", "analyze");
  await wait(async () => {
    const z = await x.request.post(
      c.origin + "/api/admin/agents/analyze/recovery/preview",
      { data: {}, headers },
    );
    return z.status() === 200 && (await z.json()).allowed.length === 1;
  });
  await plan(q);
  assert.deepEqual(
    await q.getByLabel("가능한 판단").locator("option").allTextContents(),
    ["보류"],
  );
  await decide(
    q,
    "hold",
    "시작된 대상이 있어도 ACK 근거 없이는 원래 봉쇄를 유지함",
    "보류 · 원래 봉쇄 유지",
  );
  assert.equal((await runtime("analyze")).control.phase, "unknown");
  checks.push("running target alone cannot release missing start ACK");
  await cmd("restore_ack", "analyze");
  await wait(async () => {
    const z = await x.request.post(
      c.origin + "/api/admin/agents/analyze/recovery/preview",
      { data: {}, headers },
    );
    return (
      z.status() === 200 &&
      (await z.json()).allowed.includes("confirm_observed")
    );
  });
  await plan(q);
  await decide(
    q,
    "confirm_observed",
    "원 시작 요청과 서명 ACK의 실행 회차 및 현재 boot를 대조함",
    "관리자 관측 확정",
  );
  const startDone = await wait(async () => {
    const v = await runtime("analyze");
    return !v.control.phase ? v : null;
  });
  assert.equal(startDone.workers[0].boot_id, started.workers[0].boot_id);
  await p.setViewportSize({ width: 390, height: 844 });
  await shot("mobile-start-reviewed", q);
  checks.push("start gap recovered by admin/host/UI without repeat start");
  q = await open("extract_audio", 390);
  await p.getByRole("button", { name: "시작", exact: true }).click();
  const old = await wait(async () => {
    const v = await runtime("extract_audio");
    return v.control.phase === "unknown" && v.workers[0].state === "ready"
      ? v
      : null;
  });
  await cmd("new_boot", "extract_audio");
  const newer = await wait(async () => {
    const v = await runtime("extract_audio");
    return v.workers[0].boot_id &&
      v.workers[0].boot_id !== old.workers[0].boot_id &&
      v.workers[0].state === "ready"
      ? v
      : null;
  });
  await plan(q);
  assert.deepEqual(
    await q.getByLabel("가능한 판단").locator("option").allTextContents(),
    ["보류"],
  );
  await q.getByText("불일치 · 보류 필요", { exact: true }).waitFor();
  await decide(
    q,
    "hold",
    "같은 고정 대상이라도 ACK 실행 회차와 현재 boot가 달라 봉쇄함",
    "보류 · 원래 봉쇄 유지",
  );
  await shot("mobile-start-generation-mismatch", q);
  checks.push("different execution generation remains blocked");
  q = await open("encode");
  await cmd("initial_jobs");
  await wait(async () => {
    const v = await runtime("encode");
    return v.workers.every((w) => w.state === "busy");
  });
  const before = await runtime("encode");
  const ids = c.cases.encode.workers.map((w) => w.worker_id);
  await p.getByLabel("실행 개수", { exact: true }).fill("1");
  await p.getByRole("button", { name: "개수 적용", exact: true }).click();
  const draining = await wait(async () => {
    const v = await runtime("encode");
    return v.control.phase === "unknown" &&
      v.workers.some((w) => w.worker_id === ids[1] && w.state === "stopping")
      ? v
      : null;
  });
  await cmd("followup_jobs");
  const pauseAt = Date.now();
  await cmd("pause");
  const during = await wait(async () => {
    const j = await jobs();
    return j &&
      j.jobs.find((v) => v.id === j.ids.keep_next)?.state === "completed"
      ? j
      : null;
  });
  assert(during.host_paused);
  const keptNext = during.jobs.find((v) => v.id === during.ids.keep_next);
  assert(Date.parse(keptNext.completed_at) > pauseAt);
  assert.equal(
    during.jobs.find((v) => v.id === during.ids.removed_next).state,
    "queued",
  );
  assert.equal(keptNext.worker_id, ids[0]);
  assert.equal(
    keptNext.worker_boot,
    before.workers.find((w) => w.worker_id === ids[0]).boot_id,
  );
  checks.push(
    "survivor completes subsequent work while host is paused; removed followup stays queued",
  );
  await cmd("resume");
  await wait(async () => {
    const v = await runtime("encode");
    return (
      v.observed_replicas === 1 &&
      v.workers.find((w) => w.worker_id === ids[1]).state === "stopped"
    );
  });
  await plan(q);
  await q.getByText("유지 대상 · 제어 신호 없음", { exact: true }).waitFor();
  await shot("pc-partial-only-removed-stopped", q);
  await decide(
    q,
    "confirm_observed",
    "중지 대상 작업 완료와 정상 종료, 유지 대상 동일 boot의 계속 처리를 대조함",
    "관리자 관측 확정",
  );
  const final = await wait(async () => {
    const v = await runtime("encode");
    return !v.control.phase ? v : null;
  });
  assert.equal(final.observed_replicas, 1);
  assert.equal(
    final.workers.find((w) => w.worker_id === ids[0]).boot_id,
    before.workers.find((w) => w.worker_id === ids[0]).boot_id,
  );
  await p.setViewportSize({ width: 390, height: 844 });
  await shot("mobile-partial-reviewed", q);
  checks.push(
    "partial shrink admin/host/UI preserves survivor and original action",
  );
  const completed = await jobs();
  assert.equal(completed.jobs.filter((v) => v.state === "completed").length, 3);
  assert.equal(
    completed.jobs.find((v) => v.id === completed.ids.removed_next).claim_count,
    0,
  );
  assert(
    completed.jobs
      .filter((v) => v.state === "completed")
      .every((v) => v.claim_count === 1 && v.bytes > 0 && v.sha256),
  );
  const duplicate = await x.request.put(
    c.origin + "/api/admin/agents/extract_audio/configuration",
    {
      data: {
        revision: newer.revision,
        enabled: true,
        replicas: 1,
        request_id: crypto.randomUUID().replaceAll("-", ""),
      },
      headers,
    },
  );
  assert.equal(duplicate.status(), 409);
  assert.deepEqual(errors, []);
  out = {
    ...out,
    passed: true,
    checks,
    started,
    startDone,
    changedStart: { before: old, after: newer },
    partial: {
      before,
      draining,
      host_pause_requested_at: pauseAt,
      during_host_pause: during,
      final,
      jobs: completed,
    },
    ledger,
    errors,
  };
} catch (error) {
  out = { ...out, checks, ledger, errors, error: String(error) };
  await p.screenshot({ path: c.evidence + "/failure.png", fullPage: true });
  await writeFile(
    c.evidence + "/failure.txt",
    await p.locator("body").innerText(),
  );
  throw error;
} finally {
  await writeFile(c.evidence + "/result.json", JSON.stringify(out, null, 2));
  await x.close();
  await b.close();
}
console.log(
  JSON.stringify({ passed: out.passed, new_boundaries: checks.length }),
);
