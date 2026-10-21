// Isolated production-bundle UI contract tests, never a product/worker PASS.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve, extname, join } from "node:path";
import { chromium } from "../../apps/web/node_modules/@playwright/test/index.mjs";

const dist = fileURLToPath(new URL("../../apps/web/dist/", import.meta.url));
const evidence = process.env.MIDEAGENT_BROKER_UI_EVIDENCE;
assert(evidence, "Explicit private evidence directory required");
await mkdir(evidence, { recursive: true });
const server = createServer(async (request, response) => {
  try {
    const relative = new URL(request.url, "http://localhost").pathname;
    const file = resolve(
      dist,
      relative === "/" ? "index.html" : "." + relative,
    );
    assert(file.startsWith(resolve(dist)));
    const types = {
      ".js": "text/javascript",
      ".css": "text/css",
      ".html": "text/html",
      ".woff2": "font/woff2",
    };
    response.setHeader(
      "Content-Type",
      types[extname(file)] || "application/octet-stream",
    );
    response.end(await readFile(file));
  } catch {
    response.statusCode = 404;
    response.end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({
  headless: true,
  channel: "msedge",
  args: ["--disable-gpu"],
});
const cases = [];
const failures = [];
try {
  for (const [viewport, width, height] of [
    ["pc", 1440, 1000],
    ["phone", 390, 844],
  ]) {
    for (const [state, title] of [
      ["connected", "정상"],
      ["disconnected", "연결 끊김"],
      ["unknown", "확인 불가"],
      ["controller", "확인 불가"],
      ["unsupported", "확인 불가"],
      ["busy", "처리 중"],
      ["stopped", "중지"],
      ["heartbeat_lost", "연결 끊김"],
    ]) {
      const context = await browser.newContext({ viewport: { width, height } });
      const page = await context.newPage();
      const errors = [];
      const unexpected = [];
      let failObservation = false;
      page.on("pageerror", (error) => errors.push(error.message));
      const runtime = {
        agent_id: "analyze",
        observation_source: "amqp",
        revision: 0,
        enabled: null,
        replicas: null,
        ready_replicas: null,
        draining_replicas: null,
        manageable: false,
        runtime: state === "controller" ? "application_controller" : "amqp",
        state,
        consumers:
          state === "connected" ? 2 : state === "disconnected" ? 0 : null,
        messages_ready:
          state === "connected" ? 3 : state === "disconnected" ? 0 : null,
        activity: { running: 1, expired: 0, completed: 8 },
        observed_at: "2026-10-21T11:55:00Z",
        observations: [],
        instances: [],
        unavailable_reason: "원격 시작·중지·확장 제어 미연결",
        dependencies: [],
        max_replicas: 0,
        concurrency_per_instance: 1,
      };
      if (["connected", "busy", "stopped", "heartbeat_lost"].includes(state)) {
        runtime.telemetry = true;
        runtime.collector = { healthy: true };
        runtime.workers = [
          {
            worker_id: "a".repeat(32),
            boot_id: "b".repeat(32),
            family: "cpu",
            role: "analyze",
            state: state === "connected" ? "ready" : state,
            received_at: "2026-10-21T11:00:00Z",
            ticket_id: "c".repeat(32),
            ticket_number: 3,
            node_id: "analyze",
            attempt_id: "d".repeat(32),
            recent_events: [],
          },
        ];
      }
      await context.route("**/*", (route) => {
        const url = new URL(route.request().url());
        if (url.origin !== base) {
          unexpected.push("external");
          return route.abort();
        }
        if (!url.pathname.startsWith("/api/")) return route.continue();
        assert.equal(
          route.request().method(),
          "GET",
          "No control mutations in observation tests",
        );
        if (url.pathname === "/api/admin/agents/analyze" && failObservation) {
          return route.fulfill({
            status: 503,
            json: { detail: "controlled observation failure" },
          });
        }
        const routes = {
          "/api/auth/session": {
            enabled: true,
            backend: "postgres",
            setup_required: false,
            user: {
              id: "a".repeat(32),
              username: "isolated-ui-fixture",
              role: "admin",
            },
            csrf_token: "fixture-only",
          },
          "/api/capabilities": {
            backend: "postgres",
            features: [
              "agent_management",
              "verified_uploads",
              "workflows",
              "jobs",
              "node_runs",
            ],
            agent_runtime: "amqp_explicit",
            execution_enabled: true,
            model_network_enabled: false,
          },
          "/api/settings/node-catalog": {
            nodes: [
              {
                id: "analyze",
                label: "영상 분석",
                inputs: { video: "video" },
                outputs: { metadata: "media_metadata" },
                optional_inputs: [],
                options: {},
              },
            ],
          },
          "/api/admin/agents/analyze": runtime,
          "/api/admin/agents": { agents: [runtime] },
          "/api/videos": { videos: [] },
          "/api/jobs": { jobs: [] },
          "/api/video-uploads": { uploads: [] },
        };
        if (!(url.pathname in routes)) {
          unexpected.push(url.pathname);
          return route.fulfill({
            status: 500,
            json: { detail: "unhandled isolated fixture route" },
          });
        }
        return route.fulfill({ json: routes[url.pathname] });
      });
      try {
        await page.goto(base + "/#/agents/analyze");
        const panel = page.getByRole("region", {
          name: "에이전트 현황",
          exact: true,
        });
        await panel.waitFor({ timeout: 5000 });
        const badge = panel.getByRole("status");
        await badge.filter({ hasText: title }).waitFor();
        assert.equal(
          await panel.getByLabel("에이전트 활성화", { exact: true }).count(),
          0,
        );
        assert.equal(
          await panel.getByRole("button", { name: "설정 적용" }).count(),
          0,
        );
        assert.doesNotMatch(
          await page.locator("body").innerText(),
          /독립|AMQP|consumer|worker|heartbeat|lease|실행 경로|제공하지|작업 수용|등록된 물리 엔진/,
        );
        const body = await panel.innerText();
        if (state === "busy") assert.match(body, /#3/);
        if (state === "heartbeat_lost") assert.doesNotMatch(body, /#3/);
        if (state === "connected" || state === "busy")
          assert.match(body, /1개/);
        if (runtime.telemetry) {
          const instance = panel.locator(
            '[data-worker-id="' + "a".repeat(32) + '"]',
          );
          assert.equal(
            await instance.count(),
            1,
            "Show a real ID even for one instance",
          );
          await instance.locator("summary").click();
          assert.match(await instance.innerText(), new RegExp("a".repeat(32)));
          assert.doesNotMatch(await instance.innerText(), /에이전트 \d+/);
          await instance.locator("summary").click();
          const actualResponse = await page.evaluate(() =>
            new Date("2026-10-21T11:00:00Z").toLocaleString(),
          );
          assert.match(
            body,
            new RegExp(actualResponse.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
          );
        }
        await panel.scrollIntoViewIfNeeded();
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth + 1,
        );
        assert.equal(overflow, false);
        assert.deepEqual(errors, []);
        assert.deepEqual(unexpected, []);
        await page.screenshot({
          path: join(evidence, `${viewport}-${state}.png`),
        });
        cases.push({ viewport, state, overflow, errors });
        if (state === "connected") {
          failObservation = true;
          await badge.filter({ hasText: "확인 불가" }).waitFor();
          assert.equal(
            await panel.count(),
            1,
            "Keep AMQP mode during observation failure",
          );
          await badge.filter({ hasText: "확인 불가" }).waitFor();
          assert.equal(
            await panel
              .locator('[data-worker-id="' + "a".repeat(32) + '"]')
              .count(),
            1,
            "Retain the last known ID while observation is unavailable",
          );
          assert.equal(
            await page.getByLabel("에이전트 활성화", { exact: true }).count(),
            0,
          );
          assert.equal(
            await page.getByLabel("목표 실행 개수", { exact: true }).count(),
            0,
          );
          assert.equal(await badge.filter({ hasText: "정상" }).count(), 0);
          await page.screenshot({
            path: join(evidence, `${viewport}-refresh-failed.png`),
          });
          cases.push({ viewport, state: "refresh-failed", errors });
          failObservation = false;
          await badge.filter({ hasText: "정상" }).waitFor();
          assert.equal(
            await page.getByRole("alert").count(),
            0,
            "Recovered query clears old error",
          );
          await page.screenshot({
            path: join(evidence, `${viewport}-refresh-recovered.png`),
          });
          cases.push({ viewport, state: "refresh-recovered", errors });
        }
        await page.goto(base + "/#/agents");
        await page
          .getByLabel("영상 분석 상태", { exact: true })
          .getByText(title, { exact: true })
          .waitFor({ timeout: 5000 });
        cases.push({ viewport, state: "list-" + state, errors });
      } catch (error) {
        const body = await page.locator("body").innerText();
        failures.push({
          viewport,
          state,
          message: error.message,
          errors,
          unexpected,
          body,
        });
        await page.screenshot({
          path: join(evidence, `${viewport}-${state}-failure.png`),
        });
        throw error;
      } finally {
        await context.close();
      }
    }
  }
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
  await writeFile(
    join(evidence, "broker-observation-ui.json"),
    JSON.stringify(
      { scope: "ISOLATED_UI_CONTRACT_NOT_PRODUCT_RUNTIME", cases, failures },
      null,
      2,
    ),
  );
}
assert.equal(cases.length, 2 * (8 + 2 + 8));
console.log(JSON.stringify({ cases: cases.length, failures: failures.length }));
