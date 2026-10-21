// Real TLS RabbitMQ consumers + product tickets + S3; no response mocks.
import assert from "node:assert/strict";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { openSync, closeSync } from "node:fs";
import { join } from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { once } from "node:events";
import { createHash, randomUUID } from "node:crypto";
import { chromium } from "../../apps/web/node_modules/@playwright/test/index.mjs";
const cfg = JSON.parse(
  await readFile(process.env.MIDEAGENT_BROKER_CONTROL_CONFIG, "utf8"),
);
const base = cfg.origin,
  out = process.env.MIDEAGENT_BROKER_CONTROL_EVIDENCE;
assert(
  base.startsWith("http://127.0.0.1:") &&
    process.env.MIDEAGENT_CONTROL_DISPOSABLE === "1",
);
await mkdir(out, { recursive: true });
const id = () => randomUUID().replaceAll("-", "");
const probe = () => {
  const r = spawnSync(
    process.env.MIDEAGENT_CONTROL_PYTHON,
    [process.env.MIDEAGENT_BROKER_PROBE],
    { env: process.env, encoding: "utf8" },
  );
  assert.equal(r.status, 0, "Read-only fixture probe failed");
  return JSON.parse(r.stdout);
};
const startHost = () => {
  const fd = openSync(join(out, "host.log"), "a");
  const p = spawn(
    process.env.MIDEAGENT_CONTROL_PYTHON,
    [process.env.MIDEAGENT_BROKER_HOST],
    { env: process.env, stdio: ["ignore", fd, fd] },
  );
  closeSync(fd);
  return p;
};
const killHost = async (p) => {
  if (p.exitCode === null) {
    const exit = once(p, "exit");
    p.kill();
    await exit;
  }
};
const wait = async (check, timeout = 90000) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const value = await check();
    if (value) return value;
    await new Promise((r) => setTimeout(r, 180));
  }
  throw Error("Real broker/product observation timed out");
};
const browser = await chromium.launch({ headless: true, channel: "msedge" });
const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
  }),
  page = await context.newPage();
page.setDefaultTimeout(15000);
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
let host,
  report = {
    scope: "REAL_DISPOSABLE_TLS_MQ_PRODUCT_TICKETS_S3_NOT_OPERATING",
    passed: false,
  };
