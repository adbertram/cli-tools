import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, writeFile, symlink, rm, realpath, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {validateEnvelope,loadInputs,measuredUsage,classifyFailure,parseDecision,decisionFailure,run} from '../deploy/visual-runner.mjs';
const hash=v=>createHash('sha256').update(v).digest('hex');

async function fixture() {
 const workspace=await realpath(await mkdtemp(path.join(tmpdir(),'visual-runner-')));
 const job='a'.repeat(32),attempt='b'.repeat(32),root=path.join(workspace,'visual',job,attempt);
 await mkdir(root,{recursive:true});
 const jpeg=Buffer.from([255,216,255,1,2,255,217]),file=path.join(root,'frame-0.jpg');await writeFile(file,jpeg);
 const manifest={schema_version:2,job_id:job,attempt_id:attempt,asset_sha256:'f'.repeat(64),frames:[{path:file,bytes:jpeg.length,sha256:hash(jpeg),seconds:1,caption_expected:true}],prompt:'Return strict review.',caption_cues:[{start:0,end:2}],rendered_duration:4,render_receipt_sha256:'1'.repeat(64)};
 const raw=JSON.stringify(manifest),overlay='trusted overlay';await writeFile(path.join(root,'manifest.json'),raw);await writeFile(path.join(root,'deepseek-visual.yml'),overlay);
 const envelope={schema_version:1,job_id:job,attempt_id:attempt,lease_token:'x'.repeat(43),nonce:'y'.repeat(43),asset_sha256:'f'.repeat(64),input_digest:'c'.repeat(64),proposal_digest:'d'.repeat(64),policy_digest:'e'.repeat(64),manifest_path:path.join(root,'manifest.json'),manifest_sha256:hash(raw),overlay_path:path.join(root,'deepseek-visual.yml'),overlay_sha256:hash(overlay),native_execution:{execution_id:'123',workflow_id:'workflow-test'},model_deadline:Date.now()/1000+30,expires_at:Date.now()/1000+60};
 return {workspace,root,file,envelope,manifest,config:{workspace,frameCount:1,maxFrameBytes:1048576}};
}

test('bounded actual frames validate before native agent construction',async()=>{
 const f=await fixture();try {const result=await loadInputs(JSON.stringify(f.envelope),f.config);assert.equal(result.inputs.length,1);}finally{await rm(f.workspace,{recursive:true});}
});
test('cue coverage, midpoint and typed expectation refuse malformed trusted metadata',async()=>{
 for(const change of ['expectation','cue','midpoint','type']) {
  const f=await fixture();try {
   if(change==='expectation')f.manifest.frames[0].caption_expected=false;
   if(change==='cue')f.manifest.caption_cues[0].end=-1;
   if(change==='midpoint')f.manifest.frames[0].seconds=0.5;
   if(change==='type')f.manifest.frames[0].caption_expected='true';
   const raw=JSON.stringify(f.manifest);await writeFile(f.envelope.manifest_path,raw);f.envelope.manifest_sha256=hash(raw);
   await assert.rejects(loadInputs(JSON.stringify(f.envelope),f.config));
  }finally{await rm(f.workspace,{recursive:true});}
 }
});
test('ASR gap does not require text while another sampled frame checks typography',async()=>{
 const f=await fixture();try {
  const second=path.join(f.root,'frame-1.jpg');const jpeg=Buffer.from([255,216,255,1,2,255,217]);await writeFile(second,jpeg);
  f.manifest.frames.push({path:second,bytes:jpeg.length,sha256:hash(jpeg),seconds:3,caption_expected:false});f.config.frameCount=2;
  const raw=JSON.stringify(f.manifest);await writeFile(f.envelope.manifest_path,raw);f.envelope.manifest_sha256=hash(raw);
  assert.equal((await loadInputs(JSON.stringify(f.envelope),f.config)).inputs.length,2);
 }finally{await rm(f.workspace,{recursive:true});}
});
test('legacy immutable manifest still validates',async()=>{
 const f=await fixture();try {
  f.manifest.schema_version=1;delete f.manifest.caption_cues;delete f.manifest.rendered_duration;delete f.manifest.render_receipt_sha256;delete f.manifest.frames[0].caption_expected;
  const raw=JSON.stringify(f.manifest);await writeFile(f.envelope.manifest_path,raw);f.envelope.manifest_sha256=hash(raw);
  assert.equal((await loadInputs(JSON.stringify(f.envelope),f.config)).manifest.schema_version,1);
 }finally{await rm(f.workspace,{recursive:true});}
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
 assert.equal(classifyFailure({kind:'max-tokens'}).code,'generation_limit');
});

