import test from 'node:test';import assert from 'node:assert/strict';
import {startSavedJob} from '../src/job-start.mjs';
test('one start invokes plan, confirmation, admission and dispatch even after reopening',async()=>{
const calls=[];const get=async p=>p.endsWith('/plan')?{ready:true,token:'bound-plan'}:{status:'draft',runs:[]};
const post=async(p,b)=>{calls.push([p,b]);return p.endsWith('/confirm')?{id:'consent'}:{status:'running'}};
await startSavedJob(get,post,'job','click');assert.deepEqual(calls.map(c=>c[0].split('/').at(-1)),['prepare-start','confirm','admit','run']);assert.equal(calls[2][1].consent_id,'consent');
});
test('an already started job is not dispatched again',async()=>{let calls=0;await assert.rejects(()=>startSavedJob(async()=>({status:'running',runs:[{}]}),async()=>{calls++},'job','new-click'));assert.equal(calls,0)});
