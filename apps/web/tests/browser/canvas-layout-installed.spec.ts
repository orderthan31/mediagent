import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

const origin = process.env.MIDEAGENT_CANVAS_ORIGIN;
const password = process.env.MIDEAGENT_CANVAS_PASSWORD;
const evidence = process.env.MIDEAGENT_CANVAS_EVIDENCE;
const semantic = (value: any) => ({
  inputs: value.inputs,
  edges: value.edges,
  nodes: value.nodes.map(({ position, ...node }: any) => node),
});
const positions = (value: any) =>
  value.nodes.map((node: any) => ({ id: node.id, position: node.position }));

const geometry = async (page: any) => {
  return page.locator('.workflow-graph').evaluate((graph: HTMLElement) => {
    const nodes = [...graph.querySelectorAll<HTMLElement>('.workflow-graph-node')].map((node) => ({
      id: node.dataset.nodeId!,
      x: parseFloat(node.style.left),
      y: parseFloat(node.style.top),
      width: node.offsetWidth,
      height: node.offsetHeight,
      textFits: [
        ...node.querySelectorAll<HTMLElement>(
          '.workflow-node-heading strong,.workflow-node-ports button',
        ),
      ].every((label) => {
        // Port circles intentionally protrude 5px; inspect text fragments, not scrollWidth.
        const bounds = label.getBoundingClientRect();
        return [...label.childNodes]
          .filter((child) => child.nodeType === Node.TEXT_NODE && child.textContent?.trim())
          .every((child) => {
            const range = document.createRange();
            range.selectNodeContents(child);
            return [...range.getClientRects()].every(
              (r) =>
                r.left >= bounds.left - 0.25 &&
                r.right <= bounds.right + 0.25 &&
                r.top >= bounds.top - 0.25 &&
                r.bottom <= bounds.bottom + 0.25,
            );
          });
      }),
    }));
    const paths = [...graph.querySelectorAll<SVGPathElement>('path.workflow-wire')].map((path) => ({
      id: path.dataset.edgeId!,
      d: path.getAttribute('d')!,
      points: [...path.getAttribute('d')!.matchAll(/[ML](-?[\d.]+),(-?[\d.]+)/g)].map((m) => ({
        x: Number(m[1]),
        y: Number(m[2]),
      })),
    }));
    const controlsFit = [
      ...graph.querySelectorAll<HTMLElement>('.workflow-layout-actions button'),
    ].every((button) => {
      const r = button.getBoundingClientRect();
      return (
        r.left >= 0 &&
        r.right <= innerWidth &&
        button.scrollWidth <= button.clientWidth + 1 &&
        r.height >= 40
      );
    });
    const viewport = graph.querySelector<HTMLElement>('.workflow-graph-viewport')!;
    const viewportRect = viewport.getBoundingClientRect();
    const allInView = [...graph.querySelectorAll<HTMLElement>('.workflow-graph-node')].every(
      (node) => {
        const r = node.getBoundingClientRect();
        return (
          r.left >= viewportRect.left + 1 &&
          r.right <= viewportRect.right - 1 &&
          r.top >= viewportRect.top + 1 &&
          r.bottom <= viewportRect.bottom - 1
        );
      },
    );
    const world = graph.querySelector<HTMLElement>('.workflow-graph-world')!;
    const worldRect = world.getBoundingClientRect();
    const scale = new DOMMatrix(getComputedStyle(world).transform).a;
    const anchors = Object.fromEntries(
      [...graph.querySelectorAll<HTMLElement>('.workflow-node-ports button[data-port]')].map(
        (port) => {
          const circle = port.querySelector('i')!.getBoundingClientRect();
          return [
            port.dataset.node + ':' + port.dataset.portDirection + ':' + port.dataset.port,
            {
              x: (circle.left + circle.width / 2 - worldRect.left) / scale,
              y: (circle.top + circle.height / 2 - worldRect.top) / scale,
            },
          ];
        },
      ),
    );
    const wiresInView = paths.every((path) =>
      path.points.every((point) => {
        const x = worldRect.left + point.x * scale,
          y = worldRect.top + point.y * scale;
        return (
          x >= viewportRect.left + 1 &&
          x <= viewportRect.right - 1 &&
          y >= viewportRect.top + 1 &&
          y <= viewportRect.bottom - 1
        );
      }),
    );
    return { nodes, paths, controlsFit, allInView, anchors, wiresInView };
  });
};

