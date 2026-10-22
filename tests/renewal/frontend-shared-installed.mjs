// Genuine installed API/auth/PG/CPU. No request mocking or injected results.
import assert from "node:assert/strict";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { createHash, randomUUID } from "node:crypto";
import {
  chromium,
  expect,
} from "../../apps/web/node_modules/@playwright/test/index.mjs";
const fixturePath = process.env.MIDEAGENT_SHARED_FIXTURE;
assert(fixturePath);
const f = JSON.parse(await readFile(fixturePath, "utf8"));
assert(f.base.startsWith("http://127.0.0.1:"));
await mkdir(f.evidence, { recursive: true });
const saveFixture = () => writeFile(fixturePath, JSON.stringify(f));
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
const movie = await readFile(f.movie);
const results = [];
const browser = await chromium.launch({ headless: true, channel: "msedge" });
const contexts = [];
const errors = [];
let a, b, pa, pb;
const api = async (ctx, method, path, data) => {
  const response = await ctx.request.fetch(f.base + path, { method, data });
  return response;
};
async function login(account) {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 1100 },
    acceptDownloads: true,
  });
  contexts.push(ctx);
  const session = await ctx.request.get(f.base + "/api/auth/session");
  if ((await session.json()).setup_required) {
    assert.equal(account.username, f.a.username);
    const setup = await ctx.request.post(f.base + "/api/auth/bootstrap", {
      data: account,
    });
    assert.equal(setup.status(), 201);
  }
  // Generated isolated fixture credentials go through the real auth API; no cookie injection.
  const response = await ctx.request.post(f.base + "/api/auth/login", {
    data: account,
  });
  assert.equal(response.status(), 200, "fixture normal login failed");
  const state = await response.json();
  await ctx.setExtraHTTPHeaders({
    "X-CSRF-Token": state.csrf_token,
    Origin: f.base,
  });
  return ctx;
}
async function download(page, locator, name) {
  const [transfer] = await Promise.all([
    page.waitForEvent("download"),
    locator.click({ timeout: 8000 }),
  ]);
  const file = resolve(f.evidence, name);
  await transfer.saveAs(file);
  const bytes = await readFile(file);
  return {
    bytes: bytes.length,
    sha256: sha(bytes),
    suggestedFilename: transfer.suggestedFilename(),
  };
}
async function readonly(page, jobId) {
  await page.goto(f.base + "/#/jobs/" + jobId);
  await page.reload(); // Deliberately reset same-hash canvas selection between viewports.
  await expect(page.getByText("공용 읽기 전용", { exact: true })).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  assert.equal(
    await page
      .getByRole("button", {
        name: /실행 계획 확인|계획 동의 저장|실행 요청|승인된 처리 진행|작업 취소|새 복구 작업 만들기|검수 저장|검수 확정/,
      })
      .count(),
    0,
  );
}
try {
  a = await login(f.a);
  f.actorA = (
    await (await a.request.get(f.base + "/api/auth/session")).json()
  ).user.id;
  if (!f.actorB) {
    const created = await api(a, "POST", "/api/accounts", f.b);
    assert.equal(created.status(), 201);
    f.actorB = (await created.json()).id;
    await saveFixture();
  }
  b = await login(f.b);
  const bSession = await (
    await b.request.get(f.base + "/api/auth/session")
  ).json();
  assert.equal(bSession.user.role, "user");
  f.actorB = bSession.user.id;
  pa = await a.newPage();
  pb = await b.newPage();
  for (const p of [pa, pb]) p.on("pageerror", (e) => errors.push(e.message));
  if (!f.assetId) {
    await pa.goto(f.base + "/#/videos");
    await pa.locator("input[type=file][multiple]").setInputFiles(f.movie);
    await expect
      .poll(
        async () => {
          const rows = await (
            await a.request.get(f.base + "/api/videos")
          ).json();
          return rows.videos.find(
            (v) => v.original_filename === "shared-synthetic.mp4",
          )?.asset_id;
        },
        { timeout: 30000 },
      )
      .toBeTruthy();
    const rows = await (await a.request.get(f.base + "/api/videos")).json();
    f.assetId = rows.videos.find(
      (v) => v.original_filename === "shared-synthetic.mp4",
    ).asset_id;
    await saveFixture();
  }
  const original = (
    await (await b.request.get(f.base + "/api/videos/" + f.assetId)).json()
  ).video;
  assert.equal(original.uploaded_by, f.actorA);
  assert.equal(original.sha256, sha(movie));
  await pb.goto(f.base + "/#/videos/" + f.assetId);
  const originalDownload = await download(
    pb,
    pb.getByRole("link", { name: "원본 받기", exact: true }),
    "b-original.mp4",
  );
  assert.equal(originalDownload.sha256, sha(movie));
  results.push({
    name: "A UI upload to shared B real original download",
    passed: true,
    originalDownload,
  });
  // Vertical audit-display assertion: recorded RED before adding the remaining original UI field.
  await expect(pb.getByText("원본 업로더", { exact: true })).toBeVisible();
  await expect(pb.getByText(f.actorA, { exact: true })).toBeVisible();
  await pb.screenshot({
    path: resolve(f.evidence, "b-original-pc.png"),
    fullPage: true,
  });
  if (!f.workflowId) {
    f.workflowId = randomUUID().replaceAll("-", "");
    const graph = {
      catalog_version: 1,
      revision: 0,
      name: "공용 자료 합성 CPU",
      inputs: { video: "video" },
      nodes: [
        {
          id: "encode",
          type: "encode",
          options: { subtitle_mode: "none" },
          position: { x: 240, y: 80 },
        },
        {
          id: "validate",
          type: "validate_video",
          options: {},
          position: { x: 540, y: 80 },
        },
      ],
      edges: [
        {
          id: "input-video",
          source: { node: "$input", port: "video" },
          target: { node: "encode", port: "video" },
        },
        {
          id: "encoded-video",
          source: { node: "encode", port: "video" },
          target: { node: "validate", port: "video" },
        },
      ],
    };
    const created = await api(
      a,
      "PUT",
      "/api/settings/workflow-definitions/" + f.workflowId,
      graph,
    );
    assert.equal(created.status(), 200);
    await saveFixture();
  }
  if (!f.jobId) {
    await pb.goto(f.base + "/#/start");
    await pb.getByLabel("원본", { exact: true }).selectOption(f.assetId);
    await pb
      .getByLabel("워크플로우", { exact: true })
      .selectOption(f.workflowId);
    await expect(
      pb.getByRole("button", { name: "실행 전 확인", exact: true }),
    ).toBeEnabled();
    await pb.getByRole("button", { name: "실행 전 확인", exact: true }).click();
    await pb.getByRole("button", { name: "작업 생성", exact: true }).click();
    await pb.waitForURL(/#\/jobs\/[a-f0-9]{32}$/);
    f.jobId = pb.url().split("/").at(-1);
    await saveFixture();
  }
  const jobPath = "/api/renewal/jobs/" + f.jobId;
  let state = await (await b.request.get(f.base + jobPath)).json();
  assert.equal(state.asset_owner_id, f.actorA);
  assert.equal(state.owner_id, f.actorB);
  assert.equal(state.snapshot.inputs.video.source_owner_id, f.actorA);
  assert.equal(state.snapshot.inputs.video.sha256, sha(movie));
  await readonly(pa, f.jobId);
  for (const [action, data] of [
    ["confirm", { token: "0".repeat(64), request_id: randomUUID() }],
    ["admit", { consent_id: "0".repeat(32), request_id: randomUUID() }],
    ["run", {}],
    ["cancel", { revision: state.revision }],
    ["recover", { request_id: randomUUID(), acknowledge_duplicate_risk: true }],
  ]) {
    assert.equal(
      (await api(a, "POST", jobPath + "/" + action, data)).status(),
      404,
      "cross-actor " + action,
    );
  }
  assert.equal(
    (await (await b.request.get(f.base + jobPath)).json()).revision,
    state.revision,
  );
  await pa.screenshot({
    path: resolve(f.evidence, "a-readonly-before-run.png"),
    fullPage: true,
  });
  results.push({
    name: "shared A reader cannot change B task even with admin account",
    passed: true,
  });
  if (!f.referenceJobA) {
    const selection = {
      asset_id: f.assetId,
      definition_id: f.workflowId,
      definition_revision: 1,
      options: {},
    };
    const preview = await api(a, "POST", "/api/work-entry/preview", selection);
    assert.equal(preview.status(), 200);
    const prepared = await api(a, "POST", "/api/work-entry/create", {
      ...selection,
      token: (await preview.json()).token,
      request_id: randomUUID(),
      paid_confirmed: false,
    });
    assert.equal(prepared.status(), 201);
    f.referenceJobA = (await prepared.json()).id;
    await saveFixture();
  }
  await readonly(pb, f.referenceJobA);
  assert.equal(
    (
      await b.request.get(
        f.base + "/api/renewal/jobs/" + f.referenceJobA + "/plan",
      )
    ).status(),
    404,
  );
  assert.equal(
    (
      await api(b, "POST", "/api/renewal/jobs/" + f.referenceJobA + "/run", {})
    ).status(),
    404,
  );
  await pb.screenshot({
    path: resolve(f.evidence, "b-user-readonly-other-job.png"),
    fullPage: true,
  });
  results.push({
    name: "ordinary B reads A draft in actual UI without plan or execution authority",
    passed: true,
    referenceJobA: f.referenceJobA,
  });
  if (state.status !== "completed") {
    await pb.goto(f.base + "/#/jobs/" + f.jobId);
    await pb
      .getByRole("button", { name: "실행 계획 확인", exact: true })
      .click();
    await pb
      .getByRole("button", { name: "계획 동의 저장", exact: true })
      .click();
    await pb.getByRole("button", { name: "실행 요청", exact: true }).click();
    await expect(pb.locator(".job-detail-toolbar [role=status]")).toHaveText(
      "완료",
      { timeout: 60000 },
    );
  }
  state = await (await b.request.get(f.base + jobPath)).json();
  assert.equal(state.status, "completed");
  assert(state.runs.every((r) => r.status === "completed"));
  const run = state.runs.find((r) => r.node_type === "encode");
  assert(run);
  const publicState = await (await a.request.get(f.base + jobPath)).json();
  assert.equal(publicState.access.can_manage, false);
  assert.equal(publicState.executed_by, f.actorB);
  assert(!("model_bindings" in publicState.snapshot));
  assert(
    publicState.runs.every((r) => !("request" in r) && !("lease_owner" in r)),
  );
  for (const path of [
    "/api/accounts",
    "/api/settings/serving-connections",
    "/api/settings/registered-models",
    "/api/settings/workflow-definitions",
  ])
    assert.equal((await b.request.get(f.base + path)).status(), 403, path);
  const uploadRows = (
    await (await a.request.get(f.base + "/api/video-uploads")).json()
  ).uploads;
  const upload = uploadRows.find((v) => v.asset_id === f.assetId);
  if (upload)
    assert.equal(
      (
        await b.request.get(f.base + "/api/video-uploads/" + upload.upload_id)
      ).status(),
      404,
    );
  const anonymous = await browser.newContext();
  contexts.push(anonymous);
  for (const path of [
    "/api/videos/" + f.assetId + "/download",
    jobPath,
    jobPath + "/artifacts/" + run.id + "/video",
  ])
    assert.equal((await anonymous.request.get(f.base + path)).status(), 401);
  results.push({
    name: "B UI-created reused input explicitly approved and actual CPU completed; private/admin/auth boundaries",
    passed: true,
    jobId: f.jobId,
    runId: run.id,
  });
  for (const [name, width, height] of [
    ["pc", 1440, 1100],
    ["phone", 390, 844],
  ]) {
    await pa.setViewportSize({ width, height });
    await readonly(pa, f.jobId);
    await expect(pa.getByText(f.actorA, { exact: true })).toBeVisible();
    await expect(pa.getByText(f.actorB, { exact: true })).toBeVisible();
    const identityBoxes = await pa
      .locator(".shared-job-custody dd")
      .evaluateAll((items) =>
        items.map((x) => {
          const r = x.getBoundingClientRect();
          return { x: r.x, y: r.y, right: r.right, bottom: r.bottom };
        }),
      );
    assert(
      identityBoxes.every(
        (r) =>
          r.x >= 0 && r.right <= width + 1 && r.y >= 0 && r.bottom <= height,
      ),
    );
    await pa.screenshot({
      path: resolve(f.evidence, `a-readonly-${name}-viewport.png`),
      fullPage: false,
    });
    await pa.screenshot({
      path: resolve(f.evidence, `a-readonly-${name}.png`),
      fullPage: true,
    });
    await pa.locator('[data-node-id="encode"] .workflow-node-heading').click();
    const transfer = await download(
      pa,
      pa.getByRole("link", { name: "작업 결과 원본 받기", exact: true }),
      `a-output-${name}.mp4`,
    );
    assert.equal(transfer.sha256, run.result.outputs.video.sha256);
    const outputVideo = pa
      .locator("section.execution-artifact:has(a[download]) video")
      .first();
    const playback = await outputVideo.evaluate(async (v) => {
      v.muted = true;
      v.currentTime = 0;
      await v.play();
      await new Promise((resolve, reject) => {
        const timer = setTimeout(
          () => reject(new Error("real output playback timeout")),
          10000,
        );
        v.addEventListener(
          "ended",
          () => {
            clearTimeout(timer);
            resolve();
          },
          { once: true },
        );
        v.addEventListener(
          "error",
          () => {
            clearTimeout(timer);
            reject(new Error("media decoder error"));
          },
          { once: true },
        );
      });
      return {
        ended: v.ended,
        duration: v.duration,
        decodedFrames: v.getVideoPlaybackQuality().totalVideoFrames,
        error: v.error?.code ?? null,
      };
    });
    assert(
      playback.ended && playback.decodedFrames > 0 && playback.error === null,
    );
    await outputVideo.scrollIntoViewIfNeeded();
    await pa.screenshot({
      path: resolve(f.evidence, `a-output-${name}-viewport.png`),
      fullPage: false,
    });
    await pa.screenshot({
      path: resolve(f.evidence, `a-output-${name}.png`),
      fullPage: true,
    });
    assert(
      await pa.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    );
    await pb.setViewportSize({ width, height });
    await pb.goto(f.base + "/#/videos/" + f.assetId);
    const copied = await download(
      pb,
      pb.getByRole("link", { name: "원본 받기", exact: true }),
      `b-original-${name}.mp4`,
    );
    assert.equal(copied.sha256, sha(movie));
    assert(
      await pb.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    );
    const originalPlayback = await pb
      .locator(".storage-preview video")
      .evaluate(async (v) => {
        v.muted = true;
        await v.play();
        await new Promise((resolve, reject) => {
          const timer = setTimeout(
            () => reject(new Error("real original playback timeout")),
            10000,
          );
          v.addEventListener(
            "ended",
            () => {
              clearTimeout(timer);
              resolve();
            },
            { once: true },
          );
          v.addEventListener(
            "error",
            () => {
              clearTimeout(timer);
              reject(new Error("original decoder error"));
            },
            { once: true },
          );
        });
        return {
          ended: v.ended,
          duration: v.duration,
          decodedFrames: v.getVideoPlaybackQuality().totalVideoFrames,
          error: v.error?.code ?? null,
        };
      });
    assert(
      originalPlayback.ended &&
        originalPlayback.decodedFrames > 0 &&
        originalPlayback.error === null,
    );
    await pb.evaluate(() => window.scrollTo(0, 0));
    await pb.screenshot({
      path: resolve(f.evidence, `b-original-${name}.png`),
      fullPage: true,
    });
    results.push({
      name: `${name} actual shared read-only output and original downloads`,
      passed: true,
      output: transfer,
      original: copied,
      playback,
      originalPlayback,
      identityBoxes,
    });
  }
  assert.deepEqual(errors, []);
} catch (error) {
  results.push({
    name: "installed browser journey",
    passed: false,
    error: String(error),
    errors,
  });
  if (pb)
    await pb
      .screenshot({ path: resolve(f.evidence, "failure.png"), fullPage: true })
      .catch(() => {});
  if (pa)
    await pa
      .screenshot({
        path: resolve(f.evidence, "failure-reader.png"),
        fullPage: true,
      })
      .catch(() => {});
} finally {
  for (const ctx of contexts) await ctx.close();
  await browser.close();
  await writeFile(
    resolve(f.evidence, "results.json"),
    JSON.stringify(
      {
        scope: "REAL_INSTALLED_API_PG_AUTH_LOCAL_CPU_NOT_OPERATING",
        sourceCreation:
          "admin workflow via real API; original upload, B job creation/approval and shared download through UI",
        results,
        errors,
      },
      null,
      2,
    ),
  );
}
assert.equal(
  results.filter((v) => !v.passed).length,
  0,
  JSON.stringify(results.filter((v) => !v.passed)),
);
console.log(
  JSON.stringify({
    scope: "INSTALLED_PRODUCT_FIXTURE",
    passed: results.length,
    errors: errors.length,
  }),
);
