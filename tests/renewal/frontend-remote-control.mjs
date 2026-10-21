// Real product API/PG + pinned Docker targets. No mocked responses or operating agents.
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { chromium } from '../../apps/web/node_modules/@playwright/test/index.mjs';
const base=process.env.MIDEAGENT_TEST_ORIGIN,out=process.env.MIDEAGENT_CONTROL_EVIDENCE;
assert(base?.startsWith('http://127.0.0.1:')&&out&&process.env.MIDEAGENT_CONTROL_DISPOSABLE==='1');
const cfg=JSON.parse(await readFile(process.env.MIDEAGENT_CONTROL_FIXTURE_CONFIG,'utf8'));
await mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,channel:'msedge'});
const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
page.setDefaultTimeout(12000);
const ledger=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
page.on('request',r=>{if(new URL(r.url()).pathname.endsWith('/configuration'))ledger.push({method:r.method(),body:r.postDataJSON()});});
function fixtureJob(action,...args){
  const r=spawnSync(process.env.MIDEAGENT_CONTROL_PYTHON,[process.env.MIDEAGENT_CONTROL_JOB_HELPER,action,...args],{env:process.env,encoding:'utf8'});
  assert.equal(r.status,0,'Synthetic workload helper failed');return JSON.parse(r.stdout);
}
async function waitFor(check,timeout=25000){const end=Date.now()+timeout;while(Date.now()<end){const v=await check();if(v)return v;await new Promise(r=>setTimeout(r,150));}throw Error('Timed out waiting for real observed state');}
async function state(){const r=await context.request.get(base+'/api/admin/agents/analyze');assert.equal(r.status(),200);return r.json();}
async function settled(count){
  const value=await waitFor(async()=>{const v=await state();return v.observed_replicas===count&&!v.control.phase?v:null;});
  await page.getByRole('region',{name:'에이전트 제어',exact:true}).getByText('확인된 실행 개수: '+count,{exact:true}).waitFor();
  return value;
}
let report={scope:'ISOLATED_PRODUCT_API_UI_FIXED_DOCKER_SYNTHETIC_DRAIN_NOT_OPERATING_OR_BROKER_WORKER_ACCEPTANCE',passed:false};
try{
  const session=await (await context.request.get(base+'/api/auth/session')).json();
  if(session.setup_required){assert.equal((await context.request.post(base+'/api/auth/bootstrap',{data:cfg.admin})).status(),201);}
  const login=await context.request.post(base+'/api/auth/login',{data:cfg.admin});assert.equal(login.status(),200);
  const csrf=(await login.json()).csrf_token,headers={'Origin':base,'X-CSRF-Token':csrf};
  await waitFor(async()=>{const v=await state();return v.manageable;});
  await page.goto(base+'/#/agents/analyze');
  const panel=page.getByRole('region',{name:'에이전트 제어',exact:true});
  await panel.waitFor();
  const field=panel.getByLabel('실행 개수',{exact:true});
  await field.fill('1');await panel.getByRole('button',{name:'시작',exact:true}).click();
  const first=await settled(1);
  await waitFor(async()=>{const v=await state();return v.workers.filter(w=>w.state==='ready').length===1;});
  await page.screenshot({path:join(out,'started-one.png')});
  // HTTP replay of the exact request must not signal the host again.
  const original=ledger[0].body;const replay=await context.request.put(base+'/api/admin/agents/analyze/configuration',{data:original,headers});
  assert.equal(replay.status(),200);assert.equal((await replay.json()).revision,first.revision);
  assert.equal((await state()).revision,first.revision);
  assert.equal((await context.request.put(base+'/api/admin/agents/analyze/configuration',{data:{...original,request_id:crypto.randomUUID().replaceAll('-','')},headers})).status(),409);
  await field.fill('2');await panel.getByRole('button',{name:'개수 적용',exact:true}).click();
  await settled(2);
  await waitFor(async()=>{const v=await state();return v.workers.filter(w=>w.state==='ready').length===2;});
  const target=cfg.workers[1].worker_id;
  const work=fixtureJob('enqueue',target);
  await waitFor(()=>fixtureJob('read',work.id).state==='running');
  await page.getByRole('link',{name:'#'+work.ticket_number,exact:true}).first().waitFor();
  await field.fill('1');await panel.getByRole('button',{name:'개수 적용',exact:true}).click();
  const draining=await waitFor(async()=>{const v=await state();return v.workers.some(w=>w.worker_id===target&&w.state==='stopping'&&w.ticket_id===work.id)?v:null;});
  await page.locator('[data-worker-id="'+target+'"]').getByText('중지 중',{exact:true}).waitFor();
  const second=fixtureJob('enqueue',target);
  assert.equal(fixtureJob('read',second.id).state,'queued');
  await page.screenshot({path:join(out,'busy-shrink-draining.png')});
  await settled(1);
  const done=fixtureJob('read',work.id),pending=fixtureJob('read',second.id);
  assert.equal(done.state,'completed');assert(done.bytes>0&&done.hash_verified);
  assert.equal(pending.state,'queued');assert.equal(pending.worker_id,null);
  await panel.getByRole('button',{name:'중지',exact:true}).click();await settled(0);
  await page.screenshot({path:join(out,'stopped-zero.png')});
  // Every removed slot must stop admissions before one slow slot finishes.
  await field.fill('2');await panel.getByRole('button',{name:'시작',exact:true}).click();await settled(2);
  await waitFor(async()=>{const v=await state();return v.workers.every(w=>w.state==='ready');},40000);
  const both=cfg.workers.map(w=>fixtureJob('enqueue',w.worker_id));
  await waitFor(()=>both.every(j=>fixtureJob('read',j.id).state==='running'));
  await panel.getByRole('button',{name:'중지',exact:true}).click();
  const allDraining=await waitFor(async()=>{const v=await state();return v.workers.every(w=>w.state==='stopping'&&both.some(j=>j.id===w.ticket_id))?v:null;});
  for(const worker of cfg.workers) await page.locator('[data-worker-id="'+worker.worker_id+'"]').getByText('중지 중',{exact:true}).waitFor();
  await page.screenshot({path:join(out,'all-slots-draining.png')});
  const allPending=cfg.workers.map(w=>fixtureJob('enqueue',w.worker_id));
  await settled(0);
  const allDone=both.map(j=>fixtureJob('read',j.id));
  assert(allDone.every(j=>j.state==='completed'&&j.hash_verified));
  assert(allPending.every(j=>fixtureJob('read',j.id).state==='queued'));
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
  await page.screenshot({path:join(out,'mobile-stopped-controls.png')});
  report={...report,all_removed_slots_drained_before_stop:true,all_completed:allDone,all_new_jobs_preserved_queued:allPending,all_draining:allDraining};
  const accounts=(await (await context.request.get(base+'/api/accounts')).json()).accounts;
  if(!accounts.some(a=>a.username===cfg.member.username)){assert.equal((await context.request.post(base+'/api/accounts',{data:cfg.member,headers})).status(),201);}
  const memberContext=await browser.newContext();
  try{
    const memberLogin=await memberContext.request.post(base+'/api/auth/login',{data:cfg.member});assert.equal(memberLogin.status(),200);
    const memberCsrf=(await memberLogin.json()).csrf_token;
    assert.equal((await memberContext.request.get(base+'/api/admin/agents/analyze')).status(),403);
    assert.equal((await memberContext.request.put(base+'/api/admin/agents/analyze/configuration',{data:original,headers:{'Origin':base,'X-CSRF-Token':memberCsrf}})).status(),403);
  }finally{await memberContext.close();}
  assert.deepEqual(errors,[]);
  report={...report,passed:true,counts:[0,1,2,1,0],http_replay_same_revision:true,stale_revision_rejected:true,member_rejected:true,draining_preserved_ticket:draining.workers.find(w=>w.worker_id===target).ticket_id,completed_work:done,new_work_not_admitted:pending,actual_final:await state()};
}catch(error){report={...report,error:String(error),errors};await page.screenshot({path:join(out,'failure.png')});throw error;}
finally{await writeFile(join(out,'result.json'),JSON.stringify({...report,ledger},null,2));await context.close();await browser.close();}
console.log(JSON.stringify({passed:report.passed,counts:report.counts}));