const assertClean = (value: Awaited<ReturnType<typeof geometry>>, edges: any[]) => {
  expect(value.controlsFit).toBe(true);
  expect(value.allInView).toBe(true);
  expect(value.wiresInView).toBe(true);
  expect(value.nodes.every((node) => node.textFits)).toBe(true);
  for (let i = 0; i < value.nodes.length; i++) {
    const a = value.nodes[i];
    for (const b of value.nodes.slice(i + 1)) {
      expect(
        a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y,
      ).toBe(false);
    }
  }
  expect(value.paths).toHaveLength(edges.length);
  for (const edge of edges) {
    const path = value.paths.find((p) => p.id === edge.id)!;
    const source = value.anchors[edge.source.node + ':outputs:' + edge.source.port];
    const target = value.anchors[edge.target.node + ':inputs:' + edge.target.port];
    expect(path.points[0].x).toBeCloseTo(source.x, 0);
    expect(path.points[0].y).toBeCloseTo(source.y, 0);
    expect(path.points.at(-1)!.x).toBeCloseTo(target.x, 0);
    expect(path.points.at(-1)!.y).toBeCloseTo(target.y, 0);
  }
  for (let i = 0; i < edges.length; i++) {
    for (const other of edges.slice(i + 1)) {
      const edge = edges[i];
      // Fan-out deliberately shares its source-port junction.
      if (edge.source.node === other.source.node && edge.source.port === other.source.port) {
        continue;
      }
      const first = value.paths.find((path) => path.id === edge.id)!.points;
      const second = value.paths.find((path) => path.id === other.id)!.points;
      for (let aIndex = 1; aIndex < first.length; aIndex++) {
        for (let bIndex = 1; bIndex < second.length; bIndex++) {
          const a = first[aIndex - 1],
            b = first[aIndex],
            c = second[bIndex - 1],
            d = second[bIndex];
          const horizontalA = a.y === b.y,
            horizontalB = c.y === d.y;
          const contact =
            horizontalA !== horizontalB
              ? horizontalA
                ? c.x >= Math.min(a.x, b.x) &&
                  c.x <= Math.max(a.x, b.x) &&
                  a.y >= Math.min(c.y, d.y) &&
                  a.y <= Math.max(c.y, d.y)
                : a.x >= Math.min(c.x, d.x) &&
                  a.x <= Math.max(c.x, d.x) &&
                  c.y >= Math.min(a.y, b.y) &&
                  c.y <= Math.max(a.y, b.y)
              : horizontalA
                ? a.y === c.y &&
                  Math.min(Math.max(a.x, b.x), Math.max(c.x, d.x)) >
                    Math.max(Math.min(a.x, b.x), Math.min(c.x, d.x))
                : a.x === c.x &&
                  Math.min(Math.max(a.y, b.y), Math.max(c.y, d.y)) >
                    Math.max(Math.min(a.y, b.y), Math.min(c.y, d.y));
          expect(contact, `${edge.id} overlaps/crosses ${other.id}`).toBe(false);
        }
      }
    }
  }
  for (const path of value.paths) {
    expect(path.d).not.toContain('C');
    expect(path.points.length).toBeGreaterThanOrEqual(2);
    for (let i = 1; i < path.points.length; i++) {
      const a = path.points[i - 1],
        b = path.points[i];
      expect(a.x === b.x || a.y === b.y).toBe(true);
      for (const r of value.nodes) {
        const through =
          a.y === b.y
            ? a.y > r.y + 1 &&
              a.y < r.y + r.height - 1 &&
              Math.max(a.x, b.x) > r.x + 1 &&
              Math.min(a.x, b.x) < r.x + r.width - 1
            : a.x > r.x + 1 &&
              a.x < r.x + r.width - 1 &&
              Math.max(a.y, b.y) > r.y + 1 &&
              Math.min(a.y, b.y) < r.y + r.height - 1;
        expect(through, `${path.id} crosses ${r.id}`).toBe(false);
      }
    }
  }
};

