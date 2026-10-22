import { test } from 'node:test';
import assert from 'node:assert/strict';
import { autoArrange, applyLayout } from '../src/workflow-layout.ts';

const box = (id, height = 140) => ({ id, x: 20, y: 24, width: 260, height });
const edge = (id, source, target, port = 'value') => ({
  id,
  source: { node: source, port },
  target: { node: target, port: 'value' },
});
const overlaps = (a, b) =>
  a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
const boxes = [
  box('$input', 190),
  box('split', 180),
  box('left', 250),
  box('right', 220),
  box('join', 160),
];
const edges = [
  edge('e0', '$input', 'split'),
  edge('e1', 'split', 'left', 'a'),
  edge('e2', 'split', 'right', 'b'),
  edge('e3', 'split', 'join', 'a'),
  edge('e4', 'right', 'join'),
];
test('fan-out order follows source port heights rather than unrelated node insertion order', () => {
  const input = { ...box('$input'), sourcePorts: { transcript: 60, video: 110 } };
  const branches = [input, box('video-branch'), box('text-branch')];
  const links = [
    edge('video-first', '$input', 'video-branch', 'video'),
    edge('text-last', '$input', 'text-branch', 'transcript'),
  ];
  const placed = autoArrange(branches, links);
  assert.ok(placed['text-branch'].y < placed['video-branch'].y);
});

test('100-node arrangement preserves the existing server coordinate bounds', () => {
  const all = [box('$input'), ...Array.from({ length: 100 }, (_, index) => box(`n${index}`))];
  const links = all
    .slice(1)
    .map((node, index) => edge(`e${index}`, index ? `n${index - 1}` : '$input', node.id));
  const placed = autoArrange(all, links);
  assert.equal(Object.keys(placed).length, 100);
  const actual = all.map((node) => ({ ...node, ...placed[node.id] }));
  for (const node of actual) {
    assert.ok(node.x >= 0 && node.x <= 4000 && node.y >= 0 && node.y <= 3000);
    for (const other of actual) {
      if (other.id !== node.id) {
        assert.equal(overlaps(node, other), false);
      }
    }
  }
});

test('branch arrangement uses real box heights, stays bounded, and changes positions only', () => {
  const definition = {
    id: 'synthetic',
    revision: 7,
    inputs: { video: 'video' },
    edges,
    nodes: boxes.slice(1).map((b) => ({
      id: b.id,
      type: 'select',
      position: { x: 20, y: 24 },
      options: { selection: 'both', description: '긴 이름과 설정 보존' },
      model_ref: { model_id: 'a'.repeat(32), revision: 2 },
      fallback_refs: [{ model_id: 'b'.repeat(32), revision: 3 }],
    })),
  };
  const before = JSON.stringify(definition);
  const positions = autoArrange(boxes, edges);
  const changed = applyLayout(definition, positions);
  const placed = boxes.map((b) => ({ ...b, ...positions[b.id] }));
  for (let i = 0; i < placed.length; i++) {
    assert.ok(placed[i].x >= 0 && placed[i].x <= 4000 && placed[i].y >= 0 && placed[i].y <= 3000);
    for (let j = i + 1; j < placed.length; j++) {
      assert.equal(overlaps(placed[i], placed[j]), false);
    }
  }
  assert.equal(JSON.stringify(definition), before);
  assert.deepEqual(changed.edges, definition.edges);
  assert.deepEqual(
    changed.nodes.map(({ position, ...n }) => n),
    definition.nodes.map(({ position, ...n }) => n),
  );
  assert.deepEqual(
    applyLayout(changed, Object.fromEntries(definition.nodes.map((n) => [n.id, n.position]))),
    definition,
  );
  assert.deepEqual(autoArrange(boxes, edges), positions);
});
