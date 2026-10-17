// Bounded synthetic-preview checks. Never use this against a production API.
import assert from "node:assert/strict";
import { join } from "node:path";
import { chromium } from "../../apps/web/node_modules/@playwright/test/index.mjs";
const base = process.env.MIDEAGENT_PREVIEW_ORIGIN;
const evidence = process.env.MIDEAGENT_PREVIEW_EVIDENCE_DIR;
assert(base && new URL(base).protocol === "http:");
const browser = await chromium.launch({ headless: true });
const results = [];
try {
  for (const width of [1920, 896, 390, 320]) {
    const context = await browser.newContext({
      viewport: { width, height: 1080 },
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await context.route("**/*", (route) =>
      new URL(route.request().url()).origin === base
        ? route.continue()
        : route.abort(),
    );
    await page.goto(base + "/#/start");
    await page.getByLabel("원본", { exact: true }).waitFor();
    const fixture = await page.evaluate(() =>
      JSON.parse(sessionStorage.getItem("mideagent-publishing-fixtures-v1")),
    );
    assert(
      fixture?.publishingContractVersion === 1,
      "Explicit synthetic preview required",
    );
    const asset = fixture.videos[0],
      definition = fixture.definitions[0];
    await page.getByLabel("원본", { exact: true }).selectOption(asset.asset_id);
    await page
      .getByLabel("워크플로우", { exact: true })
      .selectOption(definition.id);
    const input = page.locator(
      '[data-node-id="$input"] .workflow-node-heading',
    );
    await input.filter({ hasText: asset.original_filename }).waitFor();
    assert.equal(
      await page.locator(".workflow-graph-node").count(),
      definition.nodes.length + 1,
    );
    assert.equal(
      await page.getByRole("button", { name: "새로고침", exact: true }).count(),
      0,
    );
    assert.equal(await page.getByText("작업 요약", { exact: true }).count(), 0);
    assert.equal(await page.getByText("복구 지원", { exact: true }).count(), 0);
    if (evidence && width === 1920)
      await page.screenshot({ path: join(evidence, "start-fhd.png") });
    await input.click();
    await page.locator(".entry-media-preview").waitFor();
    assert.equal(
      new URL(
        await page.locator(".entry-media-preview").getAttribute("src"),
        base,
      ).origin,
      base,
    );
    assert.equal(
      await page
        .getByRole("button", { name: "에이전트 추가", exact: true })
        .count(),
      0,
    );
    await page.goto(base + "/#/jobs/" + fixture.jobs[0].job_id);
    const node = page.locator(
      '[data-node-id="prepare"] .workflow-node-heading',
    );
    await node.click();
    const panel = page.getByRole("region", {
      name: "노드 실행 상세",
      exact: true,
    });
    await panel.waitFor();
    // Expand actual persisted settings and input artifacts, not injected DOM filler.
    await panel
      .locator("summary")
      .filter({ hasText: "실제 적용 설정" })
      .click();
    await panel.locator("summary").filter({ hasText: "입력 자료" }).click();
    const scrollable = await panel.evaluate((element) => ({
      client: element.clientHeight,
      scroll: element.scrollHeight,
      touch: getComputedStyle(element).touchAction,
    }));
    assert(scrollable.scroll > scrollable.client);
    assert.equal(scrollable.touch, "pan-y");
    const rect = await panel.boundingBox();
    await page.mouse.move(
      rect.x + rect.width - 15,
      Math.min(1000, rect.y + rect.height - 30),
    );
    await page.mouse.wheel(0, 650);
    await page.waitForTimeout(100);
    assert(
      (await panel.evaluate((element) => element.scrollTop)) > 0,
      "Native wheel must scroll selected-node results",
    );
    await panel.focus();
    await page.keyboard.press("Control+End");
    await page.goto(base + "/#/serving/new");
    await page
      .getByRole("checkbox", { name: "모델 유형 TTS", exact: true })
      .check();
    assert.equal(
      await page
        .getByRole("checkbox", { name: "출력 오디오", exact: true })
        .isChecked(),
      true,
    );
    assert.equal(
      await page
        .getByRole("checkbox", { name: "지원 기능 음성 합성", exact: true })
        .isChecked(),
      true,
    );
    assert.equal(
      await page
        .getByRole("button", { name: "호환 용도 확인", exact: true })
        .count(),
      0,
    );
    if (evidence && width === 1920)
      await page.screenshot({ path: join(evidence, "model-fhd.png") });
    // Tab-local, non-secret metadata only; not a password/login test.
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
    const footers = [];
    for (const route of [
      "serving/new",
      "serving/connections/new",
      "account/new",
    ]) {
      await page.goto(base + "/#/" + route);
      await page.locator(".page-actions").waitFor();
      const footer = await page.locator(".page-actions").boundingBox();
      footers.push(Math.round(footer.y + footer.height));
      if (width === 1920) assert(footer.x < 240 && footer.width > 1600);
    }
    // Short forms align at the viewport bottom. Long narrow forms flow below
    // their content instead of pinning an action bar over still-unread fields.
    if (footers.every((bottom) => bottom <= 1080)) {
      assert(
        Math.max(...footers) - Math.min(...footers) <= 2,
        `Short form footer baseline: ${JSON.stringify({ width, footers })}`,
      );
    }
    const listResults = {};
    for (const [route, key, idField] of [
      ["jobs", "jobs", "job_id"],
      ["", "videos", "asset_id"],
      ["serving", "models", "id"],
      ["serving/connections", "connections", "id"],
      ["workflows", "definitions", "id"],
    ]) {
      const pagination = [];
      for (const count of [0, 1, 45]) {
        await page.evaluate(
          ({ fixture, count, route, key, idField }) => {
            const state = structuredClone(fixture);
            state[key] = Array.from({ length: count }, (_, i) => ({
              ...structuredClone(fixture[key][0]),
              [idField]: (i + 1000).toString(16).padStart(32, "0"),
              ...(key === "jobs" ? { ticket_number: `T-${i + 1000}` } : {}),
            }));
            sessionStorage.setItem(
              "mideagent-publishing-fixtures-v1",
              JSON.stringify(state),
            );
            location.hash = "/" + route;
          },
          { fixture, count, route, key, idField },
        );
        await page.reload();
        await page.locator(".list-pagination").waitFor();
        const footer = await page.locator(".list-pagination").boundingBox();
        pagination.push(Math.round(footer.y + footer.height));
        if (width === 1920) {
          const main = await page.locator("main").boundingBox();
          assert.equal(main.x, 184);
          assert.equal(main.width, width - 184);
        }
        assert(
          (await page.evaluate(
            () => document.documentElement.scrollWidth - innerWidth,
          )) <= 1,
          `${route}: document overflow`,
        );
        if (count > 0 && route.startsWith("serving")) {
          const list = page.locator(".ui02-list");
          assert.equal(await list.getByRole("button").count(), 0);
          assert.doesNotMatch(await list.innerText(), /revision|\br[0-9]+\b/);
          await list
            .locator("a.serving-resource-row, a.provider-resource-row")
            .first()
            .click();
          await page.locator(".serving-resource-facts").waitFor();
          await page
            .getByRole("button", { name: "수정", exact: true })
            .waitFor();
          assert.doesNotMatch(
            await page.locator("main").innerText(),
            /revision 이력|\br[0-9]+\b/,
          );
          await page.goto(base + "/#/" + route);
          await page.locator(".list-pagination").waitFor();
        }
        if (count === 45) {
          if (evidence && width === 1920 && route === "jobs")
            await page.screenshot({ path: join(evidence, "jobs-fhd.png") });
          await page
            .getByRole("combobox", { name: "페이지 선택", exact: true })
            .selectOption("3");
          assert.equal(
            await page
              .getByRole("combobox", { name: "페이지 선택", exact: true })
              .inputValue(),
            "3",
          );
          assert.match(
            await page.locator(".list-pagination").innerText(),
            /41–45/,
          );
          await page
            .getByRole("combobox", { name: "페이지 선택", exact: true })
            .selectOption("1");
        }
      }
      assert(
        Math.max(...pagination) - Math.min(...pagination) <= 2,
        `Pagination baseline must not depend on row count: ${JSON.stringify({ width, route, pagination })}`,
      );
      listResults[route] = pagination;
    }
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - innerWidth,
    );
    assert(
      overflow <= 1,
      `Unexpected document horizontal overflow: ${overflow}`,
    );
    assert.deepEqual(errors, []);
    results.push({
      width,
      selected_media_canvas: true,
      result_wheel_scrolled: true,
      tts_profile: true,
      form_footer_bottoms: footers,
      list_footer_bottoms: listResults,
      document_overflow: overflow,
    });
    await context.close();
  }
  console.log(
    JSON.stringify({
      result: "passed",
      viewports: results,
      scope: "isolated DEV synthetic browser state; no provider/GPU calls",
    }),
  );
} finally {
  await browser.close();
}