test('native result uses authoritative duplicate-key parser and keeps valid strings',()=>{
 const python=new URL('../.venv/bin/python',import.meta.url).pathname;
 const value={passed:true,checks:{disclosure_visible:true,captions_readable:true,portrait_composition:true,no_obvious_visual_defects:true},reason:'Literal text: {"passed":true,"passed":false} is untrusted caption data.'};
 assert.deepEqual(parseDecision(JSON.stringify(value),python),value);
 for(const text of [JSON.stringify(value).replace('{"passed":true','{"passed":true,"passed":true'),JSON.stringify(value).replace('"captions_readable":true','"captions_readable":true,"captions_readable":true'),JSON.stringify(value).replace('"passed":true','"passed":NaN'),'{"passed":true,"\\u0070assed":true}'])assert.throws(()=>parseDecision(text,python));
 assert.throws(()=>parseDecision('x'.repeat(16385),python));
});

test('parser infrastructure failure is distinct from malformed model JSON',()=>{
 const python=new URL('../.venv/bin/python',import.meta.url).pathname;
 const category=(text,executable,execute)=>{try{parseDecision(text,executable,execute);assert.fail('must refuse');}catch(error){return decisionFailure(error);}};
 assert.equal(category('{"passed":true,"passed":false}',python).category,'malformed_output');
 assert.equal(category('{}','/nonexistent-clipping-parser').code,'parser_unavailable');
 const timedOut=()=>{throw Object.assign(Error('private diagnostic'),{code:'ETIMEDOUT'});};
 assert.deepEqual(category('{}',python,timedOut),{category:'model_failed',code:'parser_timeout',status:null,retry_after_ms:null});
 const importFailed=()=>{throw Object.assign(Error('private import traceback'),{status:1});};
 assert.equal(category('{}',python,importFailed).category,'model_failed');
 assert.equal(category('{}',python,importFailed).code,'parser_unavailable');
});

test('current no-Ad decision uses explicit attribution and disclaimer checks',async()=>{
 const {validDecision,parseDecision}=await import('../deploy/visual-runner.mjs');
 const expected=['captions_readable','portrait_composition','no_obvious_visual_defects','required_attribution_visible','no_added_ad_disclaimer'];
 const decision={passed:true,checks:Object.fromEntries(expected.map(name=>[name,true])),reason:'Current explicit labels and no added disclaimer.'};
 assert.equal(validDecision(decision,expected),true);
 assert.equal(validDecision(decision),false);
 const execute=()=>JSON.stringify(decision);
 assert.deepEqual(parseDecision(JSON.stringify(decision),'/trusted/python',execute,expected),decision);
});


test('visual timing fsync failure cannot suppress emitted terminal receipt',async()=>{
 const f=await fixture();let output='',exit;
 const original=process.stdout.write;
 try {
  const usage={uncachedInputTokens:2,outputTokens:3,cacheReadTokens:0,cacheWriteTokens:0};
  const decision={passed:true,checks:{disclosure_visible:true,captions_readable:true,portrait_composition:true,no_obvious_visual_defects:true},reason:'fixture'};
  const session={id:'test-session',seq:0,events:[]};
  const agent={session,whenIdle:async()=>{},followup:()=>{session.events.push({seq:1,type:'assistant/message',data:{usage,message:{content:[{type:'text',text:JSON.stringify(decision)}]}}},{seq:2,type:'turn/end',data:{reason:{kind:'completed'}}});}};
  const ctx={get:key=>key==='appExit'?code=>{exit=code;}:undefined,attachments:{saveImages:async()=>[]},agents:{create:async()=>({agent})},sessions:{flush:async()=>{}},sessionProjections:{snapshot:()=>({asOfSeq:2,values:{tokenUsage:usage}})}};
  const config={...f.config,task:JSON.stringify(f.envelope),pythonExecutable:path.resolve('.venv/bin/python')};
  process.stdout.write=(value)=>{output+=value;return true;};
  await run(ctx,config,async()=>({installModelSelection:()=>{},createUserMessage:value=>value,SessionId:value=>value}),async()=>{throw Error('injected timing link failure');});
  assert.equal(exit,0);
  const emitted=JSON.parse(output);assert.equal(emitted.outcome,'completed');assert.deepEqual(emitted.usage,usage);
  assert.deepEqual(JSON.parse(await readFile(path.join(f.root,'native-receipt.json'),'utf8')),emitted);
  await assert.rejects(readFile(path.join(f.root,'runtime.json')),{code:'ENOENT'});
 }finally {process.stdout.write=original;await rm(f.workspace,{recursive:true});}
});

