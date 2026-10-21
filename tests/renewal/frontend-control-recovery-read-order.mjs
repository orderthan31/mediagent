import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { chromium } from "../../apps/web/node_modules/@playwright/test/index.mjs";
assert.equal(process.env.MIDEAGENT_CONTROL_DISPOSABLE, "1");
const c = JSON.parse(await readFile(process.argv[2], "utf8")),
  b = await chromium.launch({ headless: true, channel: "msedge" }),
  x = await b.newContext(),
  p = await x.newPage();
assert(c.origin.startsWith("http://127.0.0.1:"));
try {
  const login = await x.request.post(c.origin + "/api/auth/login", {
      data: c.admin,
    }),
    csrf = (await login.json()).csrf_token,
    headers = { Origin: c.origin, "X-CSRF-Token": csrf },
    ep = c.origin + "/api/admin/agents/validate_video/recovery";
  await p.goto(c.origin + "/#/agents/validate_video");
  const q = p.getByRole("region", { name: "에이전트 복구 확인", exact: true });
  await q.getByRole("button", { name: "판단 상태 새로고침" }).waitFor();
  let held,
    oldResponse,
    intercept = true;
  await p.route("**/api/admin/agents/validate_video/recovery", async (r) => {
    if (intercept) {
      intercept = false;
      oldResponse = await r.fetch();
      held = r;
    } else await r.continue();
  });
  await q.getByRole("button", { name: "판단 상태 새로고침" }).click();
  while (!held) await p.waitForTimeout(40);
  const plan = await (
      await x.request.post(ep + "/preview", { data: {}, headers })
    ).json(),
    reason =
      "새 GET가 확인한 판단 이력을 늦은 GET가 덮을 수 없음 " +
      crypto.randomUUID().slice(0, 8);
  assert.equal(
    (
      await x.request.post(ep + "/decisions", {
        data: {
          plan_id: plan.id,
          decision_id: crypto.randomUUID().replaceAll("-", ""),
          choice: "hold",
          reason,
        },
        headers,
      })
    ).status(),
    200,
  );
  await q.getByRole("button", { name: "판단 상태 새로고침" }).click();
  await q.getByText(reason, { exact: true }).waitFor();
  await held.fulfill({ response: oldResponse });
  await p.waitForTimeout(250);
  assert.equal(await q.getByText(reason, { exact: true }).count(), 1);
  await writeFile(
    c.evidence + "/read-order-result.json",
    JSON.stringify({
      passed: true,
      scope:
        "delayed genuine older GET cannot replace newer actual API history",
    }),
  );
} finally {
  await x.close();
  await b.close();
}
