import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, writeFile, symlink, rm, realpath} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {validateEnvelope,loadInputs,measuredUsage,classifyFailure} from '../deploy/visual-runner.mjs';
const hash=v=>createHash('sha256').update(v).digest('hex');

async function fixture() {
 const workspace=await realpath(await mkdtemp(path.join(tmpdir(),'visual-runner-')));
 const job='a'.repeat(32),attempt='b'.repeat(32),root=path.join(workspace,'visual',job,attempt);
 await mkdir(root,{recursive:true});
 const jpeg=Buffer.from([255,216,255,1,2,255,217]),file=path.join(root,'frame-0.jpg');await writeFile(file,jpeg);
 const manifest={schema_version:1,job_id:job,attempt_id:attempt,asset_sha256:'f'.repeat(64),frames:[{path:file,bytes:jpeg.length,sha256:hash(jpeg),seconds:1}],prompt:'Return strict review.'};
 const raw=JSON.stringify(manifest),overlay='trusted overlay';await writeFile(path.join(root,'manifest.json'),raw);await writeFile(path.join(root,'deepseek-visual.yml'),overlay);
 const envelope={schema_version:1,job_id:job,attempt_id:attempt,lease_token:'x'.repeat(43),nonce:'y'.repeat(43),asset_sha256:'f'.repeat(64),input_digest:'c'.repeat(64),proposal_digest:'d'.repeat(64),policy_digest:'e'.repeat(64),manifest_path:path.join(root,'manifest.json'),manifest_sha256:hash(raw),overlay_path:path.join(root,'deepseek-visual.yml'),overlay_sha256:hash(overlay),native_execution:{execution_id:'123',workflow_id:'workflow-test'},model_deadline:Date.now()/1000+30,expires_at:Date.now()/1000+60};
 return {workspace,root,file,envelope,config:{workspace,frameCount:1,maxFrameBytes:1048576}};
}

test('bounded actual frames validate before native agent construction',async()=>{
 const f=await fixture();try {const result=await loadInputs(JSON.stringify(f.envelope),f.config);assert.equal(result.inputs.length,1);}finally{await rm(f.workspace,{recursive:true});}
});
test('unknown paths, expired lease and altered digests reject',async()=>{
 const f=await fixture();try {
  for(const change of [{job_id:'../other'},{expires_at:0},{manifest_path:'/tmp/unknown'},{overlay_path:'/tmp/unknown'},{asset_sha256:123}])assert.throws(()=>validateEnvelope(JSON.stringify({...f.envelope,...change}),f.workspace));
  await writeFile(f.file,'changed');await assert.rejects(loadInputs(JSON.stringify(f.envelope),f.config));
 }finally{await rm(f.workspace,{recursive:true});}
});
test('symlinked frame refuses even with matching bytes',async()=>{
 const f=await fixture();try {await rm(f.file);const target=path.join(f.root,'outside');await writeFile(target,Buffer.from([255,216,255,1,2,255,217]));await symlink(target,f.file);await assert.rejects(loadInputs(JSON.stringify(f.envelope),f.config));}finally{await rm(f.workspace,{recursive:true});}
});
test('projection default zeros do not fabricate observed usage',()=>{
 const projection={values:{tokenUsage:{uncachedInputTokens:0,outputTokens:0,cacheReadTokens:0,cacheWriteTokens:0}}};
 assert.deepEqual(measuredUsage([],0,projection),{usage_observed:false,usage:null});
});
test('chunk plus message usage reads projection once rather than summing',()=>{
 const usage={uncachedInputTokens:156,outputTokens:1,cacheReadTokens:1920,cacheWriteTokens:0};
 const events=[{seq:1,type:'assistant/chunk',data:{chunk:{type:'usage'}}},{seq:2,type:'assistant/message',data:{usage:{}}}];
 assert.deepEqual(measuredUsage(events,0,{values:{tokenUsage:usage}}),{usage_observed:true,usage});
});
test('documented provider errors preserve Retry-After without raw messages',()=>{
 assert.deepEqual(classifyFailure({kind:'error',error:{code:'RATE_LIMIT',status:429,providerRetryAfterMs:12345,message:'SECRET'}}),{category:'rate_limit',code:'RATE_LIMIT',status:429,retry_after_ms:12345});
 for(const [code,category] of [['AUTH','auth'],['SERVER','provider_unavailable'],['TIMEOUT','timeout'],['QUOTA_EXCEEDED','model_failed']])assert.equal(classifyFailure({kind:'error',error:{code}}).category,category);
 assert.equal(classifyFailure({kind:'max-tokens'}).code,'max-tokens');
});
