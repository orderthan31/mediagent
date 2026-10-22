import assert from "node:assert/strict";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import { chromium } from "../../apps/web/node_modules/@playwright/test/index.mjs";
assert.equal(process.env.MIDEAGENT_TEST_DISPOSABLE, "1");
const c = JSON.parse(
  await readFile(process.env.JOB_REVIEW_BROWSER_CONFIG, "utf8"),
);
assert(c.origin.startsWith("http://127.0.0.1:"));
const out = process.env.JOB_REVIEW_EVIDENCE;
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ channel: "msedge", headless: true });
const context = await browser.newContext({
  viewport: { width: 1365, height: 1000 },
});
const page = await context.newPage();
page.setDefaultTimeout(20000);
const errors = [],
  checks = [],
  posts = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("request", (r) => {
  if (r.method() === "POST" && r.url().endsWith("/processing-review/decisions"))
    posts.push(r.postDataJSON());
});
const auth = await context.request.post(c.origin + "/api/auth/login", {
  headers: { Origin: c.origin },
  data: { username: c.username, password: c.password },
});
assert.equal(auth.status(), 200);
const control = (action, data = {}) =>
  context.request.post(c.origin + "/__fixture/" + action, {
    headers: { "X-Fixture-Control": c.control },
    data,
  });
