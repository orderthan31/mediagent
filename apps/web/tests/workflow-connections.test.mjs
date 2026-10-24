import { test } from 'node:test';
import assert from 'node:assert/strict';
const edit = await import('../src/workflow-connections.ts').catch((error) => {
  if (error.code === 'ERR_MODULE_NOT_FOUND') return {};
  throw error;
});
const boxes = [
  { id: '$input', inputs: {}, outputs: { video: 'video' } },
  { id: 'first', type: 'analyze', inputs: { video: 'video' }, outputs: { value: 'video' } },
  { id: 'second', type: 'encode', inputs: { video: 'video' }, outputs: { video: 'video' } },
  { id: 'other', type: 'encode', inputs: { video: 'video' }, outputs: { video: 'video' } },
];
const wire = {
  id: 'keep-edge-id',
  source: { node: '$input', port: 'video' },
  target: { node: 'second', port: 'video' },
};
test('reconnect a selected endpoint atomically without deleting the old wire first', () => {
  assert.equal(typeof edit.reconnectEdge, 'function');
  const original = [structuredClone(wire)];
  const result = edit.reconnectEdge(
    original,
    wire.id,
    'target',
    { node: 'other', port: 'video' },
    boxes,
  );
  assert.deepEqual(result, [{ ...wire, target: { node: 'other', port: 'video' } }]);
  assert.deepEqual(original, [wire]);
  assert.equal(result[0].id, wire.id);
});

test('an incompatible or occupied replacement leaves the original edge intact', () => {
  const original = [
    structuredClone(wire),
    {
      id: 'busy',
      source: { node: 'first', port: 'value' },
      target: { node: 'other', port: 'video' },
    },
  ];
  const preserved = structuredClone(original);
  assert.throws(
    () => edit.reconnectEdge(original, wire.id, 'target', { node: 'other', port: 'video' }, boxes),
    /이미 연결/,
  );
  assert.throws(
    () =>
      edit.reconnectEdge(original, wire.id, 'target', { node: 'other', port: 'missing' }, boxes),
    /포트/,
  );
  const typed = boxes.map((box) =>
    box.id === 'other' ? { ...box, inputs: { video: 'audio' } } : box,
  );
  assert.throws(
    () => edit.reconnectEdge([wire], wire.id, 'target', { node: 'other', port: 'video' }, typed),
    /자료 유형/,
  );
  assert.deepEqual(original, preserved);
});

test('reject an ordinary cycle while retaining the server explicit Loop.next contract', () => {
  const chain = [
    {
      id: 'one',
      source: { node: 'first', port: 'value' },
      target: { node: 'second', port: 'video' },
    },
    {
      id: 'two',
      source: { node: 'second', port: 'video' },
      target: { node: 'other', port: 'video' },
    },
  ];
  assert.throws(
    () => edit.reconnectEdge(chain, 'one', 'source', { node: 'other', port: 'video' }, boxes),
    /순환/,
  );
  const withLoop = [
    ...boxes,
    {
      id: 'loop',
      type: 'control_loop',
      inputs: { value: 'video', next: 'video' },
      outputs: { body: 'video' },
    },
  ];
  const loopEdges = [
    {
      id: 'back',
      source: { node: 'other', port: 'video' },
      target: { node: 'second', port: 'video' },
    },
    {
      id: 'body',
      source: { node: 'loop', port: 'body' },
      target: { node: 'other', port: 'video' },
    },
  ];
  assert.equal(
    edit.reconnectEdge(loopEdges, 'back', 'target', { node: 'loop', port: 'next' }, withLoop)[0]
      .target.port,
    'next',
  );
});

test('undo a connection change against current node/model settings rather than a stale definition', () => {
  assert.equal(typeof edit.undoEdgeChange, 'function');
  const changed = [{ ...wire, target: { node: 'other', port: 'video' } }];
  const current = {
    id: 'definition',
    revision: 4,
    edges: changed,
    nodes: [
      {
        id: 'second',
        options: { subtitle_mode: 'soft' },
        model_ref: { model_id: 'kept-model', revision: 7 },
      },
    ],
  };
  const restored = edit.undoEdgeChange(current, {
    definition_id: 'definition',
    before: [wire],
    after: changed,
  });
  assert.deepEqual(restored.edges, [wire]);
  assert.equal(restored.nodes, current.nodes);
  assert.equal(restored.revision, 4);
  assert.throws(
    () =>
      edit.undoEdgeChange(
        { ...current, edges: [] },
        { definition_id: 'definition', before: [wire], after: changed },
      ),
    /다른 연결/,
  );
});
