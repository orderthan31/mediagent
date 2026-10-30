import test from 'node:test';
import assert from 'node:assert/strict';
import { publicAgentGraph } from '../src/job-graphs.ts';
import { createAgentWorkflow } from '../src/workflow-templates.ts';
test('detail never falls back to the internal transport graph', () => {
  const native = {
    catalog_version: 1,
    revision: 2,
    name: 'transport',
    inputs: { video: 'video' },
    nodes: [
      { id: 'transcription__analyze', type: 'analyze', position: { x: 0, y: 0 }, options: {} },
    ],
    edges: [],
  };
  assert.equal(publicAgentGraph({ snapshot: { definition: native } }), null);
  const publicGraph = createAgentWorkflow();
  assert.equal(
    publicAgentGraph({ snapshot: { definition: publicGraph, tool_definition: native } }),
    publicGraph,
  );
  assert.equal(
    publicAgentGraph({
      snapshot: { definition: native },
      agent_workflow: { definition: publicGraph },
    }),
    publicGraph,
  );
});
