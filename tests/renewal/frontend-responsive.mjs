// Explicit DEV-only synthetic viewport QA, not a real Fold hardware test.
// Physical panel pixels are NOT CSS viewport dimensions. These cover/unfolded
// probes assume DPR=3 and include shorter browser-chrome and adjacent-size cases.
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { listGeometry } from "./list-geometry.mjs";
import { chromium } from "../../apps/web/node_modules/@playwright/test/index.mjs";
const base = process.env.MIDEAGENT_PREVIEW_ORIGIN;
const evidence = process.env.MIDEAGENT_PREVIEW_EVIDENCE_DIR;
assert(base && new URL(base).protocol === "http:" && evidence);
await mkdir(evidence, { recursive: true });
const viewports = [
  { name: "cover-portrait", width: 416, height: 657, dpr: 3, primary: true },
  {
    name: "unfolded-landscape",
    width: 816,
    height: 616,
    dpr: 3,
    primary: true,
  },
  { name: "pc-fhd", width: 1920, height: 1080, dpr: 1, primary: true },
  { name: "cover-browser-chrome", width: 416, height: 577, dpr: 3 },
  { name: "unfolded-browser-chrome", width: 816, height: 536, dpr: 3 },
  { name: "minimum-phone", width: 320, height: 640, dpr: 3 },
  { name: "adjacent-phone", width: 390, height: 844, dpr: 3 },
  { name: "adjacent-unfolded", width: 896, height: 768, dpr: 3 },
  { name: "pc-compact", width: 1440, height: 900, dpr: 1 },
];
const browser = await chromium.launch({ headless: true });
const results = [];
const interactions = [];
const failures = [];
const save = () =>
  writeFile(
    join(evidence, "responsive.json"),
    JSON.stringify({ viewports, results, interactions, failures }, null, 2),
  );
const geometry = (page) =>
  page.evaluate(() => {
    const rect = (e) => {
      const b = e.getBoundingClientRect();
      return {
        x: b.x,
        y: b.y,
        w: b.width,
        h: b.height,
        right: b.right,
        bottom: b.bottom,
      };
    };
    const outside = [...document.querySelectorAll("main *, .ui02-gnb *")]
      .filter((e) => {
        const b = e.getBoundingClientRect();
        if (
          !b.width ||
          !b.height ||
          getComputedStyle(e).position === "absolute" ||
          e.closest(
            ".workflow-graph-world, .job-ledger-scroll, dialog, [popover]:not(:popover-open)",
          )
        )
          return false;
        return b.right > innerWidth + 1 || b.left < -1;
      })
      .slice(0, 15)
      .map((e) => ({
        tag: e.tagName,
        cls: typeof e.className === "string" ? e.className : "svg",
        ...rect(e),
      }));
    const canvasControlOverlaps = [
      ...document.querySelectorAll(".workflow-graph-viewport"),
    ].flatMap((canvas) => {
      const controls = [
        ...canvas.querySelectorAll(
          ".workflow-graph-controls, .workflow-agent-picker > button",
        ),
      ].map((e) => e.getBoundingClientRect());
      return [...canvas.querySelectorAll(".workflow-graph-node")]
        .filter((node) => {
          const r = node.getBoundingClientRect();
          return controls.some(
            (c) =>
              r.left < c.right &&
              r.right > c.left &&
              r.top < c.bottom &&
              r.bottom > c.top,
          );
        })
        .map((node) => node.dataset.nodeId);
    });
    return {
      canvasControlOverlaps,
      overflow: document.documentElement.scrollWidth - innerWidth,
      main: rect(document.querySelector("main")),
      brand: rect(document.querySelector(".ui02-brand-group")),
      actions: rect(document.querySelector(".ui02-page-actions")),
      outside,
      footers: [
        ...document.querySelectorAll(
          "main .page-actions, main .list-pagination",
        ),
      ].map((e) => ({ ...rect(e), position: getComputedStyle(e).position })),
    };
  });
