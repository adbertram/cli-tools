import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const workflow=JSON.parse(readFileSync(new URL('../deploy/workflows/clip.json',import.meta.url),'utf8'));
const source=workflow.nodes.find(node=>node.name==='Require visual review').parameters.jsCode;
const now=1791144767006;
// Exact documented shapes from native render 66550 and prepare retry 66569.
const envelope={schema_version:1,job_id:'8d497009428559c8e677616aa49d9c5d',attempt_id:'830796c6dcecc6598054e98be1df5bdc',expires_at:1791144916.964493};
const run=input=>vm.runInNewContext('(function(){'+source+'})()',{Date:{now:()=>now},$input:{first:()=>({json:input})}});

test('actual Code bridge accepts direct render and nested ready-job retry envelopes',()=>{
 for(const input of [{job_id:envelope.job_id,state:'visual_pending',visual:envelope},{ready:false,state:'visual_pending',action_result:{job_id:envelope.job_id,state:'visual_pending',visual:envelope}}]) {
  const result=run(input);
  assert.equal(result.length,1);
  assert.equal(result[0].json.task,JSON.stringify(envelope));
  assert.equal(result[0].json.visual.job_id,envelope.job_id);
 }
});

test('actual Code bridge refuses malformed/ambiguous/expired visual boundaries',()=>{
 for(const input of [{state:'visual_pending'},{state:'visual_pending',action_result:{state:'visual_pending'}},{state:'visual_pending',visual:null},{state:'visual_pending',visual:envelope,action_result:{state:'visual_pending',visual:envelope}},{state:'visual_pending',visual:{...envelope,expires_at:now/1000}},{state:'visual_pending',action_result:{state:'visual_pending',visual:{...envelope,job_id:'foreign'}}},{state:'idle',visual:envelope}])assert.throws(()=>run(input));
 assert.equal(run({ready:false,state:'idle',reason:'no_eligible_job'}).length,0);
});
