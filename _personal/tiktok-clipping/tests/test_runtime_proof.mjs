import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,readFile,readdir,rm,symlink,realpath} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createHash} from 'node:crypto';
import {startRuntime,persistRuntime} from '../deploy/runtime-proof.mjs';

async function fixture(run) {
 const root=await realpath(await mkdtemp(path.join(os.tmpdir(),'native-runtime-')));
 const envelope={kind:'clip',job_id:'job',attempt_id:'attempt',nonce:'nonce',native_execution:{execution_id:'123',workflow_id:'workflow'}};
 const identity={pid:123,start_identity:'observed ps identity'};
 const receipt=JSON.stringify({envelope,outcome:'failed',usage_observed:false})+'\n';
 try {
  await writeFile(path.join(root,'result.json'),receipt);
  await writeFile(path.join(root,'process-start.json'),JSON.stringify({schema_version:1,...identity,job_id:'job',attempt_id:'attempt',nonce:'nonce'}));
  await run(root,envelope,identity,receipt);
 }finally{await rm(root,{recursive:true,force:true});}
}

test('actual monotonic proof binds exact terminal bytes and publishes once',async()=>fixture(async(root,envelope,identity,receipt)=>{
 const proof=await persistRuntime(root,envelope,identity,startRuntime(),receipt);
 assert.deepEqual(JSON.parse(await readFile(path.join(root,'runtime.json'),'utf8')),proof);
 assert.equal(proof.receipt_sha256,createHash('sha256').update(receipt).digest('hex'));
 assert.equal(proof.elapsed_seconds,(proof.monotonic_completed_ms-proof.monotonic_started_ms)/1000);
 assert.deepEqual(proof.process,identity);assert.deepEqual(proof.envelope,envelope);
 assert.ok(!(await readdir(root)).includes('.runtime.pending.json'));
 await assert.rejects(persistRuntime(root,envelope,identity,startRuntime(),receipt),{code:'EEXIST'});
}));

test('changed receipt refuses timing without replacing original outcome',async()=>fixture(async(root,envelope,identity,receipt)=>{
 await assert.rejects(persistRuntime(root,envelope,identity,startRuntime(),receipt+'changed'),/native_runtime_receipt_changed/);
 assert.equal(await readFile(path.join(root,'result.json'),'utf8'),receipt);
 assert.ok(!(await readdir(root)).includes('runtime.json'));
}));

test('receipt symlink and invalid elapsed refuse timing',async()=>fixture(async(root,envelope,identity,receipt)=>{
 await rm(path.join(root,'result.json'));await writeFile(path.join(root,'elsewhere.json'),receipt);await symlink(path.join(root,'elsewhere.json'),path.join(root,'result.json'));
 await assert.rejects(persistRuntime(root,envelope,identity,startRuntime(),receipt));
 await rm(path.join(root,'result.json'));await writeFile(path.join(root,'result.json'),receipt);
 await assert.rejects(persistRuntime(root,envelope,identity,{monotonic:Infinity,started_at:new Date().toISOString()},receipt),/native_runtime_timing_invalid/);
 assert.ok(!(await readdir(root)).includes('runtime.json'));
}));