const visit = async (page, route) => {
  await page.goto(base + "/#/" + route);
  await page.locator("main").waitFor();
  await page.waitForTimeout(160);
  await page.evaluate(() => scrollTo(0, 0));
};
const swipe = async (page, selector, dx, dy) => {
  const box = await page.locator(selector).boundingBox();
  const session = await page.context().newCDPSession(page);
  const x = box.x + box.width * 0.65,
    y = box.y + box.height * 0.7;
  await session.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [{ x, y }],
  });
  for (let step = 1; step <= 10; step++) {
    await session.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [{ x: x + (dx * step) / 10, y: y + (dy * step) / 10 }],
    });
    await page.waitForTimeout(18);
  }
  await session.send("Input.dispatchTouchEvent", {
    type: "touchEnd",
    touchPoints: [],
  });
  await page.waitForTimeout(150);
  await session.detach();
};
try {
  for (const v of viewports) {
    const context = await browser.newContext({
      viewport: { width: v.width, height: v.height },
      deviceScaleFactor: v.dpr,
      isMobile: v.dpr > 1,
      hasTouch: v.dpr > 1,
    });
    const page = await context.newPage();
    const errors = [],
      network = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await context.route("**/*", (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== base || url.pathname.startsWith("/api/")) {
        network.push(url.origin + url.pathname);
        return route.abort();
      }
      return route.continue();
    });
    await visit(page, "jobs");
    await page.locator(".list-pagination").waitFor();
    const fixture = await page.evaluate(() =>
      JSON.parse(sessionStorage.getItem("mideagent-publishing-fixtures-v1")),
    );
    assert.equal(
      fixture?.publishingContractVersion,
      1,
      "DEV-only synthetic preview required",
    );
    await page.evaluate(() =>
      sessionStorage.setItem(
        "mideagent-publishing-accounts-v1",
        JSON.stringify({
          accounts: [
            {
              id: "synthetic-admin",
              username: "synthetic-admin",
              role: "admin",
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
          currentId: "synthetic-admin",
        }),
      ),
    );
    await page.reload();
    await visit(page, "agents");
    await page.locator(".ui02-agent-row").first().waitFor();
    const agents = await page
      .locator(".ui02-agent-row")
      .evaluateAll((rows) => rows.map((e) => e.getAttribute("href").slice(2)));
    const routes = [
      ...new Set([
        "jobs",
        "start",
        "", // Original list is #/, not the unknown #/storage fallback.
        "videos/" + fixture.videos[0].asset_id,
        "jobs/" + fixture.jobs[0].job_id,
        "workflows",
        "workflows/new",
        "workflows/" + fixture.definitions[0].id,
        "agents",
        ...agents,
        "serving",
        "serving/new",
        "serving/" + fixture.models[0].id,
        "serving/" + fixture.models[0].id + "/edit",
        "serving/connections",
        "serving/connections/new",
        "serving/connections/" + fixture.connections[0].id,
        "serving/connections/" + fixture.connections[0].id + "/edit",
        "settings",
        "account",
        "account/new",
      ]),
    ];
    for (const route of routes) {
      try {
        await visit(page, route);
        if (route === "") {
          assert.match(
            await page.title(),
            /원본/,
            "Original-list root must retain its navigation context",
          );
        }
        if (route === "start") {
          await page
            .getByLabel("원본", { exact: true })
            .selectOption(fixture.videos[0].asset_id);
          await page
            .getByLabel("워크플로우", { exact: true })
            .selectOption(fixture.definitions[0].id);
          await page
            .locator(".entry-workflow .workflow-graph-viewport")
            .waitFor();
        }
        if (route === "account/new")
          assert.equal(
            await page.locator(".account-create").count(),
            1,
            "Must inspect actual admin form, not anonymous fallback",
          );
        await page.waitForTimeout(60);
        const g = await geometry(page);
        assert(g.overflow <= 1, `Document overflow ${g.overflow}`);
        assert.deepEqual(
          g.canvasControlOverlaps,
          [],
          "Fit must leave controls clear of nodes",
        );
        assert.deepEqual(g.outside, [], "Out-of-bounds layout");
        const lists = await listGeometry(page);
        assert.deepEqual(
          lists.violations,
          [],
          "List content crosses row padding or divider",
        );
        assert(g.brand.right <= g.actions.x + 1, "GNB title overlaps actions");
        for (const footer of g.footers)
          assert.equal(footer.position, "static", "No overlaying footer");
        const pager = page.locator(".list-pagination");
        if (await pager.count()) {
          assert.equal(
            await pager
              .locator("label")
              .first()
              .evaluate((e) => getComputedStyle(e).flexDirection),
            "row",
          );
          assert((await pager.first().boundingBox()).height > 0);
        }
        const actionBar = page.locator("main .page-actions");
        if (await actionBar.count()) {
          const ordering = await actionBar.first().evaluate((e) => ({
            top: e.getBoundingClientRect().top,
            previousBottom:
              e.previousElementSibling?.getBoundingClientRect().bottom || 0,
          }));
          assert(
            ordering.top >= ordering.previousBottom - 1,
            "Actions must follow content, never cover it",
          );
          await actionBar.first().scrollIntoViewIfNeeded();
          const b = await actionBar.first().boundingBox();
          assert(
            b.y >= 64 && b.y + b.height <= v.height + 1,
            "Actions must be reachable",
          );
          if (v.primary)
            await page.screenshot({
              path: join(
                evidence,
                v.name + "-" + route.replaceAll("/", "-") + "-actions.png",
              ),
              scale: "css",
            });
          await page.evaluate(() => scrollTo(0, 0));
        }
        if (
          v.primary &&
          [
            "jobs",
            "start",
            "serving/new",
            "account/new",
            "workflows/new",
            "settings",
            "serving/connections",
          ].includes(route)
        ) {
          await page.screenshot({
            path: join(
              evidence,
              v.name + "-" + route.replaceAll("/", "-") + ".png",
            ),
            scale: "css",
          });
        }
        results.push({ viewport: v.name, route, ...g, passed: true });
      } catch (error) {
        failures.push({ viewport: v.name, route, error: error.message });
        await page.screenshot({
          path: join(
            evidence,
            "failure-" + v.name + "-" + route.replaceAll("/", "-") + ".png",
          ),
          scale: "css",
        });
      }
      await save();
    }
    // Native menu, popover, horizontal table scroll, node result scroll and
    // 0/1/45-row pagination are separate from static viewport captures.
    try {
      await visit(page, "jobs");
      const menu = page.locator(".ui02-brand-group > button");
      if (v.width < 768) {
        await menu.click();
        await page.locator("dialog[open]").waitFor();
        assert.equal(await page.locator("dialog[open] nav a").count(), 7);
        await page
          .getByRole("button", { name: "메뉴 닫기", exact: true })
          .click();
        assert.equal(await page.locator("dialog[open]").count(), 0);
      } else {
        const before = await page.locator("main").boundingBox();
        await menu.click();
        const after = await page.locator("main").boundingBox();
        assert.notEqual(
          before.x,
          after.x,
          "Collapsible LNB must change available width",
        );
        await menu.click();
      }
      await page
        .getByRole("button", { name: "실행 관리", exact: true })
        .click();
      await page.locator("#execution-controls:popover-open").waitFor();
      await page.getByRole("button", { name: "실행 관리 닫기" }).click();
      assert.equal(
        await page.locator("#execution-controls").isVisible(),
        false,
        "Closed popover must not inherit pagination flex display",
      );
      const ledger = page.locator(".job-ledger-scroll");
      if (await ledger.evaluate((e) => e.scrollWidth > e.clientWidth)) {
        if (v.dpr > 1) await swipe(page, ".job-ledger-scroll", -180, 0);
        else {
          const b = await ledger.boundingBox();
          await page.mouse.move(b.x + 50, b.y + 50);
          await page.mouse.wheel(300, 0);
          await page.waitForTimeout(100);
        }
        assert(
          await ledger.evaluate((e) => e.scrollLeft > 0),
          "Table must scroll horizontally",
        );
      }
      await visit(page, "workflows/new");
      await page
        .getByRole("button", { name: "에이전트 추가", exact: true })
        .click();
      const picker = page.locator(".workflow-agent-menu");
      const menuBox = await picker.boundingBox();
      assert(menuBox.x >= 0 && menuBox.x + menuBox.width <= v.width);
      if (
        v.dpr > 1 &&
        (await picker.evaluate((e) => e.scrollHeight > e.clientHeight))
      ) {
        await swipe(page, ".workflow-agent-menu", 0, -100);
        assert(
          await picker.evaluate((e) => e.scrollTop > 0),
          "Touch must scroll agent picker inside canvas",
        );
      }
      await page
        .getByRole("button", { name: "에이전트 추가", exact: true })
        .click();
      await page
        .locator('[data-node-id="$input"] .workflow-node-heading')
        .click();
      await page
        .getByRole("region", { name: "노드 설정", exact: true })
        .waitFor();
      await visit(page, "jobs/" + fixture.jobs[0].job_id);
      await page
        .locator('[data-node-id="prepare"] .workflow-node-heading')
        .click();
      const panel = page.getByRole("region", {
        name: "노드 실행 상세",
        exact: true,
      });
      await panel
        .locator("summary")
        .filter({ hasText: "실제 적용 설정" })
        .click();
      await panel.locator("summary").filter({ hasText: "입력 자료" }).click();
      await panel.scrollIntoViewIfNeeded();
      await page.waitForTimeout(100);
      const pb = await panel.boundingBox();
      const scrollRoom = await panel.evaluate(
        (e) => e.scrollHeight - e.clientHeight,
      );
      assert(scrollRoom > 0);
      await page.mouse.move(pb.x + pb.width - 15, pb.y + pb.height * 0.7);
      await page.mouse.wheel(0, 450);
      await page.waitForTimeout(120);
      assert(
        await panel.evaluate((e) => e.scrollTop > 0),
        "Native wheel must scroll selected node",
      );
      if (v.dpr > 1) {
        await panel.evaluate((e) => {
          e.scrollTop = 0;
        });
        await swipe(
          page,
          ".workflow-node-settings",
          0,
          -Math.min(130, pb.height * 0.4),
        );
        assert(
          await panel.evaluate((e) => e.scrollTop > 0),
          "Touch must scroll selected node",
        );
      }
      if (v.primary)
        await page.screenshot({
          path: join(evidence, v.name + "-node-result.png"),
          scale: "css",
        });
      for (const [route, key, idField] of [
        ["jobs", "jobs", "job_id"],
        ["", "videos", "asset_id"],
        ["workflows", "definitions", "id"],
        ["serving", "models", "id"],
        ["serving/connections", "connections", "id"],
      ]) {
        const bottoms = [];
        for (const count of [0, 1, 45]) {
          await page.evaluate(
            ({ fixture, count, key, idField, route }) => {
              const state = structuredClone(fixture);
              state[key] = Array.from({ length: count }, (_, i) => ({
                ...structuredClone(fixture[key][0]),
                [idField]: (i + 1000).toString(16).padStart(32, "0"),
              }));
              sessionStorage.setItem(
                "mideagent-publishing-fixtures-v1",
                JSON.stringify(state),
              );
              location.hash = "/" + route;
            },
            { fixture, count, key, idField, route },
          );
          await page.reload();
          await page.locator(".list-pagination").waitFor();
          const b = await page.locator(".list-pagination").boundingBox();
          bottoms.push(Math.round(b.y + b.height));
          assert(b.y >= 64 && b.y + b.height <= v.height + 1);
          assert((await geometry(page)).overflow <= 1);
          assert.deepEqual(
            (await listGeometry(page)).violations,
            [],
            "Paginated rows must contain their children",
          );
          if (count === 45) {
            await page
              .getByLabel("페이지 선택", { exact: true })
              .selectOption("3");
            assert.match(
              await page.locator(".list-pagination").innerText(),
              /41–45/,
            );
          }
        }
        assert(
          Math.max(...bottoms) - Math.min(...bottoms) <= 2,
          `${route} data-dependent footer: ${bottoms}`,
        );
      }
      // Very long user content must shrink the title, not hide/overlap controls.
      await page.evaluate((fixture) => {
        const state = structuredClone(fixture);
        state.videos[0].original_filename =
          "긴원본파일이름".repeat(22) + ".mp4";
        state.connections[0].name = "긴공용연결".repeat(16);
        state.connections[0].endpoint =
          "https://example.invalid/" + "long-path/".repeat(30);
        sessionStorage.setItem(
          "mideagent-publishing-fixtures-v1",
          JSON.stringify(state),
        );
      }, fixture);
      for (const route of [
        "videos/" + fixture.videos[0].asset_id,
        "serving/connections",
        "serving/connections/" + fixture.connections[0].id,
      ]) {
        await visit(page, route);
        await page.reload();
        await page.waitForTimeout(150);
        const g = await geometry(page);
        assert(
          g.overflow <= 1 &&
            g.brand.right <= g.actions.x + 1 &&
            !g.outside.length,
          "Long content must be contained",
        );
      }
      if (v.name === "cover-portrait") {
        await visit(page, "workflows/new");
        await page
          .getByLabel("워크플로우 이름", { exact: true })
          .fill("접힘 전환 점검");
        await page
          .locator('[data-node-id="$input"] .workflow-node-heading')
          .click();
        await page
          .getByRole("button", { name: "메뉴 열기", exact: true })
          .click();
        for (const size of [
          { width: 816, height: 616 },
          { width: 1920, height: 1080 },
          { width: 416, height: 657 },
        ]) {
          await page.setViewportSize(size);
          await page.waitForTimeout(120);
          assert.equal(
            await page
              .getByLabel("워크플로우 이름", { exact: true })
              .inputValue(),
            "접힘 전환 점검",
          );
          assert.equal(
            await page.locator('[data-node-id="$input"].is-selected').count(),
            1,
          );
          assert.equal(await page.locator("dialog[open]").count(), 0);
          const g = await geometry(page);
          assert(g.overflow <= 1 && !g.outside.length);
          assert.equal(g.main.x, size.width < 768 ? 0 : 64);
        }
      }
      for (const route of ["setup", "login"]) {
        await page.evaluate((route) => {
          const accounts =
            route === "setup"
              ? []
              : [
                  {
                    id: "synthetic-admin",
                    username: "synthetic-admin",
                    role: "admin",
                    created_at: "2026-01-01T00:00:00Z",
                  },
                ];
          sessionStorage.setItem(
            "mideagent-publishing-accounts-v1",
            JSON.stringify({ accounts, currentId: null }),
          );
          location.hash = "/" + route;
        }, route);
        await page.reload();
        await page.locator(".access-form form").waitFor();
        const auth = await page.evaluate(() => ({
          overflow: document.documentElement.scrollWidth - innerWidth,
          outside: [
            ...document.querySelectorAll(
              ".access-form input,.access-form button",
            ),
          ].filter((e) => {
            const b = e.getBoundingClientRect();
            return b.left < 0 || b.right > innerWidth + 1;
          }).length,
        }));
        assert(auth.overflow <= 1 && auth.outside === 0, "Auth form layout");
        results.push({
          viewport: v.name,
          route,
          auth: true,
          ...auth,
          passed: true,
        });
      }
      assert.deepEqual(errors, []);
      assert.deepEqual(network, [], "No API/provider/external network calls");
      interactions.push({
        viewport: v.name,
        menu: true,
        queue_popover: true,
        local_table_scroll: true,
        node_wheel: true,
        node_touch: v.dpr > 1,
        stable_paginations: true,
        long_content: true,
      });
    } catch (error) {
      failures.push({
        viewport: v.name,
        route: "interactions",
        error: error.message,
      });
    }
    await context.close();
    await save();
  }
} finally {
  await browser.close();
  await save();
}
console.log(
  JSON.stringify(
    { screens: results.length, interactions: interactions.length, failures },
    null,
    2,
  ),
);
assert.deepEqual(failures, []);
assert.equal(interactions.length, viewports.length);
