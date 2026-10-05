// Trusted process timing is accounting evidence, never action authorization.
import {constants} from 'node:fs';
import {performance} from 'node:perf_hooks';
import {createHash} from 'node:crypto';
import {open,link,unlink,realpath} from 'node:fs/promises';
import path from 'node:path';

export function startRuntime() {
 return {monotonic:performance.now(),started_at:new Date().toISOString()};
}

export async function persistRuntime(root,envelope,processIdentity,start,receiptBytes) {

 // Publish timing only after the original receipt and process marker are durable.
 const receiptName=envelope.kind?'result.json':'native-receipt.json';
 for(const [filename,maximum] of [[receiptName,1048576],['process-start.json',2048]]) {
  const source=await open(path.join(root,filename),constants.O_RDONLY|constants.O_NOFOLLOW|constants.O_NONBLOCK);
  try {
   const info=await source.stat();
   if(!info.isFile()||info.size<1||info.size>maximum)throw Error('native_runtime_source_invalid');
   if(filename===receiptName&&!Buffer.from(await source.readFile()).equals(Buffer.from(receiptBytes)))throw Error('native_runtime_receipt_changed');
   await source.sync();
  }finally{await source.close();}
 }
 const monotonic_completed_ms=performance.now();
 const elapsed_seconds=(monotonic_completed_ms-start.monotonic)/1000;
 if(!Number.isFinite(elapsed_seconds)||elapsed_seconds<0||await realpath(root)!==root)throw Error('native_runtime_timing_invalid');
 const proof={schema_version:1,envelope,process:processIdentity,started_at:start.started_at,
  completed_at:new Date().toISOString(),monotonic_started_ms:start.monotonic,monotonic_completed_ms,elapsed_seconds,
  receipt_sha256:createHash('sha256').update(receiptBytes).digest('hex'),
  provenance:'native_process_monotonic'};
 const temporary=path.join(root,'.runtime.pending.json'),target=path.join(root,'runtime.json');
 const handle=await open(temporary,'wx',0o600);
 let published=false;
 try {
  await handle.writeFile(JSON.stringify(proof)+'\n');await handle.sync();await handle.close();
  await link(temporary,target);published=true;
  const directory=await open(root,'r');try{await directory.sync();}finally{await directory.close();}
 }catch(error) {
  if(published)await unlink(target).catch(()=>{});
  throw error;
 }finally {
  await handle.close().catch(()=>{});await unlink(temporary).catch(()=>{});
 }
 return proof;
}

export async function preserveReceiptTiming(root,envelope,identity,start,bytes,writer=persistRuntime) {
 try {await writer(root,envelope,identity,start,bytes);return true;}
 catch {try{process.stderr.write('clipping_native_runtime_proof_unavailable\n');}catch{}return false;}
}
