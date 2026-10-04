/** Native dsh runner. Credentials remain in the owning n8n node. */
import {open, realpath, writeFile} from 'node:fs/promises';
import {constants} from 'node:fs';
import {createHash, randomUUID} from 'node:crypto';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
import {execFileSync} from 'node:child_process';

export const name = 'headless-runner';
export const inject = ['agentDefaultModel','agents','sessions','attachments','sessionProjections'];
const fields = ['schema_version','job_id','attempt_id','lease_token','nonce','asset_sha256','input_digest','proposal_digest','policy_digest','manifest_path','manifest_sha256','overlay_path','overlay_sha256','native_execution','model_deadline','expires_at'];
const usageFields = ['uncachedInputTokens','outputTokens','cacheReadTokens','cacheWriteTokens'];
const checks = ['disclosure_visible','captions_readable','portrait_composition','no_obvious_visual_defects'];
const hash = data => createHash('sha256').update(data).digest('hex');
const exactKeys = (value, names) => value && typeof value==='object' && !Array.isArray(value) && Object.keys(value).sort().join(',')===names.slice().sort().join(',');

export function validateEnvelope(task, workspace, now=Date.now()/1000) {
 if(typeof task!=='string' || Buffer.byteLength(task)>8192 || typeof workspace!=='string' || !path.isAbsolute(workspace) || path.resolve(workspace)!==workspace) throw Error('invalid_visual_task');
 const e=JSON.parse(task);
 if(!exactKeys(e,fields) || e.schema_version!==1 || !/^[a-f0-9]{32}$/.test(e.job_id) || !/^[a-f0-9]{32}$/.test(e.attempt_id)) throw Error('invalid_visual_envelope');
 if(!exactKeys(e.native_execution,['execution_id','workflow_id']) || !/^[1-9][0-9]{0,63}$/.test(e.native_execution.execution_id) || typeof e.native_execution.workflow_id!=='string' || !/^[A-Za-z0-9_-]{1,128}$/.test(e.native_execution.workflow_id)) throw Error('invalid_native_execution');
 for(const key of ['asset_sha256','input_digest','proposal_digest','policy_digest','manifest_sha256','overlay_sha256']) if(typeof e[key]!=='string' || !/^[a-f0-9]{64}$/.test(e[key])) throw Error('invalid_visual_digest');
 for(const key of ['lease_token','nonce']) if(typeof e[key]!=='string' || !/^[A-Za-z0-9_-]{32,128}$/.test(e[key])) throw Error('invalid_visual_owner');
 if(!Number.isFinite(e.model_deadline) || e.model_deadline<=now || e.model_deadline>=e.expires_at) throw Error('expired_visual_model_task');
 if(!Number.isFinite(e.expires_at) || e.expires_at<=now || e.expires_at>now+3600) throw Error('expired_visual_task');
 const root=path.join(workspace,'visual',e.job_id,e.attempt_id);
 if(e.manifest_path!==path.join(root,'manifest.json')) throw Error('invalid_visual_manifest_path');
 if(e.overlay_path!==path.join(root,'deepseek-visual.yml')) throw Error('invalid_visual_overlay_path');
 return {envelope:e,root};
}

export async function ownedFile(file, root, maxBytes, expected) {
 if(typeof file!=='string' || !file.startsWith(root+'/') || path.resolve(file)!==file || await realpath(file)!==file || await realpath(root)!==root) throw Error('invalid_visual_input_path');
 const handle=await open(file,constants.O_RDONLY|constants.O_NOFOLLOW|constants.O_NONBLOCK);
 try {
  const before=await handle.stat();
  if(!before.isFile() || before.size<1 || before.size>maxBytes) throw Error('invalid_visual_input_size');
  const buffer=Buffer.alloc(before.size+1);let length=0;
  while(length<buffer.length) {const {bytesRead}=await handle.read(buffer,length,buffer.length-length,null);if(bytesRead===0)break;length+=bytesRead;}
  const after=await handle.stat();
  const data=buffer.subarray(0,length);
  if(length!==before.size || ['dev','ino','size','mtimeMs','ctimeMs'].some(k=>before[k]!==after[k]) || hash(data)!==expected) throw Error('invalid_visual_input_bytes');
  return data;
 } finally {await handle.close();}
}

