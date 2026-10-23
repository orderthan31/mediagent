import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = ts.createSourceFile(
  'WorkflowCanvas.tsx',
  fs.readFileSync(new URL('../src/WorkflowCanvas.tsx', import.meta.url), 'utf8'),
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TSX,
);
const handler = (name, context) => {
  let expression;
  const visit = (node) => {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === name) {
      expression = node.initializer;
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  assert.ok(expression, `actual component handler ${name} exists`);
  const text = ts.transpileModule(`(${expression.getText(source)})`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return vm.runInNewContext(text, context);
};

const viewportHandler = (name, context, className = 'workflow-graph-viewport') => {
  let expression;
  const visit = (node) => {
    if (ts.isJsxOpeningElement(node)) {
      const attributes = node.attributes.properties;
      if (
        attributes.some(
          (a) =>
            ts.isJsxAttribute(a) &&
            a.name.getText(source) === 'className' &&
            a.initializer?.text === className,
        )
      ) {
        const attribute = attributes.find(
          (a) => ts.isJsxAttribute(a) && a.name.getText(source) === name,
        );
        expression = attribute?.initializer?.expression;
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  assert.ok(expression, `actual viewport ${name} exists`);
  return ts.isIdentifier(expression)
    ? handler(expression.text, context)
    : vm.runInNewContext(
        ts.transpileModule(`(${expression.getText(source)})`, {
          compilerOptions: { target: ts.ScriptTarget.ES2022 },
        }).outputText,
        context,
      );
};

test('node touch movement changes only position and preserves options, model pins, fallback and edges', () => {
  const definition = {
    nodes: [
      {
        id: 'translated',
        type: 'translate',
        position: { x: 100, y: 200 },
        options: { target_language: 'ko' },
        model_ref: { model_id: 'a'.repeat(32), revision: 2 },
        fallback_refs: [{ model_id: 'b'.repeat(32), revision: 3 }],
      },
    ],
    edges: [
      {
        id: 'fixed-edge',
        source: { node: '$input', port: 'transcript' },
        target: { node: 'translated', port: 'transcript' },
      },
    ],
  };
  const before = JSON.stringify(definition);
  let changed;
  const context = {
    definition,
    nodeDrag: { current: { pointerId: 7, id: 'translated', x: 100, y: 200, px: 10, py: 20 } },
    view: { scale: 2 },
    disabled: false,
    onChange: (value) => {
      changed = value;
    },
  };
  viewportHandler(
    'onPointerMove',
    context,
    'workflow-node-heading',
  )({ pointerId: 7, clientX: 20, clientY: 40 });
  assert.equal(JSON.stringify(definition), before);
  const actual = JSON.parse(JSON.stringify(changed));
  assert.deepEqual(actual.nodes[0].position, { x: 100 + (20 - 10) / 2, y: 200 + (40 - 20) / 2 });
  const strip = (value) => value.nodes.map(({ position, ...node }) => node);
  assert.deepEqual(strip(actual), strip(definition));
  assert.deepEqual(actual.edges, definition.edges);
});

test('another touch pointer cannot move an active pan', () => {
  const pan = { current: { pointerId: 7, x: 10, y: 20, px: 2, py: 3 } };
  const queued = [];
  handler('movePointer', {
    pan,
    setView: (update) => queued.push(update),
    source: null,
    viewport: { current: null },
    setCursor() {},
  })({ pointerId: 8, clientX: 30, clientY: 40 });
  assert.equal(queued.length, 0);
});

test('lost capture clears only its own pan/node/wire and cancels unfinished wire selection', () => {
  const pan = { current: { pointerId: 7 } },
    nodeDrag = { current: { pointerId: 7 } },
    wireDrag = { current: { pointerId: 7 } };
  const sources = [];
  const lost = viewportHandler('onLostPointerCapture', {
    pan,
    nodeDrag,
    wireDrag,
    setSource: (x) => sources.push(x),
  });
  const currentTarget = { hasPointerCapture: () => false };
  lost({ pointerId: 8, type: 'lostpointercapture', currentTarget });
  assert.ok(pan.current && nodeDrag.current && wireDrag.current);
  lost({ pointerId: 7, type: 'lostpointercapture', currentTarget });
  assert.equal(pan.current, null);
  assert.equal(nodeDrag.current, null);
  assert.equal(wireDrag.current, null);
  assert.deepEqual(sources, [null]);
});

test('queued touch pan survives release/cancel and changed event coordinates before React evaluates it', () => {
  const pan = { current: { pointerId: 7, x: 10, y: 20, px: 2, py: 3 } };
  const queued = [];
  const move = handler('movePointer', {
    pan,
    setView: (update) => queued.push(update),
    source: null,
    viewport: { current: null },
    setCursor() {},
  });
  const event = { pointerId: 7, clientX: 15, clientY: 23 };
  move(event);
  pan.current = null;
  event.clientX = 999;
  event.clientY = 999;
  assert.equal(queued.length, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(queued[0]({ x: 0, y: 0, scale: 0.8 }))), {
    x: 23,
    y: 40,
    scale: 0.8,
  });
});
