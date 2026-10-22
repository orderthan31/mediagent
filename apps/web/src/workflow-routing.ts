import type { LayoutBox, LayoutEdge, LayoutPoint } from './workflow-layout';

export type Wire = LayoutEdge & { from: LayoutPoint; to: LayoutPoint };
export type WireRoute = { points: LayoutPoint[]; path: string };
type Segment = { a: LayoutPoint; b: LayoutPoint };
const epsilon = 0.001;
const between = (value: number, low: number, high: number) =>
  value > low + epsilon && value < high - epsilon;
const hits = (a: LayoutPoint, b: LayoutPoint, box: LayoutBox, padding = 14) => {
  const left = box.x - padding,
    right = box.x + box.width + padding;
  const top = box.y - padding,
    bottom = box.y + box.height + padding;
  return a.y === b.y
    ? between(a.y, top, bottom) &&
        Math.max(a.x, b.x) > left + epsilon &&
        Math.min(a.x, b.x) < right - epsilon
    : between(a.x, left, right) &&
        Math.max(a.y, b.y) > top + epsilon &&
        Math.min(a.y, b.y) < bottom - epsilon;
};
const distance = (a: LayoutPoint, b: LayoutPoint) => Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
const simplify = (points: LayoutPoint[]) => {
  const result: LayoutPoint[] = [];
  for (const point of points) {
    if (result.length && distance(result[result.length - 1], point) < epsilon) {
      continue;
    }
    const a = result[result.length - 2],
      b = result[result.length - 1];
    if (a && b && ((a.x === b.x && b.x === point.x) || (a.y === b.y && b.y === point.y))) {
      result.pop();
    }
    result.push(point);
  }
  return result;
};

