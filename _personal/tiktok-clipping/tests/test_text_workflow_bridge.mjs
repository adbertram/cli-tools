import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const now=1791028800000;
for(const kind of ['clip','learn']) {
 const workflow=JSON.parse(readFileSync(new URL(`../deploy/workflows/${kind}.json`,import.meta.url),'utf8'));
 const node=id=>workflow.nodes.find(n=>n.id===id);
 const envelope={schema_version:1,job_id:'a'.repeat(32),attempt_id:'b'.repeat(32),kind,model_deadline:now/1000+30,expires_at:now/1000+35,native_execution:{execution_id:'123',workflow_id:kind+'-native'}};
 const task=JSON.stringify(Object.fromEntries(Object.entries(envelope).sort()));
 const job={ready:true,job_id:envelope.job_id,text:envelope,task,max_payload_bytes:65536};
 const execute=(id,input,prepared=job)=>vm.runInNewContext('(function(){'+node(id).parameters.jsCode+'})()',{
  Date:{now:()=>now},Buffer,$input:{first:()=>({json:input})},$:name=>{assert.equal(name,'Require leased job');return {first:()=>({json:prepared})};}
 });
 test(kind+' native mapping and idle path are explicit',()=>{
  assert.match(node('prepare-work').parameters.command,/prepare --native-text/);
  assert.match(node('prepare-work').parameters.command,/workflow.id/);
  assert.match(node('validate-and-execute').parameters.command,/jobs apply-text/);
  assert.equal(node('deepseek-analysis').type,'n8n-nodes-agent-harnesses.deepSeekHarness');
  assert.equal(node('deepseek-analysis').continueOnFail,true);
  assert.equal(node('deepseek-analysis').retryOnFail,false);
  assert.equal(execute('require-leased-job',{ready:false,state:'idle'}).length,0);
  assert.equal(execute('require-leased-job',job).length,1);
  assert.throws(()=>execute('require-leased-job',{...job,text:{...envelope,kind:kind==='clip'?'learn':'clip'}}));
  assert.throws(()=>execute('require-leased-job',{...job,task:JSON.stringify({...envelope,attempt_id:'c'.repeat(32)})}));
 });
 test(kind+' receipt raw bytes and original identity survive bridge, reasoning ignored',()=>{
  const raw='{"x":1,"x":2,"caption":"\\nquoted \\\"text\\\""}';
  const output=execute('encode-proposal',{result:raw,reasoning:'SECRET diagnostic must not persist'});
  const payload=JSON.parse(Buffer.from(output[0].json.stdinB64,'base64').toString('utf8'));
  assert.equal(payload.receipt_json,raw);
  assert.equal(payload.native_failure,null);
  assert.deepEqual(payload.envelope,envelope);
  assert.ok(!JSON.stringify(payload).includes('SECRET'));
 });
 test(kind+' native failures preserve only typed process fields, never provider messages',()=>{
  for(const native of [{error:'SECRET',timedOut:true,exitCode:null},{error:'SECRET',exitCode:2,stdout:'committed receipt'}]) {
   const output=execute('encode-proposal',native);
   const payload=JSON.parse(Buffer.from(output[0].json.stdinB64,'base64').toString('utf8'));
   assert.equal(payload.native_failure.timed_out,native.timedOut===true);
   assert.equal(payload.native_failure.exit_code,native.exitCode);
   assert.equal(payload.receipt_json,native.stdout??null);
   assert.ok(!JSON.stringify(payload).includes('SECRET'));
  }
 });
 test(kind+' escaping overflow requests original file recovery without truncation',()=>{
  const raw='\n"\\'.repeat(1000);
  const output=execute('encode-proposal',{result:raw},{...job,max_payload_bytes:1024});
  const text=Buffer.from(output[0].json.stdinB64,'base64').toString('utf8');
  assert.ok(Buffer.byteLength(text)<=1024);
  assert.equal(JSON.parse(text).receipt_json,null);
  assert.deepEqual(JSON.parse(text).envelope,envelope);
 });
}