for (const width of [1440, 390]) {
  test(`canvas arrange / wires / fit / save and read-only boundaries ${width}`, async ({
    page,
  }) => {
    test.skip(!origin || !password || !evidence, 'Explicit disposable graph fixture required');
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    const login = await page.request.post(origin + '/api/auth/login', {
      data: { username: 'canvas-fixture-admin', password },
    });
    expect(login.status()).toBe(200);
    const meta = (await (await page.request.get(origin + '/fixture-state')).json()).items[
      String(width)
    ];
    // Only catalog display labels and a clearly synthetic thumbnail are response fixtures.
    // Authentication, definitions, CAS saves, rereads and immutable job GETs use the real API/PG.
    await page.route(/\/api\/(?:settings\/node-catalog|work-entry\/catalog)$/, async (route) => {
      const response = await route.fetch();
      const catalog = await response.json();
      await route.fulfill({
        response,
        json: {
          ...catalog,
          nodes: catalog.nodes.map((node: any) => ({
            ...node,
            label: node.label + ' · 분기와 아주 긴 이름의 가독성을 확인하는 합성 그래프 노드',
          })),
        },
      });
    });
    await page.route('**/api/videos/*/thumbnail', (route) =>
      route.fulfill({
        contentType: 'image/svg+xml',
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36"><rect width="36" height="36" fill="#334155"/><text x="18" y="23" text-anchor="middle" fill="white" font-size="12">TEST</text></svg>',
      }),
    );
    await page.goto(origin + '/#/workflows/' + meta.workflow);
    await expect(page.getByRole('textbox', { name: '워크플로우 이름' })).toHaveValue(
      meta.original.name,
    );
    const graph = page.locator('.workflow-graph');
    await expect(graph.getByRole('button', { name: '자동 정렬', exact: true })).toBeVisible();
    await expect(graph.getByRole('button', { name: '연결선 정리', exact: true })).toBeVisible();
    await expect(graph.getByRole('button', { name: '전체 보기', exact: true })).toBeVisible();
    await expect
      .poll(async () => {
        const rect = await graph.locator('.workflow-graph-viewport').boundingBox();
        return rect!.y + rect!.height;
      })
      .toBeLessThanOrEqual(page.viewportSize()!.height);
    await page.evaluate(() => document.fonts.ready);
    const before = await (
      await page.request.get(origin + '/api/settings/workflow-definitions/' + meta.workflow)
    ).json();
    await graph.getByRole('button', { name: '자동 정렬', exact: true }).click();
    await graph.getByRole('button', { name: '정렬 되돌리기', exact: true }).click();
    const undo = await geometry(page);
    expect(
      undo.nodes.filter((node) => node.id !== '$input').map(({ id, x, y }) => ({ id, x, y })),
    ).toEqual(before.nodes.map((node: any) => ({ id: node.id, ...node.position })));
    await graph.getByRole('button', { name: '자동 정렬', exact: true }).click();
    await graph.getByRole('button', { name: '연결선 정리', exact: true }).click();
    await graph.getByRole('button', { name: '전체 보기', exact: true }).click();
    await expect.poll(async () => (await geometry(page)).allInView).toBe(true);
    const arranged = await geometry(page);
    assertClean(arranged, before.edges);
    const savedResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/settings/workflow-definitions/' + meta.workflow) &&
        response.request().method() === 'PUT',
    );
    await page.getByRole('button', { name: '저장', exact: true }).click();
    expect((await savedResponse).status()).toBe(200);
    await expect(page.locator('.workflow-save-state')).toHaveText('저장됨');
    const saved = await (
      await page.request.get(origin + '/api/settings/workflow-definitions/' + meta.workflow)
    ).json();
    expect(semantic(saved)).toEqual(semantic(before));
    expect(positions(saved)).not.toEqual(positions(before));
    await fs.mkdir(evidence!, { recursive: true });
    await page.screenshot({ path: `${evidence}/editor-${width}.png`, fullPage: true });
    await page.reload();
    await expect(page.getByRole('textbox', { name: '워크플로우 이름' })).toHaveValue(
      meta.original.name,
    );
    await graph.getByRole('button', { name: '전체 보기', exact: true }).click();
    await expect.poll(async () => (await geometry(page)).allInView).toBe(true);
    const reread = await geometry(page);
    expect(
      reread.nodes.filter((node) => node.id !== '$input').map(({ id, x, y }) => ({ id, x, y })),
    ).toEqual(saved.nodes.map((node: any) => ({ id: node.id, ...node.position })));
    assertClean(reread, saved.edges);
    const writes: { method: string; path: string }[] = [];
    page.on('request', (request) => {
      if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method())) {
        writes.push({ method: request.method(), path: new URL(request.url()).pathname });
      }
    });
    await page.goto(origin + '/#/jobs/' + meta.job);
    await expect(graph).toBeVisible();
    await expect(graph.getByRole('button', { name: '자동 정렬', exact: true })).toBeEnabled();
    await graph.getByRole('button', { name: '자동 정렬', exact: true }).click();
    await graph.getByRole('button', { name: '연결선 정리', exact: true }).click();
    await graph.getByRole('button', { name: '전체 보기', exact: true }).click();
    await expect.poll(async () => (await geometry(page)).allInView).toBe(true);
    const readonly = await geometry(page);
    assertClean(readonly, meta.original.edges);
    await expect(graph.getByText('읽기 전용 · 화면 배치만 변경')).toBeVisible();
    await page.screenshot({ path: `${evidence}/readonly-${width}.png`, fullPage: true });
    if (width === 390) {
      const canvas = graph.locator('.workflow-graph-viewport');
      const target = graph.locator('[data-node-id="right"]');
      for (let index = 0; index < 12; index++) {
        if ((await target.boundingBox())!.width >= 220) {
          break;
        }
        await graph.getByRole('button', { name: '캔버스 확대', exact: true }).click();
      }
      for (let index = 0; index < 32; index++) {
        const view = (await canvas.boundingBox())!,
          node = (await target.boundingBox())!;
        const key =
          node.x < view.x + 12
            ? 'ArrowLeft'
            : node.x + node.width > view.x + view.width - 12
              ? 'ArrowRight'
              : node.y < view.y + 72
                ? 'ArrowUp'
                : node.y + node.height > view.y + view.height - 12
                  ? 'ArrowDown'
                  : '';
        if (!key) {
          break;
        }
        await canvas.press(key);
      }
      const closeup = (await target.boundingBox())!,
        view = (await canvas.boundingBox())!;
      expect(closeup.width).toBeGreaterThan(200);
      expect(closeup.x).toBeGreaterThanOrEqual(view.x);
      expect(closeup.x + closeup.width).toBeLessThanOrEqual(view.x + view.width);
      await page.evaluate(() => {
        const rect = document.querySelector('.workflow-graph')!.getBoundingClientRect();
        window.scrollTo(0, window.scrollY + rect.top - 76);
      });
      await page.screenshot({ path: `${evidence}/readonly-detail-${width}.png` });
    }
    await graph.getByRole('button', { name: '배치 초기화', exact: true }).click();
    expect((await geometry(page)).nodes.find((node) => node.id === 'split')).toMatchObject(
      meta.original.nodes[0].position,
    );
    const proof = (await (await page.request.get(origin + '/fixture-state')).json()).items[
      String(width)
    ];
    expect(proof.current_snapshot_sha256).toBe(meta.snapshot_sha256);
    expect(proof.job_revision).toBe(meta.job_revision);
    expect(proof.job_status).toBe('draft');
    expect(writes).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    expect(errors).toEqual([]);
    await fs.writeFile(
      `${evidence}/geometry-${width}.json`,
      JSON.stringify(
        {
          width,
          scope:
            'real auth/workflow PG; synthetic catalog labels and draft graph snapshot; no execution',
          undo: true,
          semantic_unchanged: true,
          saved_revision: saved.revision,
          saved_positions: positions(saved),
          reread_positions: reread.nodes,
          arranged,
          readonly,
          immutable_snapshot_unchanged: true,
          readonly_writes: writes,
          page_errors: errors,
        },
        null,
        2,
      ),
    );
  });
}
