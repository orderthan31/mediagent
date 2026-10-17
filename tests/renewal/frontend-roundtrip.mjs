// Actual production bundle -> HTTP API -> isolated PostgreSQL round trip.
// Synthetic credentials enter the test API client only, never browser form inputs.
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { chromium } from "../../apps/web/node_modules/@playwright/test/index.mjs";
const base = process.env.MIDEAGENT_TEST_ORIGIN;
assert(base?.startsWith("http://127.0.0.1:"));
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext();
const page = await context.newPage();
const errors = [];
const badResponses = [];
const apiPaths = new Set();
page.on("request", (request) => {
  const url = new URL(request.url());
  if (url.origin === base && url.pathname.startsWith("/api/"))
    apiPaths.add(url.pathname);
});
page.on("pageerror", (error) => errors.push(error.message));
page.on("response", (response) => {
  if (response.url().startsWith(base + "/api/") && response.status() >= 400)
    badResponses.push(
      response.status() + " " + new URL(response.url()).pathname,
    );
});
await context.route("**/*", (route) =>
  new URL(route.request().url()).origin === base
    ? route.continue()
    : route.abort(),
);
const waitText = async (locator, text) => {
  await locator.filter({ hasText: text }).first().waitFor();
};
try {
  await page.goto(base + "/#/serving");
  await waitText(page.locator("#auth-title"), "최초 관리자 생성");
  assert.equal(await page.locator('input[name="confirmation"]').count(), 1);
  const password = randomBytes(24).toString("base64url");
  assert.equal(
    (
      await context.request.post(base + "/api/auth/bootstrap", {
        data: { username: "browser-admin", password },
      })
    ).status(),
    201,
  );
  const logged = await context.request.post(base + "/api/auth/login", {
    data: { username: "browser-admin", password },
  });
  assert.equal(logged.status(), 200);
  const csrf = (await logged.json()).csrf_token;
  await page.reload();
  await page.getByRole("link", { name: "공급자", exact: true }).waitFor();
  await page.getByRole("link", { name: "공급자", exact: true }).click();
  await page.getByRole("link", { name: "공급자 추가", exact: true }).click();
  await page.getByLabel("이름", { exact: true }).fill("Roundtrip on-prem");
  await page
    .getByLabel("API 기본 주소", { exact: true })
    .fill("http://127.0.0.1:9/deploy/v1");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await page.waitForURL(/#\/serving\/connections\/[a-f0-9]{32}$/);
  await waitText(page.locator(".ui02-title-slot h1"), "Roundtrip on-prem");
  await page.reload();
  await waitText(page.locator(".ui02-title-slot h1"), "Roundtrip on-prem");
  let connections = (
    await (
      await context.request.get(base + "/api/settings/serving-connections")
    ).json()
  ).connections;
  assert.equal(connections.length, 1);
  const connectionId = connections[0].id;
  await page.goto(base + "/#/serving/new");
  await page.getByLabel("등록 이름").fill("Roundtrip model");
  await page.getByLabel("공급자 연결").selectOption(connectionId);
  await page.locator('input[aria-label="등록 model"]').fill("test-local-model");
  await page
    .getByRole("checkbox", { name: "모델 유형 텍스트", exact: true })
    .check();
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await page.waitForURL(/#\/serving\/[a-f0-9]{32}$/);
  await waitText(page.locator(".ui02-title-slot h1"), "Roundtrip model");
  const models = (
    await (
      await context.request.get(base + "/api/settings/registered-models")
    ).json()
  ).models;
  assert.equal(models.length, 1);
  const modelId = models[0].id;
  assert.equal(models[0].versions["1"].connection_revision, 1);
  assert.deepEqual(models[0].versions["1"].model_types, ["text"]);
  assert.deepEqual(models[0].versions["1"].capabilities, ["text_generation"]);
  await page.reload();
  await waitText(page.locator(".ui02-title-slot h1"), "Roundtrip model");
  assert.equal(
    (await page.locator(".ui02-breadcrumb").innerText())
      .replace(/\s+/g, " ")
      .trim(),
    "서빙 Roundtrip model",
  );
  await page.goto(base + "/#/serving/connections/" + connectionId + "/edit");
  await page
    .getByLabel("API 기본 주소", { exact: true })
    .fill("http://127.0.0.1:10/v1");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await page.waitForURL(/#\/serving\/connections\/[a-f0-9]{32}$/);
  await waitText(page.locator(".ui02-title-slot h1"), "Roundtrip on-prem");
  await page.goto(base + "/#/serving/" + modelId + "/edit");
  await page
    .getByRole("button", { name: "변경된 연결 적용", exact: true })
    .waitFor();
  assert.equal(
    (
      await (
        await context.request.get(base + "/api/settings/registered-models")
      ).json()
    ).models[0].versions["1"].connection_revision,
    1,
  );
  assert.doesNotMatch(
    await page.getByLabel("공급자 연결").locator("option:checked").innerText(),
    /r\d+/,
  );
  await page
    .getByRole("button", { name: "변경된 연결 적용", exact: true })
    .click();
  await page
    .getByRole("checkbox", { name: "모델 유형 텍스트", exact: true })
    .check();
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await page.waitForURL(/#\/serving\/[a-f0-9]{32}$/);
  await waitText(page.locator(".ui02-title-slot h1"), "Roundtrip model");
  const pinned = (
    await (
      await context.request.get(base + "/api/settings/registered-models")
    ).json()
  ).models[0];
  assert.equal(pinned.current_revision, 2);
  assert.equal(pinned.versions["1"].connection_revision, 1);
  assert.equal(pinned.versions["2"].connection_revision, 2);
  assert.equal(
    (
      await context.request.post(base + "/api/accounts", {
        headers: { "X-CSRF-Token": csrf },
        data: {
          username: "browser-reader",
          password: randomBytes(24).toString("base64url"),
        },
      })
    ).status(),
    201,
  );
  await page.getByRole("link", { name: "계정 관리", exact: true }).click();
  await waitText(page.locator(".account-table-row"), "browser-reader");
  await page.reload();
  await waitText(page.locator(".account-table-row"), "browser-reader");
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await waitText(page.locator("#auth-title"), "작업 공간에 로그인");
  assert.equal(
    (await (await context.request.get(base + "/api/auth/session")).json()).user,
    null,
  );
  assert.deepEqual(errors, []);
  assert.deepEqual(badResponses, []);
  assert(
    [...apiPaths].every((path) =>
      /^\/api\/(auth\/|accounts$|settings\/(serving-connections|registered-models))/.test(
        path,
      ),
    ),
    "Foundation must never activate legacy media/queue endpoints",
  );
  console.log(
    JSON.stringify({
      result: "passed",
      bootstrap_screen: true,
      real_api_session: true,
      connection_create_reopen_revision: true,
      model_create_reopen_explicit_rebind: true,
      immutable_old_reference: true,
      account_list_reopen: true,
      logout_revoked: true,
      browser_errors: errors.length,
      failed_api_responses: badResponses.length,
      real_model_calls: 0,
      user_media_operations: 0,
    }),
  );
} finally {
  await context.close();
  await browser.close();
}
