// Production bundle -> authenticated loopback API -> real PG -> real CPU processes.
// No mock transport. Synthetic account access uses API, not password form entry.
import assert from "node:assert/strict";
import { randomBytes, randomUUID, createHash } from "node:crypto";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { chromium } from "../../apps/web/node_modules/@playwright/test/index.mjs";
import { listGeometry } from "./list-geometry.mjs";
const base = process.env.MIDEAGENT_TEST_ORIGIN;
const evidence = process.env.MIDEAGENT_EXECUTION_EVIDENCE;
assert(base?.startsWith("http://127.0.0.1:"));
assert(evidence && process.env.MIDEAGENT_TEST_MOVIE);
await mkdir(evidence, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  ...(process.env.MIDEAGENT_TEST_CHROME
    ? { executablePath: process.env.MIDEAGENT_TEST_CHROME }
    : {}),
  args: ["--disable-gpu"],
});
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
});
const page = await context.newPage();
const errors = [];
const failed = [];
const paths = new Set();
page.on("pageerror", (error) => errors.push(error.message));
page.on("request", (request) => {
  const url = new URL(request.url());
  if (url.pathname.startsWith("/api/")) paths.add(url.pathname);
});
page.on("response", (response) => {
  if (response.url().startsWith(base + "/api/") && response.status() >= 400)
    failed.push(response.status() + " " + new URL(response.url()).pathname);
});
await context.route("**/*", (route) =>
  new URL(route.request().url()).origin === base
    ? route.continue()
    : route.abort(),
);
const waitFor = async (callback) => {
  for (let n = 0; n < 100; n++) {
    const result = await callback();
    if (result) return result;
    await page.waitForTimeout(100);
  }
  throw new Error("Persisted state did not reach expected condition");
};
try {
  const password = randomBytes(24).toString("base64url");
  assert.equal(
    (
      await context.request.post(base + "/api/auth/bootstrap", {
        data: { username: "infra-browser", password },
      })
    ).status(),
    201,
  );
  const auth = await context.request.post(base + "/api/auth/login", {
    data: { username: "infra-browser", password },
  });
  assert.equal(auth.status(), 200);
  const csrf = (await auth.json()).csrf_token;
  const post = (path, data) =>
    context.request.post(base + "/api" + path, {
      data,
      headers: { "X-CSRF-Token": csrf },
    });
  await page.goto(base + "/#/");
  await page
    .getByText("등록된 원본 영상이 없습니다.", { exact: true })
    .waitFor();
  await page
    .locator("input[type=file]")
    .first()
    .setInputFiles(process.env.MIDEAGENT_TEST_MOVIE);
  const source = await waitFor(async () => {
    const response = await context.request.get(base + "/api/videos");
    return (await response.json()).videos[0];
  });
  assert(source.content_verified);
  await page.locator(".storage-asset-row").first().waitFor();
  assert.deepEqual((await listGeometry(page)).violations, []);
  await page.locator(".storage-asset-row").first().click();
  await page.getByRole("heading", { name: "영상 정보", exact: true }).waitFor();
  assert.equal(
    await page.getByRole("button", { name: /삭제|자막|얼굴/ }).count(),
    0,
  );
  assert.equal(await page.locator(".storage-video-info video").count(), 1);
  assert.equal(source.web_preview.status, "ready");
  const originalSource = await context.request.get(
    base + "/api/videos/" + source.asset_id + "/download",
  );
  assert.equal(
    createHash("sha256")
      .update(await originalSource.body())
      .digest("hex"),
    source.sha256,
  );
  const sourceWebM = await context.request.get(
    base + "/api/videos/" + source.asset_id + "/stream?download=true",
  );
  assert.equal(sourceWebM.headers()["content-type"], "video/webm");
  assert.equal(
    createHash("sha256")
      .update(await sourceWebM.body())
      .digest("hex"),
    source.web_preview.reference.sha256,
  );
  const sourcePlayback = await page
    .locator(".storage-video-info video")
    .evaluate(async (video) => {
      video.muted = true;
      await video.play();
      await new Promise((resolve) => setTimeout(resolve, 300));
      video.pause();
      return {
        currentTime: video.currentTime,
        width: video.videoWidth,
        height: video.videoHeight,
      };
    });
  assert(sourcePlayback.currentTime > 0.1 && sourcePlayback.width > 0);
  await page.getByRole("link", { name: "원본 받기", exact: true }).waitFor();
  await page.getByRole("link", { name: "WebM 받기", exact: true }).waitFor();
  const definition = JSON.parse(
    await readFile(process.env.MIDEAGENT_TEST_DEFINITION, "utf8"),
  );
  const wid = randomUUID().replaceAll("-", "");
  const saved = await context.request.put(
    base + "/api/settings/workflow-definitions/" + wid,
    { data: definition, headers: { "X-CSRF-Token": csrf } },
  );
  assert.equal(saved.status(), 200);
  await page.goto(base + "/#/workflows/" + wid);
  await page.getByLabel("워크플로우 이름").fill("실제 CPU 연동");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await waitFor(
    async () =>
      (
        await (
          await context.request.get(
            base + "/api/settings/workflow-definitions/" + wid,
          )
        ).json()
      ).revision === 2,
  );
  await page.reload();
  await waitFor(
    async () =>
      (await page.getByLabel("워크플로우 이름").inputValue()) ===
      "실제 CPU 연동",
  );
  await page.goto(base + "/#/start");
  await page.getByLabel("원본", { exact: true }).selectOption(source.asset_id);
  await page.getByLabel("워크플로우", { exact: true }).selectOption(wid);
  await page.getByRole("button", { name: "실행 전 확인", exact: true }).click();
  await page.getByRole("button", { name: "작업 생성", exact: true }).click();
  await page.waitForURL(/#\/jobs\/[a-f0-9]{32}$/);
  const id = page.url().split("/jobs/")[1];
  const jobPath = "/renewal/jobs/" + id;
  let state = await (await context.request.get(base + "/api" + jobPath)).json();
  assert.equal(state.status, "draft");
  assert.equal(state.runs.length, 0);
  await page
    .getByRole("button", { name: "실행 계획 확인", exact: true })
    .click();
  await page
    .getByRole("button", { name: "계획 동의 저장", exact: true })
    .click();
  await page.getByRole("button", { name: "실행 요청", exact: true }).click();
  state = await waitFor(async () => {
    const job = await (
      await context.request.get(base + "/api" + jobPath)
    ).json();
    return job.status === "review_required" && job;
  });
  await page.getByRole("button", { name: "새로고침", exact: true }).click();
  const reviewRun = state.runs.find((r) => r.node_type === "review");
  assert(reviewRun);
  await page
    .locator(
      '[data-node-id="' + reviewRun.node_id + '"] .workflow-node-heading',
    )
    .click();
  await page.getByLabel("자료를 확인했음").check();
  await page.getByRole("button", { name: "검수 저장", exact: true }).click();
  await page.getByRole("button", { name: "검수 확정", exact: true }).click();
  await page
    .getByRole("button", { name: "실행 계획 확인", exact: true })
    .click();
  await page
    .getByRole("button", { name: "계획 동의 저장", exact: true })
    .click();
  await page.getByRole("button", { name: "실행 요청", exact: true }).click();
  state = await waitFor(async () => {
    const job = await (
      await context.request.get(base + "/api" + jobPath)
    ).json();
    return job.status === "completed" && job;
  });
  await page.getByRole("button", { name: "새로고침", exact: true }).click();
  const encoded = state.runs.find((r) => r.node_type === "encode");
  const outputUrl = jobPath + "/artifacts/" + encoded.id + "/video";
  const output = await context.request.get(base + "/api" + outputUrl);
  assert.equal(output.status(), 200);
  assert.equal(
    createHash("sha256")
      .update(await output.body())
      .digest("hex"),
    encoded.result.outputs.video.sha256,
  );
  assert(
    state.runs
      .filter((r) => r.node_type !== "review")
      .every(
        (r) =>
          r.result.transport ===
            (process.env.MIDEAGENT_EXPECT_TRANSPORT ?? "subprocess") &&
          (process.env.MIDEAGENT_EXPECT_TRANSPORT === "s3_subprocess" ||
            r.result.process_exit_code === 0),
      ),
  );
  await page.reload();
  await page
    .locator('[data-node-id="' + encoded.node_id + '"] .workflow-node-heading')
    .click();
  await page
    .getByRole("link", { name: "작업 결과 원본 받기", exact: true })
    .waitFor();
  const preview = encoded.result.previews.video;
  assert.equal(preview.status, "ready");
  const webOutput = await context.request.get(
    base + "/api" + outputUrl + "/preview?download=true",
  );
  assert.equal(webOutput.headers()["content-type"], "video/webm");
  assert.equal(
    createHash("sha256")
      .update(await webOutput.body())
      .digest("hex"),
    preview.reference.sha256,
  );
  const originalDownloadEvent = page.waitForEvent("download");
  await page
    .getByRole("link", { name: "작업 결과 원본 받기", exact: true })
    .click();
  const originalDownload = await originalDownloadEvent;
  const originalDownloadPath = evidence + "/synthetic-result-original.mp4";
  await originalDownload.saveAs(originalDownloadPath);
  assert.equal(
    createHash("sha256")
      .update(await readFile(originalDownloadPath))
      .digest("hex"),
    encoded.result.outputs.video.sha256,
  );
  const webDownloadEvent = page.waitForEvent("download");
  await page.getByRole("link", { name: "WebM 받기", exact: true }).click();
  const webDownload = await webDownloadEvent;
  const webDownloadPath = evidence + "/synthetic-result-web.webm";
  await webDownload.saveAs(webDownloadPath);
  assert.equal(
    createHash("sha256")
      .update(await readFile(webDownloadPath))
      .digest("hex"),
    preview.reference.sha256,
  );
  const playback = await page
    .locator(".renewal-node-results video")
    .last()
    .evaluate(async (video) => {
      video.muted = true;
      await video.play();
      await new Promise((resolve, reject) => {
        const timer = setTimeout(
          () => reject(new Error("Synthetic playback did not advance")),
          5000,
        );
        const advance = () => {
          if (video.currentTime > 0.1) {
            clearTimeout(timer);
            video.removeEventListener("timeupdate", advance);
            resolve();
          }
        };
        video.addEventListener("timeupdate", advance);
        advance();
      });
      video.pause();
      return {
        duration: video.duration,
        currentTime: video.currentTime,
        width: video.videoWidth,
        height: video.videoHeight,
      };
    });
  const screens = [];
  for (const [name, width, height] of [
    ["pc", 1920, 1080],
    ["cover", 416, 657],
    ["unfolded", 816, 616],
  ]) {
    await page.setViewportSize({ width, height });
    await page.evaluate(() => scrollTo(0, 0));
    await page.waitForTimeout(120);
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
      name + ": document overflow",
    );
    const path = evidence + "/" + name + "-execution.png";
    await page.screenshot({ path, fullPage: false });
    const webmLink = page.getByRole("link", { name: "WebM 받기", exact: true });
    await webmLink.scrollIntoViewIfNeeded();
    const downloadBounds = await webmLink.boundingBox();
    assert(
      downloadBounds &&
        downloadBounds.x >= 0 &&
        downloadBounds.y >= 0 &&
        downloadBounds.x + downloadBounds.width <= width + 1 &&
        downloadBounds.y + downloadBounds.height <= height + 1,
      name + ": WebM download unreachable",
    );
    await page.screenshot({
      path: evidence + "/" + name + "-downloads.png",
      fullPage: false,
    });
    screens.push({ name, width, height });
  }
  await page.goto(base + "/#/jobs");
  await page
    .getByRole("cell", { name: "실제 CPU 연동", exact: true })
    .waitFor();
  const count = (await (await context.request.get(base + "/api/jobs")).json())
    .jobs.length;
  assert.equal(count, 1);
  assert.deepEqual(errors, []);
  assert.deepEqual(failed, []);
  assert(
    ![...paths].some((path) =>
      /\/settings\/(work-tickets|system)|\/queue|\/uploads/.test(path),
    ),
  );
  const receipt = {
    browser_version: browser.version(),
    codec_support: await page.evaluate(() => {
      const video = document.createElement("video");
      return {
        h264: video.canPlayType('video/mp4; codecs="avc1.42E01E"'),
        aac: video.canPlayType('audio/mp4; codecs="mp4a.40.2"'),
      };
    }),
    real_postgres: true,
    transport: process.env.MIDEAGENT_EXPECT_TRANSPORT ?? "real_cpu_subprocess",
    mock_requests: false,
    source_sha256: source.sha256,
    job_id: id,
    ticket_number: state.ticket_number,
    snapshot_sha256: state.snapshot_sha256,
    status: state.status,
    nodes: state.runs.map((r) => ({ type: r.node_type, status: r.status })),
    screens,
    playback,
    source_playback: sourcePlayback,
    web_preview_sha256: preview.reference.sha256,
    browser_downloads: {
      original: originalDownload.suggestedFilename(),
      webm: webDownload.suggestedFilename(),
    },
    browser_errors: errors,
    failed_api_responses: failed,
    api_paths: [...paths].sort(),
  };
  await writeFile(
    evidence + "/browser-execution.json",
    JSON.stringify(receipt, null, 2),
  );
  console.log(JSON.stringify(receipt));
} catch (error) {
  const diagnostic = {
    media: await page.locator("video").evaluateAll((videos) =>
      videos.map((video) => ({
        src: video.currentSrc,
        network: video.networkState,
        ready: video.readyState,
        error: video.error?.message,
        h264: video.canPlayType('video/mp4; codecs="avc1.42E01E"'),
      })),
    ),
    error: error.message,
    url: page.url(),
    errors,
    failed,
    paths: [...paths],
    body: await page.locator("body").innerText(),
  };
  await writeFile(
    evidence + "/failure-" + Date.now() + ".json",
    JSON.stringify(diagnostic, null, 2),
  );
  await page.screenshot({
    path: evidence + "/failure-latest.png",
    fullPage: true,
  });
  console.error(JSON.stringify(diagnostic));
  throw error;
} finally {
  await context.close();
  await browser.close();
}
