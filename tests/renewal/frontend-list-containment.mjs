// Explicit, isolated DEV synthetic layout QA. No real media/API/provider calls.
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { chromium } from "../../apps/web/node_modules/@playwright/test/index.mjs";
import { listGeometry } from "./list-geometry.mjs";

const base = process.env.MIDEAGENT_PREVIEW_ORIGIN;
const evidence = process.env.MIDEAGENT_PREVIEW_EVIDENCE_DIR;
assert(base && new URL(base).protocol === "http:" && evidence);
await mkdir(evidence, { recursive: true });
const viewports = [
  { name: "cover-portrait", width: 416, height: 657, dpr: 3 },
  { name: "unfolded-landscape", width: 816, height: 616, dpr: 3 },
  { name: "pc-fhd", width: 1920, height: 1080, dpr: 1 },
  { name: "cover-short", width: 416, height: 577, dpr: 3 },
  { name: "unfolded-short", width: 816, height: 536, dpr: 3 },
  { name: "minimum-phone", width: 320, height: 640, dpr: 3 },
  { name: "adjacent-phone", width: 390, height: 844, dpr: 3 },
  { name: "adjacent-unfolded", width: 896, height: 768, dpr: 3 },
  { name: "pc-compact", width: 1440, height: 900, dpr: 1 },
];
const browser = await chromium.launch({ headless: true });
const results = [],
  failures = [];
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
      blocked = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await context.route("**/*", (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== base || url.pathname.startsWith("/api/")) {
        blocked.push(url.origin + url.pathname);
        return route.abort();
      }
      return route.continue();
    });
    const visit = async (route, selector) => {
      await page.goto(base + "/#/" + route);
      await page.locator(selector).first().waitFor();
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(100);
    };
    const check = async (name) => {
      const geometry = await listGeometry(page);
      results.push({ viewport: v.name, name, ...geometry });
      await page.screenshot({
        path: join(evidence, v.name + "-" + name + ".png"),
        scale: "css",
      });
      if (geometry.violations.length || geometry.documentOverflow > 1) {
        failures.push({ viewport: v.name, name, ...geometry });
      }
    };
    await visit("agents", ".ui02-agent-row");
    await check("agents-default");
    // Browser-only synthetic text expansion proves layout behavior, not a changed
    // catalog/API fixture. It preserves the real row DOM and production selectors.
    await page
      .locator(".ui02-agent-row")
      .first()
      .evaluate((row) => {
        row.querySelector(".ui02-list-title").textContent =
          "긴 에이전트 이름과 입력 출력 호환성 검증 ".repeat(8);
        row.querySelector(".ui02-list-meta").textContent =
          "synthetic_long_input_modality_".repeat(10) + " → 영상 정보";
      });
    await check("agents-expanded-text");
    await visit("", ".storage-asset-row");
    assert.match(
      await page.title(),
      /원본/,
      "Use the actual original-list root, not an unknown-route fallback",
    );
    await check("storage-default");
    const fixture = await page.evaluate(() =>
      JSON.parse(sessionStorage.getItem("mideagent-publishing-fixtures-v1")),
    );
    assert.equal(
      fixture?.publishingContractVersion,
      1,
      "Synthetic DEV preview required",
    );
    for (const count of [0, 1, 45]) {
      await page.evaluate(
        ({ fixture, count }) => {
          const videos = Array.from({ length: count }, (_, index) => ({
            ...fixture.videos[index % fixture.videos.length],
            asset_id: (index + 1).toString(16).padStart(32, "0"),
            original_filename:
              index === 0
                ? "synthetic_very_long_filename_without_spaces_".repeat(10) +
                  ".mp4"
                : `synthetic-${index + 1}.mp4`,
          }));
          sessionStorage.setItem(
            "mideagent-publishing-fixtures-v1",
            JSON.stringify({ ...fixture, videos }),
          );
        },
        { fixture, count },
      );
      await page.reload();
      await page.locator(".list-pagination").waitFor();
      await page.waitForTimeout(100);
      assert.equal(
        await page.locator(".storage-asset-row").count(),
        Math.min(count, 20),
      );
      await check("storage-count-" + count);
      const list = page.locator(".storage-library");
      const pager = await page.locator(".list-pagination").boundingBox();
      const box = await list.boundingBox();
      assert(
        box.y + box.height <= pager.y + 1,
        "List scroller must not cover pagination",
      );
      if (count === 45) {
        await list.evaluate((element) => {
          element.scrollTop = element.scrollHeight;
        });
        const scroll = await list.evaluate((element) => ({
          top: element.scrollTop,
          max: element.scrollHeight - element.clientHeight,
        }));
        assert(
          scroll.top > 0 && Math.abs(scroll.top - scroll.max) <= 1,
          "Last row must be reachable inside list",
        );
        await check("storage-scrolled-last-row");
        const last = await page
          .locator(".storage-asset-row")
          .last()
          .boundingBox();
        assert(last.y + last.height <= box.y + box.height + 1);
        await page.getByLabel("페이지 선택", { exact: true }).selectOption("3");
        await page.waitForTimeout(50);
        assert.equal(await page.locator(".storage-asset-row").count(), 5);
        await check("storage-page-3");
        await page.locator(".storage-asset-row").last().click();
        await page.waitForURL("**/#/videos/*");
        assert.equal(await page.locator(".storage-video-info").count(), 1);
      }
    }
    assert.deepEqual(errors, [], "No application exceptions");
    assert.deepEqual(blocked, [], "No real API or external requests");
    await context.close();
  }
} finally {
  await browser.close();
  await writeFile(
    join(evidence, "list-containment.json"),
    JSON.stringify({ viewports, results, failures }, null, 2),
  );
}
console.log(
  JSON.stringify({ cases: results.length, failures: failures.length }),
);
assert.equal(
  failures.length,
  0,
  "List content must stay above its own divider and inside row padding",
);
