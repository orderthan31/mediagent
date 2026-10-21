// Production-bundle UI contracts only; no operating API or worker calls.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { resolve, extname, join, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "../../apps/web/node_modules/@playwright/test/index.mjs";
const out = process.env.MIDEAGENT_UI_EVIDENCE;
assert(out, "Explicit evidence directory required");
await mkdir(out, { recursive: true });
const dist = fileURLToPath(new URL("../../apps/web/dist/", import.meta.url));
const server = createServer(async (req, res) => {
  try {
    const file = resolve(
      dist,
      "." +
        (new URL(req.url, "http://localhost").pathname === "/"
          ? "/index.html"
          : new URL(req.url, "http://localhost").pathname),
    );
    assert(file.startsWith(resolve(dist) + sep));
    res.setHeader(
      "Content-Type",
      {
        ".js": "text/javascript",
        ".css": "text/css",
        ".html": "text/html",
        ".woff2": "font/woff2",
      }[extname(file)] || "application/octet-stream",
    );
    res.end(await readFile(file));
  } catch {
    res.writeHead(404);
    res.end();
  }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}`;
const jobId = "a".repeat(32),
  workflowId = "b".repeat(32);
const definition = {
  id: workflowId,
  name: "분류 확인",
  revision: 1,
  inputs: { video: "video" },
  nodes: [],
  edges: [],
};
const specs = [
  {
    id: "analyze",
    label: "영상 분석",
    inputs: { video: "video" },
    outputs: { metadata: "media_metadata" },
    options: {},
    optional_inputs: [],
  },
  {
    id: "control_if",
    label: "IF",
    inputs: { value: "video" },
    outputs: { true: "video", false: "video" },
    options: {},
    optional_inputs: [],
  },
  {
    id: "control_switch",
    label: "Switch",
    inputs: { value: "video" },
    outputs: { default: "video" },
    options: {},
    optional_inputs: [],
  },
  {
    id: "review",
    label: "사람 검수",
    inputs: { value: "video" },
    outputs: { value: "video" },
    options: { data_type: ["video"] },
    optional_inputs: [],
  },
];
const routes = {
  "/api/auth/session": {
    enabled: true,
    backend: "postgres",
    setup_required: false,
    user: { id: "f".repeat(32), username: "isolated-ui", role: "admin" },
    csrf_token: "fixture-only",
  },
  "/api/capabilities": {
    backend: "postgres",
    features: [
      "verified_uploads",
      "agent_management",
      "workflows",
      "jobs",
      "node_runs",
    ],
    model_network_enabled: false,
  },
  "/api/videos": { videos: [] },
  "/api/video-uploads": { uploads: [] },
  ["/api/videos/" + "c".repeat(32)]: {
    video: {
      asset_id: "c".repeat(32),
      original_filename: "preview-layout.mp4",
      size_bytes: 4265166,
      created_at: "2026-10-21T10:00:00Z",
      provenance: { kind: "upload" },
      media: { duration: 4, width: 1280, height: 720 },
      web_preview: { status: "ready" },
    },
    jobs: [],
  },
  ["/api/videos/" + "c".repeat(32) + "/subtitles"]: { subtitles: [] },
  "/api/legacy/history": { records: [], total: 0 },
  "/api/work-entry/workflows": { definitions: [] },
  "/api/accounts": {
    accounts: [
      {
        id: "f".repeat(32),
        username: "isolated-ui",
        role: "admin",
        created_at: "2026-10-21T10:00:00Z",
      },
    ],
  },
  "/api/jobs": {
    jobs: [
      {
        job_id: jobId,
        ticket_number: "#42",
        original_filename: "row-target.mp4",
        status: "COMPLETED",
        created_at: "2026-10-21T10:00:00Z",
        metadata: { workflow: { name: "행 이동 확인" } },
      },
    ],
  },
  ["/api/renewal/jobs/" + jobId]: {
    id: jobId,
    ticket_number: 42,
    revision: 1,
    status: "completed",
    parent_id: null,
    snapshot: {
      asset: { asset_id: "c".repeat(32), original_filename: "row-target.mp4" },
      definition,
    },
    runs: [],
    reviews: [],
  },
  "/api/settings/node-catalog": { nodes: specs },
  "/api/work-entry/catalog": { nodes: specs },
  "/api/settings/workflow-definitions": {
    definitions: [{ id: workflowId, name: definition.name, revision: 1 }],
  },
  ["/api/settings/workflow-definitions/" + workflowId]: definition,
  "/api/settings/registered-models": { models: [], providers: {} },
  "/api/settings/serving-connections": { connections: [], providers: {} },
  "/api/admin/agents": { agents: [] },
  "/api/admin/agents/analyze": {
    agent_id: "analyze",
    state: "ready",
    observation_source: "amqp",
    telemetry: true,
    collector: { healthy: true },
    workers: [
      {
        worker_id: "d".repeat(32),
        state: "ready",
        received_at: "2026-10-21T11:00:00Z",
        ticket_id: null,
        ticket_number: null,
      },
    ],
    revision: 0,
    enabled: null,
    replicas: null,
    instances: [],
    max_replicas: 0,
    dependencies: [],
    manageable: false,
  },
};
const browser = await chromium.launch({
  headless: true,
  channel: "msedge",
  args: ["--disable-gpu"],
});
definition.nodes = specs.map((s, i) => ({
  id: "node-" + i,
  type: s.id,
  position: { x: 330 + i * 270, y: 100 },
  options: s.id === "review" ? { data_type: "video" } : {},
}));
definition.edges = definition.nodes.map((n, i) => ({
  id: "edge-" + i,
  source: { node: "$input", port: "video" },
  target: { node: n.id, port: i === 0 ? "video" : "value" },
}));
const results = [],
  failures = [];
async function runCase(viewport, name, check) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  page.setDefaultTimeout(6000);
  const errors = [],
    unexpected = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await context.route("**/*", async (route) => {
    const u = new URL(route.request().url());
    if (u.origin !== base) {
      unexpected.push("external");
      return route.abort();
    }
    if (!u.pathname.startsWith("/api/")) return route.continue();
    if (u.pathname === "/api/videos/" + "c".repeat(32) + "/thumbnail")
      return route.fulfill({ status: 404, body: "" });
    if (!(u.pathname in routes)) {
      unexpected.push(u.pathname);
      return route.fulfill({
        status: 500,
        json: { detail: "Unhandled fixture route" },
      });
    }
    return route.fulfill({ json: routes[u.pathname] });
  });
  try {
    await check(page, context);
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpected, []);
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth + 1,
      ),
      false,
    );
    await page.screenshot({ path: join(out, `${viewport.width}-${name}.png`) });
    results.push({ width: viewport.width, name, passed: true });
  } catch (e) {
    failures.push({
      width: viewport.width,
      name,
      error: String(e),
      errors,
      unexpected,
      body: await page.locator("body").innerText(),
    });
    await page.screenshot({
      path: join(out, `${viewport.width}-${name}-failed.png`),
    });
    throw e;
  } finally {
    await context.close();
  }
}
try {
  for (const viewport of [
    { width: 1440, height: 1000 },
    { width: 390, height: 844 },
  ]) {
    await runCase(viewport, "original-initial-loading", async (page) => {
      let release;
      const gate = new Promise((r) => (release = r));
      await page.route("**/api/videos", async (route) => {
        await gate;
        await route.fulfill({ json: { videos: [] } });
      });
      try {
        await page.goto(base + "/#/");
        await page.locator('[data-skeleton="list"]').waitFor();
        assert.equal(
          await page
            .getByText("등록된 원본 영상이 없습니다.", { exact: true })
            .count(),
          0,
        );
        await page.screenshot({
          path: join(out, `${viewport.width}-original-loading.png`),
        });
      } finally {
        release();
      }
      await page
        .getByText("등록된 원본 영상이 없습니다.", { exact: true })
        .waitFor();
      assert.equal(await page.locator("[data-skeleton]").count(), 0);
    });
    await runCase(viewport, "job-row", async (page) => {
      await page.goto(base + "/#/jobs");
      const row = page
        .locator(".job-ledger tbody tr")
        .filter({ hasText: "row-target.mp4" });
      await row.locator("td").nth(1).click();
      await page.waitForURL("**/#/jobs/" + jobId);
      await page.getByText("작업 #42", { exact: true }).waitFor();
      for (const key of ["Enter", "Space"]) {
        await page.goto(base + "/#/jobs");
        await row.waitFor();
        await row.focus();
        await row.press(key);
        await page.waitForURL("**/#/jobs/" + jobId);
      }
      await page.goto(base + "/#/jobs");
      await row.waitFor();
      await row.evaluate((el) => {
        const td = el.children[1];
        td.insertAdjacentHTML(
          "beforeend",
          '<button type="button" id="row-action">독립 조작</button><input type="checkbox" aria-label="선택 검증"><a href="#/jobs" id="row-download" download>다운로드 검증</a>',
        );
      });
      await page.locator("#row-action").click();
      assert.equal(new URL(page.url()).hash, "#/jobs");
      await row.locator("input").check();
      assert.equal(new URL(page.url()).hash, "#/jobs");
      await row
        .locator("td")
        .nth(1)
        .click({ modifiers: ["Control"] });
      assert.equal(new URL(page.url()).hash, "#/jobs");
      await row.locator("td").nth(4).click();
      await page.waitForURL("**/#/jobs/" + jobId);
    });
    await runCase(viewport, "get-layouts", async (page) => {
      for (const [hash, path, layout] of [
        ["#/", "/api/capabilities", "list"],
        ["#/jobs", "/api/jobs", "table"],
        [
          "#/videos/" + "c".repeat(32),
          "/api/videos/" + "c".repeat(32),
          "media",
        ],
        ["#/jobs/" + jobId, "/api/renewal/jobs/" + jobId, "canvas"],
        ["#/workflows", "/api/settings/workflow-definitions", "list"],
        [
          "#/workflows/" + workflowId,
          "/api/settings/workflow-definitions/" + workflowId,
          "canvas",
        ],
        ["#/agents", "/api/settings/node-catalog", "list"],
        ["#/agents/analyze", "/api/admin/agents/analyze", "agent"],
        ["#/serving", "/api/settings/registered-models", "list"],
        ["#/serving/new", "/api/settings/registered-models", "form"],
        ["#/serving/connections", "/api/settings/serving-connections", "list"],
        [
          "#/serving/connections/new",
          "/api/settings/serving-connections",
          "form",
        ],
        ["#/start", "/api/work-entry/workflows", "form"],
        ["#/account", "/api/accounts", "list"],
      ]) {
        let release;
        const gate = new Promise((r) => (release = r));
        const pattern = "**" + path;
        await page.route(pattern, async (route) => {
          await gate;
          await route.fulfill({ json: routes[path] });
        });
        try {
          // Hash-only navigation intentionally reuses already loaded lists.
          // Use a fresh document to test an actual initial GET, not cached navigation.
          await page.goto("about:blank");
          await page.goto(base + "/" + hash);
          await page.locator('[data-skeleton="' + layout + '"]').waitFor();
          await page.screenshot({
            path: join(
              out,
              `${viewport.width}-loading-${hash.replaceAll(/[^a-z0-9]/gi, "_")}.png`,
            ),
          });
        } finally {
          release();
        }
        await page.locator("[data-skeleton]").waitFor({ state: "detached" });
        await page.unroute(pattern);
      }
    });
    await runCase(viewport, "initial-failure-not-empty", async (page) => {
      await page.route("**/api/jobs", (route) =>
        route.fulfill({
          status: 503,
          json: { detail: "controlled initial failure" },
        }),
      );
      await page.goto(base + "/#/jobs");
      await page
        .getByRole("alert")
        .filter({ hasText: "목록 조회 실패" })
        .waitFor();
      assert.equal(
        await page.getByText("작업이 없습니다.", { exact: true }).count(),
        0,
      );
      assert.equal(await page.locator("[data-skeleton]").count(), 0);
      await page.unroute("**/api/jobs");
      await page
        .locator(".job-ledger tbody tr")
        .filter({ hasText: "row-target.mp4" })
        .waitFor();
    });
    await runCase(viewport, "refresh-keeps-content", async (page) => {
      await page.goto(base + "/#/jobs");
      const row = page
        .locator(".job-ledger tbody tr")
        .filter({ hasText: "row-target.mp4" });
      await row.waitFor();
      let release;
      const gate = new Promise((r) => (release = r));
      await page.route("**/api/jobs", async (route) => {
        await gate;
        await route.fulfill({
          status: 503,
          json: { detail: "controlled refresh failure" },
        });
      });
      try {
        await page.waitForTimeout(3000);
        assert.equal(await row.count(), 1);
        assert.equal(await page.locator("[data-skeleton]").count(), 0);
      } finally {
        release();
      }
      await page
        .getByRole("alert")
        .filter({ hasText: "목록 갱신 실패" })
        .waitFor();
      assert.equal(await row.count(), 1);
      await page.unroute("**/api/jobs");
      await page
        .getByRole("alert")
        .filter({ hasText: "목록 갱신 실패" })
        .waitFor({ state: "detached" });
      assert.equal(await row.count(), 1);
    });
    await runCase(viewport, "node-kinds", async (page) => {
      await page.goto(base + "/#/agents");
      await page.locator(".ui02-agent-row").first().waitFor();
      assert.equal(
        await page.locator(".ui02-agent-row").count(),
        1,
        "Only processing agents belong in the agent catalog",
      );
      await page.goto(base + "/#/workflows/" + workflowId);
      await page.locator('[data-node-id="node-3"]').waitFor();
      for (const [id, kind, icon] of [
        ["node-0", "agent", "boxes"],
        ["node-1", "control", "git-branch"],
        ["node-2", "control", "git-branch"],
        ["node-3", "review", "user-round-check"],
      ]) {
        const n = page.locator('[data-node-id="' + id + '"]');
        assert.equal(await n.getAttribute("data-node-kind"), kind);
        assert.equal(await n.locator(".lucide-" + icon).count(), 1);
      }
      const before = await page
        .locator(".workflow-graph-node")
        .evaluateAll((ns) =>
          ns.map((n) => ({
            id: n.dataset.nodeId,
            style: n.getAttribute("style"),
          })),
        );
      for (const [name, labels, icon] of [
        ["에이전트 추가", ["영상 분석"], "boxes"],
        ["제어 노드 추가", ["IF", "Switch"], "git-branch"],
        ["사람 검수 추가", ["사람 검수"], "user-round-check"],
      ]) {
        await page.getByRole("button", { name, exact: true }).click();
        const menu = page.getByRole("group", {
          name: "추가할 노드",
          exact: true,
        });
        assert.deepEqual(
          await menu.locator("button").allTextContents(),
          labels,
        );
        assert.equal(
          await menu.locator(".lucide-" + icon).count(),
          labels.length,
        );
      }
      assert.doesNotMatch(
        await page.locator(".workflow-save-state").innerText(),
        /미저장/,
      );
      assert.deepEqual(
        await page.locator(".workflow-graph-node").evaluateAll((ns) =>
          ns.map((n) => ({
            id: n.dataset.nodeId,
            style: n.getAttribute("style"),
          })),
        ),
        before,
      );
      await page.goto(base + "/#/jobs/" + jobId);
      await page.locator('[data-node-id="node-3"]').waitFor();
      assert.equal(
        await page
          .locator('[data-node-id="node-3"] .lucide-user-round-check')
          .count(),
        1,
        "Execution uses the same human-review icon",
      );
      assert.equal(
        await page
          .locator('[data-node-id="node-1"] .lucide-git-branch')
          .count(),
        1,
      );
    });
    await runCase(viewport, "individual-identity", async (page, context) => {
      await context.grantPermissions(["clipboard-read", "clipboard-write"]);
      const original = routes["/api/admin/agents/analyze"];
      const first = original.workers[0];
      routes["/api/admin/agents/analyze"] = {
        ...original,
        workers: [
          first,
          {
            ...first,
            worker_id: "e".repeat(32),
            state: "busy",
            ticket_id: jobId,
            ticket_number: 42,
          },
        ],
      };
      try {
        await page.goto(base + "/#/agents/analyze");
        const one = page.locator('[data-worker-id="' + "d".repeat(32) + '"]');
        const two = page.locator('[data-worker-id="' + "e".repeat(32) + '"]');
        await one.waitFor();
        await two.waitFor();
        assert.doesNotMatch(await one.innerText(), /#42/);
        assert.match(await two.innerText(), /#42/);
        await one
          .getByRole("button", {
            name: "실행 ID 복사: " + "d".repeat(32),
            exact: true,
          })
          .click();
        assert.equal(
          await page.evaluate(() => navigator.clipboard.readText()),
          "d".repeat(32),
        );
        await two.locator("summary").click();
        assert.match(await two.innerText(), new RegExp("e".repeat(32)));
        await two
          .getByRole("button", {
            name: "실행 ID 복사: " + "e".repeat(32),
            exact: true,
          })
          .click();
        assert.equal(
          await page.evaluate(() => navigator.clipboard.readText()),
          "e".repeat(32),
        );
        if (viewport.width < 700) {
          const cellsVisible = await two.locator("td").evaluateAll((cells) =>
            cells.every((cell) => {
              const rect = cell.getBoundingClientRect();
              return rect.left >= 0 && rect.right <= innerWidth;
            }),
          );
          assert(
            cellsVisible,
            "Mobile identity, state and work must remain readable together",
          );
        }
        routes["/api/admin/agents/analyze"] = {
          ...routes["/api/admin/agents/analyze"],
          state: "unknown",
          collector: { healthy: false },
        };
        await two.getByText("확인 불가", { exact: true }).first().waitFor();
        assert.equal(
          await page.getByRole("link", { name: "#42", exact: true }).count(),
          0,
          "Hide old busy work when collection is unavailable",
        );
        assert.equal(await one.count(), 1);
        assert.equal(await two.count(), 1);
      } finally {
        routes["/api/admin/agents/analyze"] = original;
      }
    });
  }
} finally {
  await browser.close();
  await new Promise((r) => server.close(r));
  await writeFile(
    join(out, "result.json"),
    JSON.stringify(
      {
        scope: "ISOLATED_UI_CONTRACT_NOT_OPERATING_RUNTIME",
        results,
        failures,
      },
      null,
      2,
    ),
  );
}
console.log(JSON.stringify({ results, failures }));