export const routeConnections = (boxes: LayoutBox[], wires: Wire[]): Map<string, WireRoute> => {
  const routes = new Map<string, WireRoute>();
  const reserved: Segment[] = [];
  const remainingTargets = new Map<string, number>();
  for (const wire of wires) {
    remainingTargets.set(wire.target.node, (remainingTargets.get(wire.target.node) || 0) + 1);
  }
  let totalVisits = 0;
  for (const [ordinal, wire] of wires.entries()) {
    const source = boxes.find((box) => box.id === wire.source.node);
    const target = boxes.find((box) => box.id === wire.target.node);
    if (
      !source ||
      !target ||
      ![wire.from.x, wire.from.y, wire.to.x, wire.to.y].every(Number.isFinite)
    ) {
      throw new Error('연결 포트의 위치를 확인할 수 없습니다.');
    }
    const offset = (ordinal % 8) * 3;
    const start = { x: wire.from.x + 28 + offset, y: wire.from.y };
    // Nest later arrivals closer to their target, not across an earlier approach.
    const remaining = remainingTargets.get(wire.target.node)! - 1;
    remainingTargets.set(wire.target.node, remaining);
    const end = { x: wire.to.x - 28 - remaining * 8, y: wire.to.y };
    if (
      boxes.some((box) => box.id !== source.id && hits(wire.from, start, box)) ||
      boxes.some((box) => box.id !== target.id && hits(end, wire.to, box))
    ) {
      throw new Error('노드가 겹칩니다. 자동 정렬 후 연결선을 정리해 주세요.');
    }
    const xs = [
      ...new Set([
        start.x,
        end.x,
        ...boxes.flatMap((box) => [box.x - 14 - offset, box.x + box.width + 14 + offset]),
      ]),
    ].sort((a, b) => a - b);
    const ys = [
      ...new Set([
        start.y,
        end.y,
        ...boxes.flatMap((box) => [box.y - 14 - offset, box.y + box.height + 14 + offset]),
      ]),
    ].sort((a, b) => a - b);
    const nx = xs.length;
    const point = (cell: number) => ({ x: xs[cell % nx], y: ys[Math.floor(cell / nx)] });
    const startCell = ys.indexOf(start.y) * nx + xs.indexOf(start.x);
    const endCell = ys.indexOf(end.y) * nx + xs.indexOf(end.x);
    type Item = { key: number; g: number; f: number; order: number };
    const heap: Item[] = [];
    let serial = 0;
    const less = (a: Item, b: Item) => a.f < b.f || (a.f === b.f && a.order < b.order);
    const push = (value: Item) => {
      heap.push(value);
      let i = heap.length - 1;
      while (i > 0) {
        const parent = Math.floor((i - 1) / 2);
        if (!less(heap[i], heap[parent])) {
          break;
        }
        [heap[i], heap[parent]] = [heap[parent], heap[i]];
        i = parent;
      }
    };
    const pop = () => {
      const value = heap[0],
        last = heap.pop()!;
      if (heap.length) {
        heap[0] = last;
        let i = 0;
        while (true) {
          let next = i;
          for (const child of [i * 2 + 1, i * 2 + 2]) {
            if (child < heap.length && less(heap[child], heap[next])) {
              next = child;
            }
          }
          if (next === i) {
            break;
          }
          [heap[i], heap[next]] = [heap[next], heap[i]];
          i = next;
        }
      }
      return value;
    };
    const costs = new Map<number, number>([[startCell * 3, 0]]);
    const previous = new Map<number, number>();
    const clearCache = new Map<string, boolean>();
    push({ key: startCell * 3, g: 0, f: distance(start, end), order: serial++ });
    let found: number | undefined;
    while (heap.length) {
      if (++totalVisits > 250000) {
        throw new Error(
          '그래프가 복잡해 연결선 정리를 중단했습니다. 노드 배치를 나눠 조정해 주세요.',
        );
      }
      const current = pop();
      if (current.g !== costs.get(current.key)) {
        continue;
      }
      const cell = Math.floor(current.key / 3),
        direction = current.key % 3;
      if (cell === endCell) {
        found = current.key;
        break;
      }
      const x = cell % nx,
        y = Math.floor(cell / nx),
        a = point(cell);
      for (const [dx, dy] of [
        [1, 0],
        [0, 1],
        [0, -1],
        [-1, 0],
      ]) {
        const xx = x + dx,
          yy = y + dy;
        if (xx < 0 || yy < 0 || xx >= nx || yy >= ys.length) {
          continue;
        }
        const nextCell = yy * nx + xx,
          b = point(nextCell);
        const cache = Math.min(cell, nextCell) + ':' + Math.max(cell, nextCell);
        if (!clearCache.has(cache)) {
          clearCache.set(cache, !boxes.some((box) => hits(a, b, box)));
        }
        if (!clearCache.get(cache)) {
          continue;
        }
        const nextDirection = dx ? 1 : 2;
        let penalty = direction && direction !== nextDirection ? 24 : 0;
        for (const { a: c, b: d } of reserved) {
          if (a.y === b.y && c.y === d.y && a.y === c.y) {
            penalty +=
              Math.max(
                0,
                Math.min(Math.max(a.x, b.x), Math.max(c.x, d.x)) -
                  Math.max(Math.min(a.x, b.x), Math.min(c.x, d.x)),
              ) * 8;
          } else if (a.x === b.x && c.x === d.x && a.x === c.x) {
            penalty +=
              Math.max(
                0,
                Math.min(Math.max(a.y, b.y), Math.max(c.y, d.y)) -
                  Math.max(Math.min(a.y, b.y), Math.min(c.y, d.y)),
              ) * 8;
          } else if (
            a.y === b.y &&
            c.x === d.x &&
            between(c.x, Math.min(a.x, b.x), Math.max(a.x, b.x)) &&
            between(a.y, Math.min(c.y, d.y), Math.max(c.y, d.y))
          ) {
            penalty += 80;
          } else if (
            a.x === b.x &&
            c.y === d.y &&
            between(c.y, Math.min(a.y, b.y), Math.max(a.y, b.y)) &&
            between(a.x, Math.min(c.x, d.x), Math.max(c.x, d.x))
          ) {
            penalty += 80;
          }
        }
        const g = current.g + distance(a, b) + penalty,
          key = nextCell * 3 + nextDirection;
        if (g >= (costs.get(key) ?? Infinity)) {
          continue;
        }
        costs.set(key, g);
        previous.set(key, current.key);
        push({ key, g, f: g + distance(b, end), order: serial++ });
      }
    }
    if (found === undefined) {
      throw new Error('노드가 겹칩니다. 자동 정렬 후 연결선을 정리해 주세요.');
    }
    const middle: LayoutPoint[] = [];
    for (let at: number | undefined = found; at !== undefined; at = previous.get(at)) {
      middle.push(point(Math.floor(at / 3)));
    }
    middle.reverse();
    const points = simplify([wire.from, ...middle, wire.to]);
    routes.set(wire.id, {
      points,
      path: points.map((p, i) => `${i ? 'L' : 'M'}${p.x},${p.y}`).join(' '),
    });
    for (let i = 1; i < points.length; i++) {
      reserved.push({ a: points[i - 1], b: points[i] });
    }
  }
  return routes;
};
