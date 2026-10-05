import {startRuntime,preserveReceiptTiming} from './runtime-proof.mjs';
/** Native text-only dsh runner. Credentials stay in DeepSeekHarness. */
import {open, realpath, link, unlink, lstat} from 'node:fs/promises';
import {constants} from 'node:fs';
import {createHash, randomUUID} from 'node:crypto';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {ownedFile, measuredUsage, classifyFailure} from './visual-runner.mjs';

export const name='headless-runner';
export const inject=['agentDefaultModel','agents','sessions','sessionProjections'];
const fields=['schema_version','job_id','attempt_id','kind','lease_token','nonce','input_digest','policy_digest','prompt_digest','manifest_path','manifest_sha256','overlay_path','overlay_sha256','native_execution','model_deadline','expires_at'];
const hash=value=>createHash('sha256').update(value).digest('hex');
const exact=(value,keys)=>value && typeof value==='object' && !Array.isArray(value) && Object.keys(value).sort().join(',')===keys.slice().sort().join(',');
const fail=code=>Object.assign(Error(code),{code});
const maxResultBytes=16384;

export function strictJson(text,pythonExecutable,limit=maxResultBytes,execute=execFileSync) {
 if(typeof text!=='string' || Buffer.byteLength(text)>limit || typeof pythonExecutable!=='string' || !path.isAbsolute(pythonExecutable))throw fail('invalid_model_json');
 let raw;
 try {
  raw=execute(pythonExecutable,['-c','import sys\nfrom tiktok_clipping_cli.safety import strict_json,canonical,SafetyError\ntry:\n print(canonical(strict_json(sys.stdin.buffer.read(int(sys.argv[1])+1),int(sys.argv[1]))))\nexcept (SafetyError,ValueError):\n sys.exit(2)',String(limit)],{input:text,encoding:'utf8',timeout:2000,maxBuffer:limit*6+1024,stdio:['pipe','pipe','ignore']});
 } catch(error) {throw fail(error.status===2?'invalid_model_json':error.code==='ETIMEDOUT'?'parser_timeout':'parser_unavailable');}
 return JSON.parse(raw);
}

export function validateEnvelope(e,workspace,now=Date.now()/1000) {
 if(typeof workspace!=='string' || !path.isAbsolute(workspace) || path.resolve(workspace)!==workspace || !exact(e,fields) || e.schema_version!==1 || !['clip','learn'].includes(e.kind))throw fail('invalid_text_envelope');
 for(const key of ['job_id','attempt_id'])if(typeof e[key]!=='string' || !/^[a-f0-9]{32}$/.test(e[key]))throw fail('invalid_text_identity');
 for(const key of ['input_digest','policy_digest','prompt_digest','manifest_sha256','overlay_sha256'])if(typeof e[key]!=='string' || !/^[a-f0-9]{64}$/.test(e[key]))throw fail('invalid_text_digest');
 for(const key of ['lease_token','nonce'])if(typeof e[key]!=='string' || !/^[A-Za-z0-9_-]{32,128}$/.test(e[key]))throw fail('invalid_text_lease');
 if(!exact(e.native_execution,['execution_id','workflow_id']) || typeof e.native_execution.execution_id!=='string' || !/^[1-9][0-9]{0,63}$/.test(e.native_execution.execution_id) || typeof e.native_execution.workflow_id!=='string' || !/^[A-Za-z0-9_-]{1,128}$/.test(e.native_execution.workflow_id))throw fail('invalid_native_execution');
 if(!Number.isFinite(e.model_deadline) || !Number.isFinite(e.expires_at) || e.model_deadline<=0 || e.model_deadline>=e.expires_at || e.expires_at<=now || e.expires_at>now+3600)throw fail('expired_text_task');
 const root=path.join(workspace,'model',e.job_id,e.attempt_id);
 if(e.manifest_path!==path.join(root,'manifest.json') || e.overlay_path!==path.join(root,'deepseek-text.yml'))throw fail('invalid_text_input_path');
 return {envelope:e,root};
}

export async function loadInputs(config) {
 if(typeof config.task!=='string')throw fail('invalid_text_task');
 const {envelope,root}=validateEnvelope(strictJson(config.task,config.pythonExecutable,8192),config.workspace);
 await ownedFile(envelope.overlay_path,root,16384,envelope.overlay_sha256);
 const bytes=await ownedFile(envelope.manifest_path,root,2*1048576,envelope.manifest_sha256);
 const manifest=strictJson(bytes.toString('utf8'),config.pythonExecutable,2*1048576);
 if(!exact(manifest,['schema_version','job_id','attempt_id','kind','prompt','prompt_digest']) || manifest.schema_version!==1 || ['job_id','attempt_id','kind','prompt_digest'].some(k=>manifest[k]!==envelope[k]) || typeof manifest.prompt!=='string' || !manifest.prompt.trim() || Buffer.byteLength(manifest.prompt)>1048576 || hash(manifest.prompt)!==envelope.prompt_digest)throw fail('invalid_text_manifest');
 return {envelope,root,manifest};
}