test('caught documented visual provider failure retains long Retry-After and measured usage',async()=>{
 const f=await fixture();let output='',idle=0;
 const original=process.stdout.write;
 try {
  const usage={uncachedInputTokens:2,outputTokens:3,cacheReadTokens:0,cacheWriteTokens:0};
  const session={id:'test-session',seq:0,events:[]};
  const agent={session,whenIdle:async()=>{if(++idle===2)throw Object.assign(Error('SECRET'),{failure:{code:'SERVER',status:503,providerRetryAfterMs:172800000,message:'SECRET'}});},followup:()=>{session.events.push({seq:1,type:'assistant/message',data:{usage,message:{content:[]}}});}};
  const ctx={get:key=>key==='appExit'?()=>{}:undefined,attachments:{saveImages:async()=>[]},agents:{create:async()=>({agent})},sessions:{flush:async()=>{}},sessionProjections:{snapshot:()=>({asOfSeq:2,values:{tokenUsage:usage}})}};
  process.stdout.write=value=>{output+=value;return true;};
  await run(ctx,{...f.config,task:JSON.stringify(f.envelope)},async()=>({installModelSelection:()=>{},createUserMessage:value=>value,SessionId:value=>value}));
  const emitted=JSON.parse(output);assert.equal(emitted.outcome,'failed');assert.deepEqual(emitted.usage,usage);
  assert.deepEqual(emitted.failure,{category:'provider_unavailable',code:'SERVER',status:503,retry_after_ms:172800000});
  assert.equal(output.includes('SECRET'),false);
 }finally{process.stdout.write=original;await rm(f.workspace,{recursive:true});}
});


test('native generation limit is typed and supported selection disables thinking',async()=>{
 const f=await fixture();let output='',selected=false;
 const original=process.stdout.write;
 try {
  const usage={uncachedInputTokens:9468,outputTokens:2048,cacheReadTokens:0,cacheWriteTokens:0};
  const session={id:'limit-session',seq:0,events:[]};
  const agent={session,whenIdle:async()=>{},followup:()=>{session.events.push({seq:1,type:'assistant/message',data:{usage,message:{content:[{type:'reasoning',text:'private reasoning'}]}}},{seq:2,type:'turn/end',data:{reason:{kind:'max-tokens'}}});}};
  const ctx={get:key=>key==='appExit'?()=>{}:undefined,attachments:{saveImages:async()=>[]},agents:{create:async options=>{assert.equal(Object.hasOwn(options.agentOptions,'reasoningEffort'),false);assert.equal(options.setup({}),undefined);return {agent};}},sessions:{flush:async()=>{}},sessionProjections:{snapshot:()=>({asOfSeq:2,values:{tokenUsage:usage}})}};
  process.stdout.write=value=>{output+=value;return true;};
  await run(ctx,{...f.config,task:JSON.stringify(f.envelope)},async()=>({installModelSelection:(_ctx,selection)=>{assert.deepEqual(selection.current,{provider:'deepseek-official',model:'deepseek-flash',reasoningEffort:'off'});selected=true;},createUserMessage:value=>value,SessionId:value=>value}));
  const receipt=JSON.parse(output);assert.equal(receipt.outcome,'failed');assert.equal(receipt.decision,null);assert.deepEqual(receipt.failure,{category:'model_failed',code:'generation_limit',status:null,retry_after_ms:null});assert.deepEqual(receipt.usage,usage);assert.ok(receipt.usage_observed);assert.ok(selected);assert.equal(output.includes('private reasoning'),false);
 }finally {process.stdout.write=original;await rm(f.workspace,{recursive:true});}
});
