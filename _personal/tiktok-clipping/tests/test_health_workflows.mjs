import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const load=kind=>JSON.parse(readFileSync(new URL(`../deploy/workflows/${kind}.json`,import.meta.url),'utf8'));
const source=(w,name)=>w.nodes.find(n=>n.name===name).parameters.jsCode;
const run=(js,input,original)=>vm.runInNewContext('(function(){'+js+'})()',{Buffer,Date,$input:{first:()=>({json:input})},$:()=>({first:()=>({json:original})})});

test('all four graphs inactive with one health gate and the verified owning error handler',()=>{
 for(const kind of ['clip','learn','metrics','maintain']) {
  const w=load(kind);
  assert.equal(w.active,false);assert.equal(w.settings.errorWorkflow,'F79g2nlj6f1glf8u');
  assert.equal(w.nodes.filter(n=>n.name==='Check operational health').length,1);
  assert.equal(w.connections['Read operational health'].main[0][0].node,'Check operational health');
 }
});

test('clip completion filters select exactly one idle/render/visual completion path',()=>{
 const w=load('clip');
 const cases=[{ready:false,state:'idle'},{ready:false,state:'paused'},{ready:false,state:'waiting'},
  {ready:false,state:'blocked',action_result:{state:'blocked'}},
  {ready:false,state:'visual_pending',action_result:{state:'visual_pending',visual:{}}},
  {ready:true,state:'leased'}];
 for(const d of cases) {
  const idle=run(source(w,'Complete idle work'),d);
  assert.equal(idle.length,!d.ready && d.state!=='visual_pending'?1:0);
 }
 for(const state of ['blocked','published','ready','visual_pending']) {
  assert.equal(run(source(w,'Complete render work'),{state}).length,state==='visual_pending'?0:1);
 }
 assert.equal(w.connections['Validate visual receipt'].main[0][0].node,'Read operational health');
 assert.equal(w.nodes.find(n=>n.name==='DeepSeek visual review').continueOnFail,true);
 assert.match(w.nodes.find(n=>n.name==='Validate visual receipt').parameters.command,/--n8n-workflow-id \{\{\$workflow.id\}\}/);
});

test('health raises only actionable sanitized evidence; idle/cooldown/paused/staged continue',()=>{
 const js=source(load('clip'),'Check operational health');
 for(const state of ['healthy','cooldown','paused','staged']) {
  assert.equal(run(js,{stdout:JSON.stringify({state,health:{state,actionable:false,issues:[]}})}).length,1);
 }
 assert.throws(()=>run(js,{stdout:JSON.stringify({health:{actionable:true,state:'action_required',issues:[{reason:'publication_outcome_unknown',request_id:'trusted'}]}})}),/CLIPPING_OPERATIONAL_FAILURE/);
 assert.throws(()=>run(js,{stdout:'{}'}),/health contract/);
});

test('visual bridge preserves valid receipt bytes even after wrapper failure',()=>{
 const w=load('clip'),envelope={attempt_id:'a'.repeat(32),job_id:'b'.repeat(32)};
 const receipt=' {"envelope":'+JSON.stringify(envelope)+',"usage":{"outputTokens":5},"outcome":"failed"}\n';
 for(const native of [{result:receipt},{error:'private cookie text',stdout:receipt,timedOut:true}]) {
  const output=run(source(w,'Encode visual receipt'),native,{visual:envelope});
  assert.equal(Buffer.from(output[0].json.stdinB64,'base64').toString('utf8'),receipt);
 }
});

test('missing visual receipt creates original-attempt unknown-usage failure without provider prose',()=>{
 const js=source(load('clip'),'Encode visual receipt'),envelope={attempt_id:'a'.repeat(32),job_id:'b'.repeat(32)};
 for(const timedOut of [false,true]) {
  const output=run(js,{error:'secret auth RATE_LIMIT Retry-After=1000',stdout:'private nonjson',timedOut},{visual:envelope});
  const receipt=JSON.parse(Buffer.from(output[0].json.stdinB64,'base64').toString('utf8'));
  assert.deepEqual(receipt.envelope,envelope);assert.equal(receipt.usage,null);assert.equal(receipt.usage_observed,false);
  assert.equal(receipt.decision,null);assert.equal(receipt.failure.retry_after_ms,null);
  assert.equal(receipt.failure.category,timedOut?'timeout':'model_failed');
  assert(!JSON.stringify(receipt).includes('secret'));
 }
 assert.throws(()=>run(js,{result:'{"envelope":{"job_id":"foreign"}}'},{visual:envelope}),/envelope changed/);
 for(const native of [{},{result:42},{reasoning:'private prose'}]) {
  const output=run(js,native,{visual:envelope});
  const receipt=JSON.parse(Buffer.from(output[0].json.stdinB64,'base64').toString('utf8'));
  assert.deepEqual(receipt.envelope,envelope);
  assert.equal(receipt.failure.code,'native_receipt_missing');
  assert.equal(receipt.usage,null);assert.equal(receipt.decision,null);
 }
});