export async function loadInputs(task, config) {
 const {envelope,root}=validateEnvelope(task,config.workspace);
 await ownedFile(envelope.overlay_path,root,16384,envelope.overlay_sha256);
 const manifest=JSON.parse(await ownedFile(envelope.manifest_path,root,16384,envelope.manifest_sha256));
 if(!exactKeys(manifest,['schema_version','job_id','attempt_id','asset_sha256','frames','prompt']) || manifest.schema_version!==1 || ['job_id','attempt_id','asset_sha256'].some(k=>manifest[k]!==envelope[k]) || typeof manifest.prompt!=='string' || manifest.prompt.length>8000 || !Array.isArray(manifest.frames) || manifest.frames.length!==config.frameCount || config.frameCount<1 || config.frameCount>8) throw Error('invalid_visual_manifest');
 const inputs=[];
 for(const [i,item] of manifest.frames.entries()) {
  if(!exactKeys(item,['path','sha256','bytes','seconds']) || item.path!==path.join(root,`frame-${i}.jpg`) || !/^[a-f0-9]{64}$/.test(item.sha256) || !Number.isFinite(item.seconds) || item.seconds<0) throw Error('invalid_visual_frame');
  const data=await ownedFile(item.path,root,config.maxFrameBytes,item.sha256);
  if(data.length!==item.bytes || data.length<5 || data[0]!==255 || data[1]!==216 || data[2]!==255 || data.at(-2)!==255 || data.at(-1)!==217) throw Error('invalid_visual_jpeg');
  inputs.push({data,mediaType:'image/jpeg',name:path.basename(item.path)});
 }
 return {envelope,root,manifest,inputs};
}

export function measuredUsage(events, firstSeq, projection) {
 const observed=events.some(e=>e.seq>=firstSeq && ((e.type==='assistant/chunk' && e.data.chunk.type==='usage') || (e.type==='assistant/message' && e.data.usage!==undefined)));
 if(!observed)return {usage_observed:false,usage:null};
 const usage=Object.fromEntries(usageFields.map(k=>[k,projection.values.tokenUsage[k]]));
 if(Object.values(usage).some(v=>!Number.isSafeInteger(v)||v<0)) throw Error('invalid_visual_usage');
 return {usage_observed:true,usage};
}

export function classifyFailure(reason) {
 const error=reason?.error;
 const code=String(error?.code||reason?.kind||'UNKNOWN').slice(0,128);
 const status=Number.isInteger(error?.status) && error.status>=100 && error.status<=599 ? error.status:null;
 const retry=Number.isFinite(error?.providerRetryAfterMs) && error.providerRetryAfterMs>=0 ? Math.ceil(error.providerRetryAfterMs):null;
 const category=code==='RATE_LIMIT'?'rate_limit':['AUTH','MISSING_CREDENTIAL'].includes(code)?'auth':code==='TIMEOUT'?'timeout':code==='SERVER'?'provider_unavailable':'model_failed';
 return {category,code,status,retry_after_ms:retry};
}

export function validDecision(value) {
 return exactKeys(value,['passed','checks','reason']) && exactKeys(value.checks,checks) && typeof value.passed==='boolean'
  && Object.values(value.checks).every(v=>typeof v==='boolean') && value.passed===Object.values(value.checks).every(Boolean)
  && typeof value.reason==='string' && value.reason.trim().length>0 && value.reason.length<=2000;
}