/** SDK facts live on turn reason.error or caught LlmError.failure. */
export function failureFacts(value) {
 if(value?.kind==='max-tokens')return classifyFailure(value);
 const facts=value?.failure ?? value?.error;
 if(facts && typeof facts==='object')return classifyFailure({kind:value?.kind||'error',error:facts});
 return classifyFailure({kind:value?.kind||'error',error:{code:value?.code||value?.name||'UNKNOWN'}});
}

export function validResult(kind,value) {
 if(kind==='learn')return exact(value,['weights','exploration']) && value.weights && typeof value.weights==='object' && !Array.isArray(value.weights) && Object.keys(value.weights).length>0 && Object.keys(value.weights).length<=128 && Object.values(value.weights).every(n=>Number.isFinite(n)&&n>=0&&n<=1) && Number.isFinite(value.exploration) && value.exploration>=0 && value.exploration<=1;
 const keys=['start_seconds','end_seconds','caption','style',...(Object.hasOwn(value??{},'segments')?['segments']:[])];
 if(!exact(value,keys) || !Number.isFinite(value.start_seconds) || value.start_seconds<0 || !Number.isFinite(value.end_seconds) || value.end_seconds<=value.start_seconds || typeof value.caption!=='string' || !value.caption.trim() || typeof value.style!=='string' || !value.style.trim())return false;
 if(value.segments!==undefined) {
  if(!Array.isArray(value.segments) || value.segments.length<1 || value.segments.length>4)return false;
  let end=-1;
  for(const segment of value.segments) {
   if(!exact(segment,['start_seconds','end_seconds']) || !Number.isFinite(segment.start_seconds) || segment.start_seconds<0 || segment.start_seconds<end || !Number.isFinite(segment.end_seconds) || segment.end_seconds<=segment.start_seconds)return false;
   end=segment.end_seconds;
  }
  if(value.segments[0].start_seconds!==value.start_seconds || end!==value.end_seconds)return false;
 }
 return true;
}

export function parseResult(text,kind,pythonExecutable,limit=maxResultBytes) {
 const value=strictJson(text,pythonExecutable,limit);
 if(!validResult(kind,value))throw fail('invalid_model_result');
 return value;
}

/** Exclusive durable publication. Retry never replaces an earlier receipt. */
export async function publishReceipt(root,filename,value,io={open,realpath,link,unlink}) {
 if(!['result.json','process-start.json'].includes(filename) || await io.realpath(root)!==root)throw fail('invalid_text_receipt_path');
 const temp=path.join(root,`.${filename}.${randomUUID()}.tmp`),target=path.join(root,filename);
 const directory=await io.open(root,constants.O_RDONLY|constants.O_DIRECTORY|constants.O_NOFOLLOW);
 try {
  const file=await io.open(temp,'wx',0o600);
  try {await file.writeFile(JSON.stringify(value)+'\n');await file.sync();}finally{await file.close();}
  await io.link(temp,target);await directory.sync();
 } finally {
  try {await io.unlink(temp);await directory.sync();}finally{await directory.close();}
 }
}

async function loadSdk(config) {
 const require=createRequire(config.sdkPackage);
 const [{installModelSelection},{createUserMessage},{SessionId}]=await Promise.all(['@deepseek-ai/dsh-agent','@deepseek-ai/dsh-llm','@deepseek-ai/dsh-session'].map(p=>import(pathToFileURL(require.resolve(p)).href)));
 return {installModelSelection,createUserMessage,SessionId};
}

