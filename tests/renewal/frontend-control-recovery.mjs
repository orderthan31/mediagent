// Actual isolated API; interception delays or drops genuine responses only.
import assert from "node:assert/strict";
import { readFile, writeFile, mkdir, rename } from "node:fs/promises";
import { join } from "node:path";
import { chromium } from "../../apps/web/node_modules/@playwright/test/index.mjs";
assert.equal(process.env.MIDEAGENT_CONTROL_DISPOSABLE, "1");
const cfg = JSON.parse(
  await readFile(process.env.MIDEAGENT_REVIEW_UI_CONFIG, "utf8"),
);
assert(cfg.origin.startsWith("http://127.0.0.1:"));
await mkdir(cfg.evidence, { recursive: true });
const browser = await chromium.launch({ headless: true, channel: "msedge" }),
  ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } }),
  page = await ctx.newPage();
page.setDefaultTimeout(15000);
const checks = [],
  ledger = [],
  errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("request", (r) => {
  if (r.method() === "POST" && r.url().endsWith("/recovery/decisions"))
    ledger.push(r.postDataJSON());
});
const ep = (g) => cfg.origin + "/api/admin/agents/" + g + "/recovery";
let csrf;
const headers = () => ({ Origin: cfg.origin, "X-CSRF-Token": csrf });
async function wait(fn) {
  const end = Date.now() + 30000;
  while (Date.now() < end) {
    if (await fn()) return;
    await new Promise((r) => setTimeout(r, 120));
  }
  throw Error("fixture wait timed out");
}
async function cmd(kind) {
  const id = crypto.randomUUID();
  await writeFile(
    join(cfg.private_root, "next.json"),
    JSON.stringify({ id, kind }),
  );
  await rename(
    join(cfg.private_root, "next.json"),
    join(cfg.private_root, "command.json"),
  );
  await wait(async () => {
    try {
      return (
        JSON.parse(
          await readFile(join(cfg.private_root, "command-result.json"), "utf8"),
        ).id === id
      );
    } catch {
      return false;
    }
  });
}
async function state(g) {
  return (await ctx.request.get(ep(g))).json();
}
async function open(g, w = 1440) {
  await page.setViewportSize({ width: w, height: w === 390 ? 844 : 1000 });
  await page.goto(cfg.origin + "/#/agents/" + g);
  const p = page.getByRole("region", {
    name: "에이전트 복구 확인",
    exact: true,
  });
  await p.waitFor();
  return p;
}
async function preview(p) {
  await p.getByRole("button", { name: "최신 근거 확인", exact: true }).click();
  await p.getByLabel("복구 판단 사유").waitFor();
  await p.getByLabel("가능한 판단").isEnabled();
}
async function shot(name, p) {
  assert.equal(
    await p.evaluate((el) =>
      [el, ...el.querySelectorAll("code,input,textarea,button,select")].some(
        (n) => {
          const b = n.getBoundingClientRect();
          return b.width > 0 && (b.left < 0 || b.right > innerWidth + 1);
        },
      ),
    ),
    false,
  );
  await page.screenshot({
    path: join(cfg.evidence, name + ".png"),
    fullPage: true,
  });
}
const button = (p) => p.getByRole("button", { name: "판단 접수", exact: true });
let report = {
  passed: false,
  scope:
    "actual API/PG and native-fault setup, PC/390px; not MQ/tickets/start/partial-scale acceptance",
};
try {
  const login = await ctx.request.post(cfg.origin + "/api/auth/login", {
    data: cfg.admin,
  });
  assert.equal(login.status(), 200);
  csrf = (await login.json()).csrf_token;
  let p = await open("analyze");
  await preview(p);
  for (const value of [
    cfg.cases.analyze.request_id,
    cfg.cases.analyze.worker_id,
    cfg.cases.analyze.target_id,
  ])
    assert(await p.getByText(value, { exact: true }).count());
  assert(await button(p).isDisabled());
  assert.equal(await p.getByLabel("가능한 판단").locator("option").count(), 2);
  await shot("pc-evidence", p);
  checks.push("bound original request/target and only eligible choices");
  p = await open("validate_video", 390);
  await preview(p);
  assert.deepEqual(
    await p.getByLabel("가능한 판단").locator("option").allTextContents(),
    ["보류"],
  );
  await p
    .getByLabel("복구 판단 사유")
    .fill("모바일에서 근거 부족을 확인하고 원래 봉쇄를 유지함");
  await button(p).click();
  await p
    .locator("li strong")
    .filter({ hasText: "보류 · 원래 봉쇄 유지" })
    .first()
    .waitFor();
  await shot("mobile-held", p);
  checks.push("mobile hold admission and host history");
  // Delay status reads so a real concurrent admission reaches server CAS first.
  await preview(p);
  await p
    .getByLabel("복구 판단 사유")
    .fill("다른 세션 판단과 충돌하면 최신 근거를 다시 확인해야 함");
  let gate = true;
  const pending = [];
  const match = "**/api/admin/agents/validate_video/recovery";
  await page.route(match, async (r) => {
    if (gate) pending.push(r);
    else await r.continue();
  });
  await cmd("pause");
  const plan = await ctx.request.post(ep("validate_video") + "/preview", {
    data: {},
    headers: headers(),
  });
  assert.equal(plan.status(), 200);
  assert.equal(
    (
      await ctx.request.post(ep("validate_video") + "/decisions", {
        data: {
          plan_id: (await plan.json()).id,
          decision_id: crypto.randomUUID().replaceAll("-", ""),
          choice: "hold",
          reason: "다른 세션의 선행 보류 판단",
        },
        headers: headers(),
      })
    ).status(),
    200,
  );
  await button(p).click();
  await p
    .getByText(
      "근거나 다른 판단이 변경됐습니다. 최신 근거를 다시 확인하세요.",
      { exact: true },
    )
    .waitFor();
  assert(await button(p).isDisabled());
  gate = false;
  await Promise.all(pending.map((r) => r.continue()));
  await page.unroute(match);
  await cmd("resume");
  await wait(async () => !(await state("validate_video")).pending_decision);
  await shot("mobile-concurrent-conflict", p);
  checks.push("concurrent judgment requires new confirmation");
  // A changed real worker observation invalidates an open plan without resubmit.
  await preview(p);
  await cmd("stop_validate");
  await p
    .getByText("이전 근거는 사용할 수 없습니다. 최신 근거를 다시 확인하세요.", {
      exact: true,
    })
    .waitFor();
  assert(await button(p).isDisabled());
  await shot("mobile-observation-stale", p);
  checks.push("actual observation change invalidates plan");
  p = await open("analyze");
  await preview(p);
  await p.getByLabel("가능한 판단").selectOption("confirm_observed");
  await p
    .getByLabel("복구 판단 사유")
    .fill("같은 원 요청과 boot의 ACK 근거 및 정상 종료를 대조함");
  await cmd("pause");
  await button(p).click();
  await p
    .locator("li strong")
    .filter({ hasText: "접수됨 · 호스트 재검증 대기" })
    .first()
    .waitFor();
  assert.equal(
    await p
      .locator("li strong")
      .filter({ hasText: "관리자 관측 확정" })
      .count(),
    0,
  );
  await shot("pc-admitted-pending", p);
  await page.setViewportSize({ width: 390, height: 844 });
  await shot("mobile-admitted-pending", p);
  await cmd("tamper_ack");
  await cmd("resume");
  await p
    .locator("li strong")
    .filter({ hasText: "근거 변경 · 새 확인 필요" })
    .first()
    .waitFor();
  await shot("mobile-host-rejected", p);
  checks.push("admission is not completion, host rejection shown");
  await cmd("restore_ack");
  await wait(async () => {
    const q = await ctx.request.post(ep("analyze") + "/preview", {
      data: {},
      headers: headers(),
    });
    return (
      q.status() === 200 &&
      (await q.json()).allowed.includes("confirm_observed")
    );
  });
  await preview(p);
  await p.getByLabel("가능한 판단").selectOption("confirm_observed");
  await p
    .getByLabel("복구 판단 사유")
    .fill("근거를 다시 검증한 후 원 요청 정상 종료를 관측 확정함");
  await page.route(
    "**/api/admin/agents/analyze/recovery/decisions",
    async (r) => {
      await r.fetch();
      await p
        .locator("li strong")
        .filter({ hasText: "관리자 관측 확정" })
        .first()
        .waitFor();
      await r.abort("failed");
    },
  );
  await button(p).click();
  await p
    .locator("li strong")
    .filter({ hasText: "관리자 관측 확정" })
    .first()
    .waitFor();
  await page.waitForTimeout(1800);
  assert.equal(
    await p
      .getByText(
        "접수 결과 확인 불가 · 새 판단을 보내지 않고 이력을 조회합니다.",
        { exact: true },
      )
      .count(),
    0,
  );
  await page.unroute("**/api/admin/agents/analyze/recovery/decisions");
  await shot("mobile-observed", p);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await shot("pc-observed", p);
  checks.push(
    "lost POST response cannot replace observed result or duplicate POST",
  );
  p = await open("encode", 390);
  await preview(p);
  assert.deepEqual(
    await p.getByLabel("가능한 판단").locator("option").allTextContents(),
    ["보류", "실패 확인 · 격리"],
  );
  await p.getByLabel("가능한 판단").selectOption("quarantine_failed");
  await p
    .getByLabel("복구 판단 사유")
    .fill("종료 코드 7을 확인하여 실패와 격리를 유지함");
  await button(p).click();
  await p
    .locator("li strong")
    .filter({ hasText: "실패 확인 · 격리 유지" })
    .first()
    .waitFor();
  await shot("mobile-quarantined", p);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await shot("pc-quarantined", p);
  assert(
    await page.getByRole("button", { name: "시작", exact: true }).isDisabled(),
  );
  checks.push("failed quarantine without release or reactivation");
  const counts = {};
  for (const v of ledger)
    counts[v.decision_id] = (counts[v.decision_id] || 0) + 1;
  assert(Object.values(counts).every((n) => n === 1));
  assert.deepEqual(errors, []);
  report = {
    ...report,
    passed: true,
    checks,
    ledger,
    errors,
    final: {
      analyze: await state("analyze"),
      hold: await state("validate_video"),
      failed: await state("encode"),
    },
  };
} catch (error) {
  report = { ...report, checks, ledger, errors, error: String(error) };
  await page.screenshot({
    path: join(cfg.evidence, "failure.png"),
    fullPage: true,
  });
  await writeFile(
    join(cfg.evidence, "failure.txt"),
    await page.locator("body").innerText(),
  );
  throw error;
} finally {
  await writeFile(
    join(cfg.evidence, "result.json"),
    JSON.stringify(report, null, 2),
  );
  await ctx.close();
  await browser.close();
}
console.log(JSON.stringify({ passed: report.passed, checks: checks.length }));