async function run(ctx,config) {
 await ctx.get('loader')?.await();
 const {envelope,root,manifest,inputs}=await loadInputs(config.task,config);
 const start=execFileSync('/bin/ps',['-p',String(process.pid),'-o','lstart='],{encoding:'utf8',timeout:2000,env:{...process.env,LC_ALL:'C'}}).trim();
 if(!start)throw Error('native_process_start_unverified');
 await writeFile(path.join(root,'process-start.json'),JSON.stringify({schema_version:1,job_id:envelope.job_id,attempt_id:envelope.attempt_id,nonce:envelope.nonce,pid:process.pid,start_identity:start})+'\n',{flag:'wx',mode:0o600});
 const selection={provider:'deepseek-official',model:'deepseek-flash'};
 const receipt={envelope,outcome:'failed',decision:null,usage_observed:false,usage:null,usage_provenance:{session_id:null,as_of_seq:null},model:selection,observed_at:new Date().toISOString(),failure:classifyFailure({kind:'native_call_not_completed'})};
 let agent,firstSeq;
 try {
  const attachments=await ctx.attachments.saveImages(inputs);
  const require=createRequire(config.sdkPackage);
  const [{installModelSelection},{createUserMessage},{SessionId}]=await Promise.all(['@deepseek-ai/dsh-agent','@deepseek-ai/dsh-llm','@deepseek-ai/dsh-session'].map(p=>import(pathToFileURL(require.resolve(p)).href)));
  ({agent}=await ctx.agents.create({sessionId:SessionId(`session-${randomUUID()}`),meta:{cwd:process.cwd()},agentOptions:{...selection,maxTokens:2500,reasoningEffort:'off'},setup:agentCtx=>{installModelSelection(agentCtx,{current:selection,assembled:undefined});}}));
  await agent.whenIdle();firstSeq=agent.session.seq;
  agent.followup(createUserMessage({content:[{type:'text',text:manifest.prompt},...attachments.map(attachment=>({type:'image',attachment}))],source:{kind:'user'}}));
  await agent.whenIdle();await ctx.sessions.flush(agent.session);
  let text='',reason;
  for(const event of agent.session.events) {
   if(event.seq<firstSeq)continue;
   if(event.type==='assistant/message'){const value=event.data.message.content.filter(b=>b.type==='text').map(b=>b.text).join('');if(value)text=value;}
   if(event.type==='turn/end')reason=event.data.reason;
  }
  Object.assign(receipt,measuredUsage(agent.session.events,firstSeq,ctx.sessionProjections.snapshot(agent.session)));
  receipt.usage_provenance={session_id:agent.session.id,as_of_seq:ctx.sessionProjections.snapshot(agent.session).asOfSeq};
  if(reason?.kind==='completed' && Buffer.byteLength(text)<=16384) {
   receipt.raw_result=text;
   try {const decision=JSON.parse(text);if(!validDecision(decision))throw Error('invalid_schema');receipt.decision=decision;receipt.outcome='completed';receipt.failure=null;}
   catch {receipt.decision=null;receipt.failure={category:'malformed_output',code:'invalid_model_result',status:null,retry_after_ms:null};}
  } else {
   receipt.failure=classifyFailure(reason);
  }
 } catch(error) {
  if(agent && firstSeq!==undefined) {
   await ctx.sessions.flush(agent.session);
   Object.assign(receipt,measuredUsage(agent.session.events,firstSeq,ctx.sessionProjections.snapshot(agent.session)));
   receipt.usage_provenance={session_id:agent.session.id,as_of_seq:ctx.sessionProjections.snapshot(agent.session).asOfSeq};
  }
  receipt.failure=classifyFailure({kind:'error',error:{code:error.code||error.name||'UNKNOWN'}});
 }
 receipt.observed_at=new Date().toISOString();
 // Persist failed usage too, before stdout/appExit. The native node's hard
 // timeout handles processes which cannot produce a terminal receipt.
 await writeFile(path.join(root,'native-receipt.json'),JSON.stringify(receipt)+'\n',{flag:'wx',mode:0o600});
 process.stdout.write(JSON.stringify(receipt)+'\n');ctx.get('appExit')(0);
}

export function apply(ctx,config) {
 if(typeof ctx.get('appExit')!=='function')throw Error('visual_runner_exit_unavailable');
 run(ctx,config).catch(error=>{process.stderr.write('clipping_visual_boundary_failed:'+String(error.code||error.name)+'\n');ctx.get('appExit')(1);});
}
