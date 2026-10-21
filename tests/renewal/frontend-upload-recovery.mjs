// Real UI file chooser -> installed API -> disposable PG/CAS/FFmpeg.
// Only the deliberately interrupted chunk requests are intercepted; no fake successes.
import assert from "node:assert/strict";
import { randomBytes, createHash } from "node:crypto";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { basename, resolve } from "node:path";
import { chromium } from "../../apps/web/node_modules/@playwright/test/index.mjs";
import { blockSize } from "../../apps/web/src/upload-verification.ts";
const base = process.env.MIDEAGENT_TEST_ORIGIN,
  file = process.env.MIDEAGENT_TEST_MOVIE,
  evidence = process.env.MIDEAGENT_UPLOAD_EVIDENCE;
assert(base?.startsWith("http://127.0.0.1:") && file && evidence);
await mkdir(evidence, { recursive: true });
const bytes = await readFile(file),
  name = basename(file);
assert(bytes.length > blockSize, "Need a real multi-block video");
const browser = await chromium.launch({ headless: true, channel: "msedge" });
const phone = process.env.MIDEAGENT_UPLOAD_PHONE === "1";
const context = await browser.newContext({
  viewport: phone ? { width: 390, height: 844 } : { width: 1440, height: 1000 },
});
const page = await context.newPage();
page.setDefaultTimeout(12000);
page.on("dialog", (d) => d.accept());
const errors = [],
  ledger = [];
let interrupt = true,
  failedChunks = 0,
  verifyCalls = 0,
  createCalls = 0;
page.on("pageerror", (e) => errors.push(e.message));
page.on("request", (r) => {
  const u = new URL(r.url());
  if (u.pathname === "/api/video-uploads" && r.method() === "POST")
    createCalls++;
  if (u.pathname.endsWith("/verify")) verifyCalls++;
  if (u.pathname.startsWith("/api/video-uploads"))
    ledger.push({
      method: r.method(),
      path: u.pathname,
      offset: u.searchParams.get("offset"),
    });
});
await page.route("**/api/video-uploads/*/chunks?*", (route) => {
  const offset = Number(
    new URL(route.request().url()).searchParams.get("offset"),
  );
  if (interrupt && offset >= blockSize) {
    failedChunks++;
    return route.abort("failed");
  }
  return route.continue();
});
let report = {
  scope: "ISOLATED_REAL_API_UI_UPLOAD_NOT_PRODUCT_DEPLOYMENT",
  passed: false,
};
try {
  const password = randomBytes(24).toString("base64url");
  const boot = await context.request.post(base + "/api/auth/bootstrap", {
    data: { username: "upload-fixture", password },
  });
  assert.equal(boot.status(), 201);
  const login = await context.request.post(base + "/api/auth/login", {
    data: { username: "upload-fixture", password },
  });
  assert.equal(login.status(), 200);
  const csrf = (await login.json()).csrf_token;
  const memberPassword = randomBytes(24).toString("base64url");
  const issued = await context.request.post(base + "/api/accounts", {
    data: { username: "upload-member", password: memberPassword },
    headers: { "X-CSRF-Token": csrf },
  });
  assert.equal(issued.status(), 201);
  const member = await context.request.post(base + "/api/auth/login", {
    data: { username: "upload-member", password: memberPassword },
  });
  assert.equal(member.status(), 200);
  assert.equal((await member.json()).user.role, "user");
  assert.equal(
    (await context.request.get(base + "/api/admin/agents")).status(),
    403,
  );
  await page.goto(base + "/#/");
  await page
    .getByText("등록된 원본 영상이 없습니다.", { exact: true })
    .waitFor();
  const upload = page.getByRole("button", { name: "원본 업로드", exact: true });
  await upload.waitFor();
  assert(
    await upload.locator("span").isVisible(),
    "Upload text must remain visible",
  );
  await page.screenshot({
    path: resolve(evidence, "original-list-upload-button.png"),
  });
  const chooser = page.waitForEvent("filechooser");
  await upload.click();
  await (await chooser).setFiles(file);
  await page.getByText("실패", { exact: true }).waitFor({ timeout: 30000 });
  assert.match(
    await page.locator(".upload-strip-error").innerText(),
    /전송 연결 끊김/,
  );
  const partial = (
    await (await context.request.get(base + "/api/video-uploads")).json()
  ).uploads[0];
  assert(partial.uploaded_bytes > 0 && partial.uploaded_bytes < bytes.length);
  assert.equal(partial.asset_id, null);
  assert(failedChunks > 0);
  await page.screenshot({
    path: resolve(evidence, "interrupted-progress.png"),
  });
  // Recover after losing the in-memory File object, not merely an optimistic retry.
  interrupt = false;
  await page.reload();
  const stateButton = page.getByRole("button", {
    name: "업로드 상태",
    exact: true,
  });
  await stateButton.waitFor();
  if ((await stateButton.getAttribute("aria-expanded")) !== "true")
    await stateButton.click();
  const resume = page.getByRole("button", {
    name: "파일 선택 후 재개: " + name,
    exact: true,
  });
  await resume.waitFor();
  const resumeChooser = page.waitForEvent("filechooser");
  await resume.click();
  await (await resumeChooser).setFiles(file);
  await page
    .locator(".storage-asset-row")
    .filter({ hasText: name })
    .waitFor({ timeout: 60000 });
  const assets = (
    await (await context.request.get(base + "/api/videos")).json()
  ).videos;
  const asset = assets.find((x) => x.original_filename === name);
  assert(asset?.content_verified);
  assert.equal(asset.sha256, createHash("sha256").update(bytes).digest("hex"));
  assert.equal(createCalls, 1, "Resumption must reuse the same upload session");
  assert(
    verifyCalls > 0,
    "Stored prefix must really be verified through the API",
  );
  const final = await (
    await context.request.get(base + "/api/video-uploads/" + partial.upload_id)
  ).json();
  assert.equal(final.asset_id, asset.asset_id);
  const close = page.getByRole("button", {
    name: "업로드 상태 닫기",
    exact: true,
  });
  if (await close.isVisible()) await close.click();
  await page.locator(".storage-asset-row").filter({ hasText: name }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "원본 받기", exact: true }).click();
  const downloaded = await readFile(await (await download).path());
  assert.equal(
    createHash("sha256").update(downloaded).digest("hex"),
    asset.sha256,
  );
  assert.deepEqual(errors, []);
  await page.screenshot({
    path: resolve(evidence, "recovered-original-detail.png"),
  });
  report = {
    ...report,
    passed: true,
    upload_id: partial.upload_id,
    asset_id: asset.asset_id,
    bytes: bytes.length,
    stored_before_resume: partial.uploaded_bytes,
    source_sha256: asset.sha256,
    failed_chunks: failedChunks,
    prefix_checks: verifyCalls,
    sessions_created: createCalls,
    actual_download_hash_matches: true,
  };
} catch (error) {
  report = { ...report, error: String(error), page_errors: errors };
  await page.screenshot({ path: resolve(evidence, "failure.png") });
  throw error;
} finally {
  await writeFile(
    resolve(evidence, "result.json"),
    JSON.stringify({ ...report, ledger }, null, 2),
  );
  await context.close();
  await browser.close();
}
console.log(JSON.stringify(report));
