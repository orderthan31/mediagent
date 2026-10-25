import { test } from 'node:test';
import assert from 'node:assert/strict';
import { supportsModelRole,nodeModelRoles } from '../src/registered-models.ts';
test('vocalization requires explicit audio event capability, not a multimodal or ASR name',()=>{
 const model={model_types:['multimodal'],input_modalities:['audio','text'],output_modalities:['text'],capabilities:['speech_recognition','structured_output']};
 assert.equal(nodeModelRoles.vocalize,'vocalization');
 assert.equal(supportsModelRole(model,'vocalization'),false);
 assert.equal(supportsModelRole({...model,capabilities:[...model.capabilities,'vocalization_classification']},'vocalization'),true);
 assert.equal(supportsModelRole({...model,capabilities:['vocalization_classification']},'vocalization'),false);
});
