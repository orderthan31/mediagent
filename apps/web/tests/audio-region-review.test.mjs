import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resolvePorts } from '../src/workflow-spec.ts';
test('audio region review exposes the explicit additional CAS output only for its chosen mode', () => {
  const spec = {
    inputs: { value: 'video' },
    outputs: { value: 'video' },
    options: { data_type: ['video', 'audio'], review_kind: ['approve_only', 'audio_regions_v1'] },
    port_types_from_options: { inputs: { value: 'data_type' }, outputs: { value: 'data_type' } },
    conditional_outputs: { review_kind: { audio_regions_v1: { regions: 'audio_regions' } } },
  };
  assert.deepEqual(
    resolvePorts(spec, { data_type: 'audio', review_kind: 'audio_regions_v1' }).outputs,
    { value: 'audio', regions: 'audio_regions' },
  );
  assert.deepEqual(resolvePorts(spec, { data_type: 'audio' }).outputs, { value: 'audio' });
  assert.deepEqual(spec.outputs, { value: 'video' });
});

import * as forms from '../src/form-contract.ts';
const orderedFields = forms.orderedFields;
test('explicit form field order survives JSONB-style key order without hiding fields', () => {
  const props = {
    end: { type: 'number', title: '끝' },
    kind: { type: 'string', title: '종류' },
    start: { type: 'number', title: '시작' },
  };
  assert.equal(typeof orderedFields, 'function');
  assert.deepEqual(
    orderedFields({
      type: 'object',
      title: '구간',
      properties: props,
      propertyOrder: ['start', 'end', 'kind'],
    }).map(([key]) => key),
    ['start', 'end', 'kind'],
  );
  assert.deepEqual(
    orderedFields({ type: 'object', title: '구간', properties: props }).map(([key]) => key),
    ['end', 'kind', 'start'],
  );
});
