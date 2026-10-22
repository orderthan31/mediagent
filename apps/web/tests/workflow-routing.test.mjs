import { test } from 'node:test';
import assert from 'node:assert/strict';
import { routeConnections } from '../src/workflow-routing.ts';

const boxes = [
  { id: 'source', x: 24, y: 100, width: 260, height: 180 },
  { id: 'obstacle', x: 450, y: 40, width: 260, height: 300 },
  { id: 'target', x: 950, y: 100, width: 260, height: 180 },
];
const wire = {
  id: 'same-edge-id',
  source: { node: 'source', port: 'a' },
  target: { node: 'target', port: 'value' },
  from: { x: 284, y: 190 },
  to: { x: 950, y: 190 },
};
const nestedBoxes = [
  { id: '$input', x: 20, y: 24, width: 210, height: 149 },
  { id: 'split', x: 350, y: 232, width: 210, height: 152 },
  { id: 'left', x: 680, y: 24, width: 210, height: 128 },
  { id: 'right', x: 680, y: 232, width: 210, height: 128 },
  { id: 'join', x: 1010, y: 24, width: 210, height: 171 },
  { id: 'translated', x: 350, y: 24, width: 210, height: 128 },
];
const connection = (id, source, port, target, targetPort, x, y, xx, yy) => ({
  id,
  source: { node: source, port },
  target: { node: target, port: targetPort },
  from: { x, y },
  to: { x: xx, y: yy },
});
const nestedWires = [
  connection('root-video', '$input', 'video', 'split', 'value', 230, 129.59, 350, 334.78),
  connection('left-review', 'split', 'a', 'left', 'value', 560, 334.78, 680, 126.78),
  connection('right-review', 'split', 'b', 'right', 'value', 560, 358.78, 680, 334.78),
  connection('join-left', 'split', 'a', 'join', 'left', 560, 334.78, 1010, 146.37),
  connection('join-right', 'right', 'value', 'join', 'right', 890, 334.78, 1010, 170.37),
  connection(
    'root-text',
    '$input',
    'transcript',
    'translated',
    'transcript',
    230,
    87.59,
    350,
    126.78,
  ),
];

test('branch merge does not cross unrelated incoming wires at adjacent target ports', () => {
  const routes = routeConnections(nestedBoxes, nestedWires);
  for (let i = 0; i < nestedWires.length; i++) {
    const left = nestedWires[i];
    for (const right of nestedWires.slice(i + 1)) {
      if (left.source.node === right.source.node && left.source.port === right.source.port) {
        continue;
      }
      const aa = routes.get(left.id).points,
        bb = routes.get(right.id).points;
      for (let j = 1; j < aa.length; j++) {
        for (let k = 1; k < bb.length; k++) {
          const a = aa[j - 1],
            b = aa[j],
            c = bb[k - 1],
            d = bb[k];
          const cross =
            a.y === b.y && c.x === d.x
              ? c.x >= Math.min(a.x, b.x) &&
                c.x <= Math.max(a.x, b.x) &&
                a.y >= Math.min(c.y, d.y) &&
                a.y <= Math.max(c.y, d.y)
              : a.x === b.x &&
                c.y === d.y &&
                a.x >= Math.min(c.x, d.x) &&
                a.x <= Math.max(c.x, d.x) &&
                c.y >= Math.min(a.y, b.y) &&
                c.y <= Math.max(a.y, b.y);
          assert.equal(cross, false, `${left.id} crosses ${right.id}`);
        }
      }
    }
  }
});

const hits = (a, b, r) =>
  a.y === b.y
    ? a.y > r.y &&
      a.y < r.y + r.height &&
      Math.max(a.x, b.x) > r.x &&
      Math.min(a.x, b.x) < r.x + r.width
    : a.x > r.x &&
      a.x < r.x + r.width &&
      Math.max(a.y, b.y) > r.y &&
      Math.min(a.y, b.y) < r.y + r.height;

test('orthogonal cleanup bypasses an intervening long-name node without retargeting ports', () => {
  const before = JSON.stringify({ boxes, wire });
  const route = routeConnections(boxes, [wire]).get(wire.id);
  assert.ok(route.points.length > 2);
  assert.deepEqual(route.points[0], wire.from);
  assert.deepEqual(route.points.at(-1), wire.to);
  assert.match(route.path, /^M/);
  assert.ok(!route.path.includes('C'));
  for (let i = 1; i < route.points.length; i++) {
    const a = route.points[i - 1],
      b = route.points[i];
    assert.ok(a.x === b.x || a.y === b.y);
    for (const box of boxes) {
      assert.equal(hits(a, b, box), false);
    }
  }
  assert.equal(JSON.stringify({ boxes, wire }), before);
  assert.deepEqual(routeConnections(boxes, [wire]).get(wire.id), route);
});