async function open(name, width = 1365) {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
  await page.goto(c.origin + "/#/jobs/" + c.jobs[name]);
  const q = page.getByRole("region", { name: "작업 처리 확인", exact: true });
  await q.getByText("원 요청 해시", { exact: true }).waitFor();
  return q;
}
async function preview(q) {
  const [r] = await Promise.all([
    page.waitForResponse(
      (r) =>
        r.url().endsWith("/processing-review/preview") &&
        r.request().method() === "POST",
    ),
    q.getByRole("button", { name: "현재 근거 확인", exact: true }).click(),
  ]);
  assert.equal(r.status(), 200);
  return r.json();
}
try {
  let q = await open("hold");
  assert.equal(
    await page.locator(".job-detail-toolbar [role=status]").innerText(),
    "처리 여부 확인 필요",
  );
  let plan = await preview(q);
  assert.equal(plan.can_create_child, false);
  assert(
    await q.getByRole("button", { name: "새 복구 작업 준비" }).isDisabled(),
  );
  await q
    .getByRole("textbox", { name: "판단 사유" })
    .fill("수신·종료 근거가 부족하여 보류");
  await q.getByRole("button", { name: "보류 판단 저장", exact: true }).click();
  await q.getByText("관리자 확인 보류", { exact: true }).waitFor();
  await page.screenshot({ path: out + "/pc-held.png", fullPage: true });
  checks.push(
    "real API hold with unchanged raw running source and durable history",
  );
  q = await open("hold", 390);
  await q.getByText("관리자 확인 보류", { exact: true }).waitFor();
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  );
  assert.equal(
    await q
      .locator(".processing-risk")
      .evaluate((e) => getComputedStyle(e).flexDirection),
    "row",
  );
  assert(
    await q.locator("code,textarea,button").evaluateAll((els) =>
      els
        .filter((e) => e.getClientRects().length)
        .every((e) => {
          const r = e.getBoundingClientRect();
          return r.left >= 0 && r.right <= innerWidth + 1;
        }),
    ),
  );
  await page.screenshot({ path: out + "/mobile-held.png", fullPage: true });
  checks.push("390px persistent history and identifier/form bounds");
  q = await open("stale");
  await preview(q);
  await control("late", { case: "stale" });
  await q
    .getByRole("textbox", { name: "판단 사유" })
    .fill("오래된 관측으로 제출");
  const [stale] = await Promise.all([
    page.waitForResponse((r) =>
      r.url().endsWith("/processing-review/decisions"),
    ),
    q.getByRole("button", { name: "보류 판단 저장", exact: true }).click(),
  ]);
  assert.equal(stale.status(), 409);
  await q.getByRole("alert").waitFor();
  await page.screenshot({ path: out + "/stale-409.png", fullPage: true });
  checks.push(
    "changed receipt rejects old plan 409 without recording a judgment",
  );
  let releaseOld, oldCaptured;
  const captured = new Promise((r) => (oldCaptured = r)),
    release = new Promise((r) => (releaseOld = r));
  let reads = 0;
  const staleURL = "**/api/admin/jobs/" + c.jobs.stale + "/processing-review";
  await page.route(staleURL, async (route) => {
    if (++reads === 1) {
      await route.fetch();
      oldCaptured();
      await release;
      await route.abort("failed");
    } else await route.continue();
  });
  await q
    .getByRole("button", { name: "판단 원장 새로고침", exact: true })
    .click();
  await captured;
  const newer = page.waitForResponse(
    (r) =>
      r.url().endsWith("/jobs/" + c.jobs.stale + "/processing-review") &&
      r.status() === 200,
  );
  await q
    .getByRole("button", { name: "판단 원장 새로고침", exact: true })
    .click();
  await (await newer).finished();
  const oldFailed = page.waitForEvent("requestfailed", (r) =>
    r.url().endsWith("/jobs/" + c.jobs.stale + "/processing-review"),
  );
  releaseOld();
  await oldFailed;
  await page.evaluate(
    () =>
      new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))),
  );
  assert.equal(await q.getByRole("alert").count(), 0);
  await page.unroute(staleURL);
  checks.push("older failed read does not overwrite newer confirmed state");
  q = await open("recover");
  plan = await preview(q);
  assert.equal(plan.can_create_child, true);
  await q
    .getByRole("textbox", { name: "판단 사유" })
    .fill("원 종료 결과와 격리 파일을 확인했고 별도 승인으로 복구");
  await q.getByRole("checkbox").check();
  let dropped = 0;
  await page.route(
    "**/api/admin/jobs/" + c.jobs.recover + "/processing-review/decisions",
    async (route) => {
      const response = await route.fetch();
      assert.equal(response.status(), 200);
      dropped++;
      await route.abort("failed");
    },
  );
  await q
    .getByRole("button", { name: "새 복구 작업 준비", exact: true })
    .click();
  await q.getByRole("link", { name: "새 작업 열기", exact: true }).waitFor();
  assert.equal(dropped, 1);
  await page.unroute(
    "**/api/admin/jobs/" + c.jobs.recover + "/processing-review/decisions",
  );
  const fixed = await (
    await context.request.get(
      c.origin + "/api/admin/jobs/" + c.jobs.recover + "/processing-review",
    )
  ).json();
  assert.equal(fixed.history[0].authority_snapshot.role, "admin");
  assert.equal(fixed.history[0].acknowledge_duplicate_risk, true);
  assert.equal(
    fixed.history[0].plan_context.policy,
    "encode-terminal-receipt-v1",
  );
  const frozenDetails = q.getByText("판단 시점의 고정 근거", { exact: true });
  await frozenDetails.click();
  assert(
    (await frozenDetails.locator("..").innerText()).includes(
      "encode-terminal-receipt-v1",
    ),
  );
  await frozenDetails.click();
  const href = await q
    .getByRole("link", { name: "새 작업 열기", exact: true })
    .getAttribute("href");
  const child = href.split("/").at(-1);
  const draft = await (
    await context.request.get(c.origin + "/api/renewal/jobs/" + child)
  ).json();
  assert.equal(draft.status, "draft");
  assert.equal(draft.active_claim_id, null);
  await page.screenshot({
    path: out + "/child-after-lost-response.png",
    fullPage: true,
  });
  checks.push(
    "lost successful POST reply reconciles by real GET with one child",
  );
  await q.getByRole("link", { name: "새 작업 열기", exact: true }).click();
  await page
    .getByRole("button", { name: "실행 계획 확인", exact: true })
    .click();
  await page
    .getByRole("button", { name: "계획 동의 저장", exact: true })
    .click();
  await page.getByRole("button", { name: "실행 요청", exact: true }).click();
  await page
    .locator(".job-detail-toolbar [role=status]")
    .filter({ hasText: "완료" })
    .waitFor({ timeout: 90000 });
  const done = await (
    await context.request.get(c.origin + "/api/renewal/jobs/" + child)
  ).json();
  assert.equal(done.status, "completed");
  const run = done.runs[0],
    ref = run.result.outputs.video;
  const download = await context.request.get(
    c.origin + "/api/renewal/jobs/" + child + "/artifacts/" + run.id + "/video",
  );
  assert.equal(download.status(), 200);
  const bytes = await download.body();
  assert.equal(bytes.length, ref.bytes);
  assert.equal(createHash("sha256").update(bytes).digest("hex"), ref.sha256);
  await writeFile(out + "/child.mp4", bytes);
  await control("late", { case: "recover" });
  const final = await (await control("readback")).json();
  assert(Object.values(final.parents_unchanged).every(Boolean));
  assert.equal(final.children.length, 1);
  assert.equal(final.children[0].status, "completed");
  assert.equal(final.decisions.length, 2);
  assert.equal(final.late_results, 2);
  assert.equal(posts.filter((p) => p.choice === "create_child").length, 1);
  assert.equal(errors.length, 0, errors.join("\n"));
  checks.push(
    "new child uses separate plan/admission and real FFmpeg, actual MP4 download SHA, repeated old result isolated",
  );
  await writeFile(
    out + "/browser-results.json",
    JSON.stringify(
      {
        passed: true,
        scope:
          "isolated genuine ASGI API/PG/local synthetic execution; no operating job or physical worker manipulation",
        checks,
        decisions_sent: posts.map((p) => ({
          id: p.decision_id,
          choice: p.choice,
        })),
        child,
        reference: ref,
        db: final,
        page_errors: errors,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({
      passed: true,
      cases: checks.length,
      child_completed: true,
      parents_unchanged: true,
      real_download_SHA_match: true,
    }),
  );
} finally {
  await browser.close();
}
