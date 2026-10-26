/** Local standalone adapter; no Notion Worker runtime or hosted invocation. */
import {Client} from '@notionhq/client';
import {Gumroad,plan,deploy,publish,productHash,summary,VERSION} from './core.js';
import {inspectBuild,buildFresh,smokeFresh} from './build.js';
import {createSmokeDraft,updateSmokeDraft} from './smoke-draft.js';
import {buildEpub} from './epub.js';
import {planFormats,formatPlanSummary,updateFormats} from './formats.js';

export async function execute(operation:string,input:any){
 const api=new Gumroad();
 if(operation==='listGumroadProducts')return {version:VERSION,products:await api.list()};
 if(operation==='inspectGumroadProduct'){const p=await api.product(input.productId);return {product:summary(p),productHash:productHash(p)};}
 if(!process.env.NOTION_API_TOKEN)throw Error('Missing Notion API token; configure notion-api-token in the CLI-tools secret manager.');
 // Disable SDK write retries: an ambiguous attachment must be inspected, never repeated.
 const notion=new Client({auth:process.env.NOTION_API_TOKEN,retry:false,timeoutMs:60000});
 switch(operation){
  case 'inspectGumroadBuild':return inspectBuild(input,notion);
  case 'buildGumroadBook':return buildFresh(input,notion);
  case 'buildGumroadEpub':return buildEpub(input,notion);
  case 'smokeTestGumroadUpload':return smokeFresh(input,notion,api);
  case 'createGumroadSmokeDraft':return createSmokeDraft(input,notion,api);
  case 'updateGumroadSmokeDraft':return updateSmokeDraft(input,notion,api);
  case 'planGumroadRelease':{const p=await plan(input,notion,api);return{planHash:p.planHash,pdfSha256:p.artifact.pdfSha256,bytes:p.artifact.bytes.length,sourceDigest:p.artifact.sourceDigest,exportFingerprint:p.artifact.exportFingerprint,bookTitle:p.artifact.book.title,action:p.product?(p.product.published?'liveUpdate':'updateDraft'):'createDraft',product:p.product?summary(p.product):null,retainedFileIds:p.retained.map((f:any)=>f.id),warning:'Direct-Notion build manifest, exact PDF hash and current source revision digest verified. Review exact bytes before product deployment/publication.'};}
  case 'createGumroadDraft':if(input.productId!==null)throw Error('Draft creation requires productId=null.');return deploy({...input,confirmLiveUpdate:false},notion,api);
  case 'updateGumroadBook':if(input.productId===null)throw Error('Update requires an existing product ID.');return deploy({...input,confirmCreateDraft:false},notion,api);
  case 'publishGumroadBook':return publish(input,notion,api);
  case 'planGumroadFormats':return formatPlanSummary(await planFormats(input,notion,api));
  case 'updateGumroadFormats':return updateFormats(input,notion,api);
  default:throw Error('Unknown operation.');
 }
}

async function main(){
 const chunks:Buffer[]=[];let size=0;
 for await(const chunk of process.stdin){size+=chunk.length;if(size>1024*1024)throw Error('Input exceeds 1 MiB.');chunks.push(chunk);}
 const request=JSON.parse(Buffer.concat(chunks).toString());
 const result=await execute(request.operation,request.input);
 process.stdout.write(JSON.stringify(result)+'\n');
}
main().catch(error=>{console.error(error instanceof Error?error.message:'Operation failed.');process.exitCode=1;});