export async function run(ctx,config,sdkLoader=loadSdk,runtimeWriter) {
 const runtimeStarted=startRuntime();
 await ctx.get('loader')?.await();
 const {envelope,root,manifest}=await loadInputs(config);
 const model=config.model;
 if(!exact(model,['provider','model']) || Object.values(model).some(v=>typeof v!=='string'||!v.trim()||v.length>128) || !Number.isSafeInteger(config.maxTokens) || config.maxTokens<1 || typeof config.sdkPackage!=='string' || !path.isAbsolute(config.sdkPackage))throw fail('invalid_text_model_config');
 if(!Number.isSafeInteger(config.maxResultBytes) || config.maxResultBytes<1 || config.maxResultBytes>65536 || !Number.isSafeInteger(config.maxReceiptBytes) || config.maxReceiptBytes<1 || config.maxReceiptBytes>1048576)throw fail('invalid_text_output_limits');
 try {await lstat(path.join(root,'result.json'));throw fail('text_attempt_already_completed');}catch(error){if(error.code!=='ENOENT')throw error;}
 const start=execFileSync('/bin/ps',['-p',String(process.pid),'-o','lstart='],{encoding:'utf8',timeout:2000,env:{...process.env,LC_ALL:'C'}}).trim();
 if(!start)throw fail('native_process_start_unverified');
 const processIdentity={pid:process.pid,start_identity:start};
 await publishReceipt(root,'process-start.json',{schema_version:1,job_id:envelope.job_id,attempt_id:envelope.attempt_id,nonce:envelope.nonce,...processIdentity});
 const receipt={envelope,outcome:'failed',raw_result:null,usage_observed:false,usage:null,usage_provenance:{session_id:null,as_of_seq:null},model:{...model},observed_at:new Date().toISOString(),failure:failureFacts({kind:'native_call_not_completed'})};
 const worstBase={...receipt,usage_observed:true,usage:Object.fromEntries(['uncachedInputTokens','outputTokens','cacheReadTokens','cacheWriteTokens'].map(k=>[k,Number.MAX_SAFE_INTEGER])),usage_provenance:{session_id:'session-'+randomUUID(),as_of_seq:Number.MAX_SAFE_INTEGER},failure:{category:'model_failed',code:'X'.repeat(128),status:599,retry_after_ms:Number.MAX_VALUE}};
 if(Buffer.byteLength(JSON.stringify(worstBase))+1>config.maxReceiptBytes)throw fail('text_receipt_headroom_exhausted');
 let agent,firstSeq;
 const collect=()=>{
  const projection=ctx.sessionProjections.snapshot(agent.session);
  Object.assign(receipt,measuredUsage(agent.session.events,firstSeq,projection));
  receipt.usage_provenance={session_id:agent.session.id,as_of_seq:projection.asOfSeq};
 };
 try {
  if(Date.now()/1000>=envelope.model_deadline)throw fail('text_model_deadline_exceeded');
  const {installModelSelection,createUserMessage,SessionId}=await sdkLoader(config);
  ({agent}=await ctx.agents.create({sessionId:SessionId(`session-${randomUUID()}`),meta:{cwd:process.cwd()},agentOptions:{...model,maxTokens:config.maxTokens},setup:agentCtx=>{installModelSelection(agentCtx,{current:{...model,reasoningEffort:'off'},assembled:undefined});}}));
  await agent.whenIdle();firstSeq=agent.session.seq;
  if(Date.now()/1000>=envelope.model_deadline)throw fail('text_model_deadline_exceeded');
  agent.followup(createUserMessage({content:[{type:'text',text:manifest.prompt}],source:{kind:'user'}}));
  await agent.whenIdle();await ctx.sessions.flush(agent.session);collect();
  let text='',reason;
  for(const event of agent.session.events) {
   if(event.seq<firstSeq)continue;
   if(event.type==='assistant/message') {
    const value=event.data.message.content.filter(b=>b.type==='text').map(b=>b.text).join('');if(value)text=value;
   }
   if(event.type==='turn/end')reason=event.data.reason;
  }
  if(text && Buffer.byteLength(text)<=config.maxResultBytes)receipt.raw_result=text;
  if(Buffer.byteLength(text)>config.maxResultBytes)throw fail('output_limit');
  if(reason?.kind==='completed') {
   parseResult(text,envelope.kind,config.pythonExecutable,config.maxResultBytes);
   if(Date.now()/1000>envelope.model_deadline)throw fail('text_model_deadline_exceeded');
   if(!receipt.usage_observed)throw fail('model_usage_missing');
   receipt.outcome='completed';receipt.failure=null;
  }else receipt.failure=failureFacts(reason);
 }catch(error) {
  if(agent && firstSeq!==undefined) {
   try {await ctx.sessions.flush(agent.session);collect();}
   catch {try {collect();}catch {receipt.usage_observed=false;receipt.usage=null;}}
  }
  if(error.code==='text_model_deadline_exceeded') {receipt.outcome='timeout';receipt.failure={category:'timeout',code:error.code,status:null,retry_after_ms:null};}
  else receipt.failure=['invalid_model_json','invalid_model_result','output_limit'].includes(error.code)?{category:'malformed_output',code:error.code,status:null,retry_after_ms:null}:failureFacts(error);
 }
 receipt.observed_at=new Date().toISOString();
 if(Buffer.byteLength(JSON.stringify(receipt))+1>config.maxReceiptBytes) {receipt.raw_result=null;receipt.outcome='failed';receipt.failure={category:'malformed_output',code:'output_limit',status:null,retry_after_ms:null};}
 if(Buffer.byteLength(JSON.stringify(receipt))+1>config.maxReceiptBytes)throw fail('text_receipt_headroom_exhausted');
 await publishReceipt(root,'result.json',receipt);
 await preserveReceiptTiming(root,envelope,processIdentity,runtimeStarted,JSON.stringify(receipt)+'\n',runtimeWriter);
 return receipt;
}

export function apply(ctx,config) {
 if(typeof ctx.get('appExit')!=='function')throw fail('text_runner_exit_unavailable');
 run(ctx,config).then(receipt=>{process.stdout.write(JSON.stringify(receipt)+'\n');ctx.get('appExit')(0);}).catch(error=>{process.stderr.write('clipping_text_boundary_failed:'+String(error.code||error.name)+'\n');ctx.get('appExit')(1);});
}