try {
  host = startHost();
  const checked = async (method, path, data, expected = 200) => {
    const r = await context.request.fetch(base + path, {
      method,
      data,
      headers: method === "GET" ? {} : headers,
    });
    assert.equal(
      r.status(),
      expected,
      "Product API rejected " + method + " " + path,
    );
    return r;
  };
  const session = await (
    await context.request.get(base + "/api/auth/session")
  ).json();
  if (session.setup_required)
    assert.equal(
      (
        await context.request.post(base + "/api/auth/bootstrap", {
          data: cfg.admin,
        })
      ).status(),
      201,
    );
  const login = await context.request.post(base + "/api/auth/login", {
    data: cfg.admin,
  });
  assert.equal(login.status(), 200);
  const headers = {
    Origin: base,
    "X-CSRF-Token": (await login.json()).csrf_token,
  };
  const state = async () => {
    const r = await context.request.get(base + "/api/admin/agents/encode");
    assert.equal(r.status(), 200);
    return r.json();
  };
  const settled = async (count) => {
    const s = await wait(async () => {
      const v = await state();
      return v.observed_replicas === count && !v.control.phase ? v : null;
    });
    await page
      .getByRole("region", { name: "에이전트 제어" })
      .getByText("확인된 실행 개수: " + count, { exact: true })
      .waitFor();
    return s;
  };
  await wait(async () => {
    const s = await state();
    return s.manageable;
  });
  await page.goto(base + "/#/agents/encode");
  const panel = page.getByRole("region", {
    name: "에이전트 제어",
    exact: true,
  });
  await panel.waitFor();
  const field = panel.getByLabel("실행 개수", { exact: true });
  await field.fill("1");
  await panel.getByRole("button", { name: "시작", exact: true }).click();
  await settled(1);
  await wait(async () => {
    const s = await state();
    return s.workers.filter((w) => w.state === "ready").length === 1;
  });
  await field.fill("2");
  await panel.getByRole("button", { name: "개수 적용", exact: true }).click();
  await settled(2);
  await wait(async () => {
    const s = await state();
    return s.workers.every((w) => w.state === "ready");
  });
  const movie = await readFile(process.env.MIDEAGENT_BROKER_MOVIE);
  const upload = await (
    await checked(
      "POST",
      "/api/video-uploads",
      {
        filename: "real-broker-45s-synthetic.mp4",
        size: movie.length,
        request_id: id(),
      },
      201,
    )
  ).json();
  const chunk = await context.request.put(
    base + "/api/video-uploads/" + upload.upload_id + "/chunks?offset=0",
    {
      data: movie,
      headers: { ...headers, "Content-Type": "application/octet-stream" },
    },
  );
  assert.equal(chunk.status(), 200);
  const source = await (
    await checked(
      "POST",
      "/api/video-uploads/" + upload.upload_id + "/complete",
      {},
    )
  ).json();
  const workflow = id();
  const graph = {
    catalog_version: 1,
    revision: 0,
    name: "격리 실제 MQ 45초 검증",
    inputs: { video: "video" },
    nodes: [
      {
        id: "encode-node",
        type: "encode",
        position: { x: 0, y: 0 },
        options: { subtitle_mode: "none" },
      },
      {
        id: "validate-node",
        type: "validate_video",
        position: { x: 300, y: 0 },
        options: {},
      },
    ],
    edges: [
      {
        id: "input",
        source: { node: "$input", port: "video" },
        target: { node: "encode-node", port: "video" },
      },
      {
        id: "next",
        source: { node: "encode-node", port: "video" },
        target: { node: "validate-node", port: "video" },
      },
    ],
  };
  await checked("PUT", "/api/settings/workflow-definitions/" + workflow, graph);
  const createJob = async () => {
    const selection = {
      asset_id: source.asset_id,
      definition_id: workflow,
      definition_revision: 1,
      recovery_enabled: false,
      options: {},
    };
    const preview = await (
      await checked("POST", "/api/settings/work-entry/preview", selection)
    ).json();
    const job = await (
      await checked(
        "POST",
        "/api/settings/work-entry/create",
        {
          ...selection,
          token: preview.token,
          request_id: id(),
          paid_confirmed: false,
        },
        201,
      )
    ).json();
    const path = "/api/renewal/jobs/" + job.id;
    const plan = await (await checked("GET", path + "/plan")).json();
    const consent = await (
      await checked("POST", path + "/confirm", {
        token: plan.token,
        request_id: id(),
      })
    ).json();
    await checked("POST", path + "/admit", {
      consent_id: consent.id,
      request_id: id(),
    });
    await checked("POST", path + "/run", {});
    return job;
  };
  const jobs = [await createJob(), await createJob()];
  const busy = await wait(async () => {
    const s = await state();
    return s.workers.every(
      (w) => w.state === "busy" && jobs.some((j) => j.id === w.ticket_id),
    )
      ? s
      : null;
  });
  assert(busy.workers.every((w) => w.attempt_id && w.ticket_number));
  await page.screenshot({ path: join(out, "real-product-tickets-busy.png") });
  await panel.getByRole("button", { name: "중지", exact: true }).click();
  const draining = await wait(async () => {
    const s = await state();
    return s.workers.every(
      (w) => w.state === "stopping" && jobs.some((j) => j.id === w.ticket_id),
    )
      ? s
      : null;
  });
  for (const w of draining.workers)
    await page
      .locator('[data-worker-id="' + w.worker_id + '"]')
      .getByText("중지 중", { exact: true })
      .waitFor();
  const requestId = draining.control.request_id;
  assert(requestId);
  await wait(() => {
    const p = probe();
    const a = p.actions.filter((a) => a.request_id === requestId);
    return a.length === 2 && a.every((a) => a.phase === "sent");
  });
  await page.screenshot({ path: join(out, "real-consumers-draining.png") });
  await killHost(host);
  host = null;
  const third = await createJob();
  const unknown = await wait(async () => {
    const s = await state();
    return s.control.phase === "unknown" && !s.manageable ? s : null;
  }, 25000);
  await panel.getByText("제어 결과 확인 불가", { exact: true }).waitFor();
  await page.screenshot({
    path: join(out, "controller-interrupted-unknown.png"),
  });
  host = startHost();
  await wait(async () => {
    const s = await state();
    return (
      s.manageable &&
      s.control.request_id === requestId &&
      s.workers.every((w) => w.state === "stopping")
    );
  });
  const beyond = await wait(async () => {
    const p = probe();
    const actions = p.actions.filter((a) => a.request_id === requestId);
    if (actions.length !== 2 || !actions.every((a) => a.elapsed_seconds > 30))
      return false;
    const s = await state();
    return s.observed_replicas === 2 && s.control.phase === "applying"
      ? { state: s, actions }
      : false;
  }, 45000);
  assert(
    beyond.actions.every((a) => a.issue_count === 1 && a.phase === "sent"),
  );
  await page.screenshot({
    path: join(out, "beyond-30-seconds-still-draining.png"),
  });
  await settled(0);
  const completed = await wait(async () => {
    const all = await Promise.all(
      jobs.map(async (j) =>
        (await checked("GET", "/api/renewal/jobs/" + j.id)).json(),
      ),
    );
    return all.every((j) => j.status === "completed") ? all : null;
  });
  const waiting = await (
    await checked("GET", "/api/renewal/jobs/" + third.id)
  ).json();
  assert.notEqual(waiting.status, "completed");
  const artifacts = [];
  for (const job of completed) {
    const run = job.runs.find((r) => r.node_type === "encode");
    const ref = run.result.outputs.video;
    const data = await (
      await checked(
        "GET",
        "/api/renewal/jobs/" + job.id + "/artifacts/" + run.id + "/video",
      )
    ).body();
    assert.equal(createHash("sha256").update(data).digest("hex"), ref.sha256);
    await writeFile(join(out, "job-" + job.ticket_number + ".mp4"), data);
    artifacts.push({
      job: job.id,
      ticket_number: job.ticket_number,
      attempt: run.id,
      sha256: ref.sha256,
      bytes: data.length,
    });
  }
  const afterRestart = probe();
  const stoppedActions = afterRestart.actions.filter(
    (a) => a.request_id === requestId,
  );
  assert(
    stoppedActions.every((a) => a.issue_count === 1 && a.phase === "confirmed"),
  );
  await field.fill("2");
  await panel.getByRole("button", { name: "시작", exact: true }).click();
  await settled(2);
  const resumed = await wait(async () => {
    const j = await (
      await checked("GET", "/api/renewal/jobs/" + third.id)
    ).json();
    return j.status === "completed" ? j : null;
  });
  await panel.getByRole("button", { name: "중지", exact: true }).click();
  await settled(0);
  const final = probe();
  assert(
    final.actions.every((a) => a.issue_count === 1 && a.phase === "confirmed"),
  );
  assert.deepEqual(errors, []);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: join(out, "real-product-final-zero-mobile.png"),
  });
  report = {
    ...report,
    passed: true,
    actual_busy: busy,
    actual_draining: draining,
    controller_unknown: unknown,
    beyond_cli_deadline: beyond,
    interrupted_request_id: requestId,
    no_repeated_stop_signal: true,
    completed_artifacts: artifacts,
    preserved_waiting_job: { id: third.id, status: waiting.status },
    resumed_queued_job: { id: resumed.id, status: resumed.status },
    final_database: final,
  };
} catch (error) {
  report = { ...report, error: String(error), errors, probe: probe() };
  await page.screenshot({ path: join(out, "failure.png") });
  throw error;
} finally {
  if (host) await killHost(host);
  await writeFile(join(out, "result.json"), JSON.stringify(report, null, 2));
  await context.close();
  await browser.close();
}
console.log(
  JSON.stringify({
    passed: report.passed,
    real_product_tickets: report.completed_artifacts?.length,
    over_30_second_drain: !!report.beyond_cli_deadline,
    no_repeated_stop_signal: report.no_repeated_stop_signal,
  }),
);
