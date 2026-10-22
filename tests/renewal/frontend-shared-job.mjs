// Permission presentation only: explicit contract fixture, NOT a product processing proof.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { resolve, extname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "../../apps/web/node_modules/@playwright/test/index.mjs";
const evidence = process.env.MIDEAGENT_SHARED_UI_EVIDENCE;
assert(evidence && process.env.MIDEAGENT_TEST_CATALOG);
await mkdir(evidence, { recursive: true });
const catalog = JSON.parse(
  await readFile(process.env.MIDEAGENT_TEST_CATALOG, "utf8"),
);
const dist = fileURLToPath(new URL("../../apps/web/dist/", import.meta.url));
const server = createServer(async (req, res) => {
  try {
    const p = new URL(req.url, "http://localhost").pathname;
    const file = resolve(dist, p === "/" ? "index.html" : "." + p);
    assert(
      file.startsWith(resolve(dist) + "/") ||
        file.startsWith(resolve(dist) + "\\"),
    );
    res.setHeader(
      "Content-Type",
      { ".js": "text/javascript", ".css": "text/css", ".html": "text/html" }[
        extname(file)
      ] || "application/octet-stream",
    );
    res.end(await readFile(file));
  } catch {
    res.statusCode = 404;
    res.end();
  }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true, channel: "msedge" });
const cases = [];
try {
  for (const [name, width, height] of [
    ["pc", 1440, 1000],
    ["phone", 390, 844],
  ]) {
    for (const own of [false, true]) {
      const context = await browser.newContext({ viewport: { width, height } });
      const page = await context.newPage();
      page.setDefaultTimeout(4000);
      const id = "d".repeat(32),
        actor = "c".repeat(32),
        source = "b".repeat(32);
      const state = {
        id,
        ticket_number: 1,
        revision: 1,
        status: "draft",
        parent_id: null,
        owner_id: own ? actor : "a".repeat(32),
        executed_by: own ? actor : "a".repeat(32),
        asset_owner_id: source,
        access: { can_manage: own },
        snapshot_redacted: true,
        snapshot: {
          asset: {
            asset_id: "e".repeat(32),
            original_filename: "isolated-shared-fixture.mp4",
            uploaded_by: source,
          },
          definition: {
            version: 1,
            name: "shared read-only contract fixture",
            inputs: { video: "video" },
            nodes: [
              {
                id: "encode",
                type: "encode",
                options: { subtitle_mode: "none" },
                position: { x: 80, y: 100 },
              },
            ],
            edges: [
              {
                id: "source-video",
                source: { node: "$input", port: "video" },
                target: { node: "encode", port: "video" },
              },
            ],
          },
        },
        runs: [],
        reviews: [],
      };
      const unexpected = [],
        errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      const ledger = {
        job_id: id,
        status: "pending",
        display_name: "contract fixture #1",
        workflow_definition: {
          execution_namespace: "renewal_job",
          frozen: state.snapshot.definition,
        },
        metadata: { asset_id: "e".repeat(32) },
      };
      await context.route("**/*", (route) => {
        const u = new URL(route.request().url());
        if (u.origin !== base) {
          unexpected.push("external");
          return route.abort();
        }
        if (!u.pathname.startsWith("/api/")) return route.continue();
        if (route.request().method() !== "GET") {
          unexpected.push("mutation");
          return route.fulfill({
            status: 403,
            json: { detail: "fixture forbids mutations" },
          });
        }
        const routes = {
          "/api/auth/session": {
            enabled: true,
            backend: "postgres",
            setup_required: false,
            user: {
              id: actor,
              username: "shared-reader-fixture",
              role: "user",
            },
            csrf_token: "fixture-only",
          },
          "/api/capabilities": {
            backend: "postgres",
            features: ["verified_uploads", "workflows", "jobs", "node_runs"],
            execution_enabled: true,
            model_network_enabled: false,
          },
          "/api/work-entry/catalog": catalog,
          "/api/settings/node-catalog": catalog,
          "/api/videos": { videos: [] },
          "/api/video-uploads": { uploads: [] },
          "/api/workflows": { workflows: [] },
          "/api/jobs": { jobs: [ledger] },
          ["/api/jobs/" + id]: ledger,
          ["/api/renewal/jobs/" + id]: state,
        };
        if (u.pathname === "/api/videos/" + "e".repeat(32) + "/thumbnail")
          return route.fulfill({ status: 404, body: "" });
        if (!(u.pathname in routes)) {
          unexpected.push(u.pathname);
          return route.fulfill({
            status: 404,
            json: { detail: "undefined fixture route" },
          });
        }
        return route.fulfill({ json: routes[u.pathname] });
      });
      try {
        await page.goto(base + "/#/jobs/" + id);
        await page
          .getByRole("button", { name: "새로고침", exact: true })
          .waitFor();
        if (!own) {
          await page.getByText("공용 읽기 전용", { exact: true }).waitFor();
          assert.equal(
            await page
              .getByRole("button", {
                name: /실행 계획 확인|취소 요청|새 작업으로 복구|검수 저장|검수 확정/,
              })
              .count(),
            0,
          );
        } else {
          assert.equal(
            await page
              .getByRole("button", { name: "실행 계획 확인", exact: true })
              .count(),
            1,
          );
        }
        assert.deepEqual(errors, []);
        assert.deepEqual(unexpected, []);
        assert(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= window.innerWidth + 1,
          ),
        );
        await page.screenshot({
          path: resolve(
            evidence,
            `${name}-${own ? "own" : "shared"}-fixture.png`,
          ),
          fullPage: true,
        });
        cases.push({ name, own, passed: true });
      } catch (error) {
        cases.push({
          name,
          own,
          passed: false,
          error: String(error),
          unexpected,
          errors,
        });
      } finally {
        await context.close();
      }
    }
  }
} finally {
  await browser.close();
  await new Promise((r) => server.close(r));
  await writeFile(
    resolve(evidence, "cases.json"),
    JSON.stringify(
      { scope: "PRODUCTION_BUNDLE_CONTRACT_FIXTURE_NOT_PRODUCT", cases },
      null,
      2,
    ),
  );
}
assert.equal(cases.filter((c) => !c.passed).length, 0, JSON.stringify(cases));
console.log(
  JSON.stringify({ scope: "CONTRACT_FIXTURE", passed: cases.length }),
);
