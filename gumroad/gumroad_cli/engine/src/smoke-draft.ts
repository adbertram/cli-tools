import {Reader,readBook,text,idOf} from './book.js';
import {Gumroad,digest,sourceDigest,fetchBytes,summary,receipt,type Bytes} from './core.js';
import {verifyLiveSource} from './build.js';
export type SmokeDraftInput={bookPageUrl:string;pdfFileBlockId:string;overrideFinalStatusForSmokeTest:boolean;confirmCreateUnpublishedDraft:boolean};
const html=(s:string)=>s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
export async function captureSmokeProof(input:SmokeDraftInput,notion:any,load:Bytes=fetchBytes){
 if(input.overrideFinalStatusForSmokeTest!==true||input.confirmCreateUnpublishedDraft!==true)throw Error('Explicit smoke-test status override and unpublished-product creation approval are both required.');
 const reader=new Reader(notion),book=await readBook(reader,input.bookPageUrl,'proof');
 const block:any=await reader.call(()=>notion.blocks.retrieve({block_id:idOf(input.pdfFileBlockId)}));
 if(block.archived||block.in_trash||block.type!=='file'||block.parent?.type!=='page_id'||idOf(block.parent.page_id)!==book.id||block.file?.type!=='file'||!block.file.file?.url)throw Error('Smoke PDF must be a native build output attached directly to this book root.');
 const caption=text(block.file.caption),match=caption.match(/^BookWriter proof • (native|ebook200) • (\d+) units • source ([a-f0-9]{64})$/);
 if(!match||Number(match[2])!==book.chapters.length)throw Error('Smoke deployment requires a complete, visibly labelled proof build.');
 const manifests=(await reader.children(book.id)).filter(b=>b.type==='code').flatMap(b=>{try{return[JSON.parse(text(b.code.rich_text))];}catch{return[];}}).filter(m=>m.kind==='bookwriter-build-manifest'&&m.fileBlockId===block.id);
 if(manifests.length!==1)throw Error('Exactly one direct-Notion build manifest is required.');const manifest=manifests[0];const currentSource=sourceDigest(book);
 if(manifest.mode!=='proof'||manifest.bookId!==book.id||manifest.sourceDigest!==currentSource||manifest.chapterCount!==book.chapters.length||manifest.exportFingerprint!==match[3])throw Error('Build manifest does not match current Notion chapters; build a fresh proof before deployment.');
 const bytes=await load(block.file.file.url);if(bytes.subarray(0,5).toString()!=='%PDF-'||bytes.length>100*1024*1024||digest(bytes)!==manifest.pdfSha256)throw Error('Proof bytes do not match the exact build manifest or PDF budget.');
 return{reader,book,block,manifest,bytes,pdfSha256:digest(bytes),sourceDigest:currentSource};
}
export async function createSmokeDraft(input:SmokeDraftInput,notion:any,api:Gumroad,load:Bytes=fetchBytes){
 const a=await captureSmokeProof(input,notion,load);
 const name=a.book.title.slice(0,230)+' — Reading Proof';
 const author=typeof a.manifest.author==='string'?a.manifest.author:null;
 const marker='BookWriter unpublished smoke test. Book ID: '+a.book.id;
 const description=`<p>${html(marker)}</p><p>Reading proof of ${html(a.book.title)}${author?' by '+html(author):''}. Built directly from the current Notion chapter Draft pages. Unfinished editorial material may be present. Not a publication-ready edition.</p><p>Smoke-test placeholder price: $0 USD. This product must remain unpublished.</p>`;
 const verifyDelivered=async(p:any)=>{if(p.published!==false)throw Error('Smoke-test product is not confirmed unpublished. No publication requested; inspect the product immediately.');if(p.name!==name||p.price!==0||String(p.currency).toLowerCase()!=='usd')throw Error('Gumroad metadata differs from the unpublished smoke-test defaults. Inspect this product; do not retry creation.');if(!Array.isArray(p.files)||p.files.length!==1||String(p.files[0].filetype).toLowerCase()!=='pdf'||!p.files[0].url)throw Error('Exactly one delivered PDF must be confirmed on the smoke-test draft.');if(digest(await load(p.files[0].url))!==a.pdfSha256)throw Error('Gumroad-delivered PDF hash differs from the current Notion build.');return p;};
 const existing=(await api.list()).filter((p:any)=>p.name===name);
 if(existing.length){if(existing.length!==1)throw Error('Multiple matching reading-proof products; inspect exact targets instead of creating another.');const p=await api.product(existing[0].id);if(typeof p.description!=='string'||!p.description.includes(marker))throw Error('A matching-name product is not identified as this book smoke test. No upload or write attempted.');await verifyDelivered(p);await verifyLiveSource(a.reader,a.book,'proof');return{operation:'createSmokeDraft',changed:false,smokeTest:true,statusOverrideUsed:true,bookTitle:a.book.title,chapterCount:a.book.chapters.length,warnings:a.book.warnings,product:summary(p),pdfSha256:a.pdfSha256,notionPdfFileBlockId:a.block.id,deliveryVerified:true,published:false,audienceEmailApiCalled:false,receiptBlockId:null,receiptWarning:null};}
 await verifyLiveSource(a.reader,a.book,'proof');
 console.error('Uploading fresh proof for an unpublished Gumroad reading-proof product');
 const url=await api.upload(a.bytes,'BookWriter-reading-proof-'+a.pdfSha256.slice(0,24)+'.pdf');
 await verifyLiveSource(a.reader,a.book,'proof');const now:any=await a.reader.call(()=>notion.blocks.retrieve({block_id:a.block.id}));if(now.archived||now.in_trash||now.last_edited_time!==a.block.last_edited_time||text(now.file?.caption)!==text(a.block.file.caption))throw Error('Built PDF changed during upload. Staged file left unattached; no product created.');
 const created=await api.call('POST','/products',{native_type:'ebook',name,description,price:0,price_currency_type:'usd',draft:true,published:false,files:[{url}]});
 const productId=created.product?.id;if(typeof productId!=='string')throw Error('Draft creation response lacks an ID; completion unconfirmed. Inspect account before any retry.');
 console.error('Unpublished draft creation response received; verifying delivered PDF');
 const p=await verifyDelivered(await api.product(productId));let receiptBlockId:string|null=null,receiptWarning:string|null=null;
 try{receiptBlockId=await receipt(notion,a.book.id,{operation:'createSmokeDraft',smokeTest:true,statusOverrideUsed:true,productId:p.id,pdfFileId:p.files[0].id,notionPdfFileBlockId:a.block.id,pdfSha256:a.pdfSha256,sourceDigest:a.sourceDigest,published:false,deliveryVerified:true,price:0,currency:'usd',at:new Date().toISOString()});}catch{receiptWarning='Unpublished product and delivered PDF verified, but Notion receipt failed. Do not repeat creation for logging.';}
 return{operation:'createSmokeDraft',changed:true,smokeTest:true,statusOverrideUsed:true,bookTitle:a.book.title,chapterCount:a.book.chapters.length,product:summary(p),pdfSha256:a.pdfSha256,notionPdfFileBlockId:a.block.id,deliveryVerified:true,published:false,audienceEmailApiCalled:false,receiptBlockId,receiptWarning,warnings:a.book.warnings};
}

export type SmokeUpdateInput={bookPageUrl:string;pdfFileBlockId:string;productId:string;replaceFileId:string|null;overrideFinalStatusForSmokeTest:boolean;confirmUpdateUnpublishedDraft:boolean};
export async function updateSmokeDraft(input:SmokeUpdateInput,notion:any,api:Gumroad,load:Bytes=fetchBytes){
 if(input.overrideFinalStatusForSmokeTest!==true||input.confirmUpdateUnpublishedDraft!==true)throw Error('Explicit smoke-test override and update approval are both required.');
 const {identifier,productHash,preservedFiles}=await import('./core.js');identifier(input.productId);
 const a=await captureSmokeProof({...input,confirmCreateUnpublishedDraft:true},notion,load);
 const target=await api.product(input.productId);if(target.published!==false)throw Error('Smoke-test updates require an unpublished product; live products are forbidden.');
 const before=productHash(target),retained=preservedFiles(target,input.replaceFileId);
 const metadata=(p:any)=>{const {files,...other}=p;return productHash({...other,files:[]});};
 const verify=async(p:any)=>{if(p.published!==false||metadata(p)!==metadata(target))throw Error('Product metadata or unpublished state changed; inspect the exact product, never retry automatically.');if(p.files.length!==retained.length+1||retained.some((f:any)=>!p.files.some((g:any)=>g.id===f.id)))throw Error('Attachment preservation verification failed.');const added=p.files.filter((f:any)=>!retained.some((g:any)=>g.id===f.id));if(added.length!==1||String(added[0].filetype).toLowerCase()!=='pdf'||!added[0].url||digest(await load(added[0].url))!==a.pdfSha256)throw Error('Gumroad-delivered proof PDF does not match the build.');return added[0];};
 if(input.replaceFileId){const old=target.files.find((f:any)=>f.id===input.replaceFileId);if(old?.url&&digest(await load(old.url))===a.pdfSha256){await verifyLiveSource(a.reader,a.book,'proof');const now=await api.product(input.productId);if(productHash(now)!==before)throw Error('Product changed during no-op verification.');await verify(now);return{operation:'updateSmokeDraft',changed:false,smokeTest:true,statusOverrideUsed:true,bookTitle:a.book.title,chapterCount:a.book.chapters.length,product:summary(now),pdfSha256:a.pdfSha256,notionPdfFileBlockId:a.block.id,deliveryVerified:true,published:false,audienceEmailApiCalled:false,receiptBlockId:null,receiptWarning:null,warnings:a.book.warnings};}}
 await verifyLiveSource(a.reader,a.book,'proof');console.error('Uploading current proof to the explicitly selected unpublished product; preserving metadata');
 const url=await api.upload(a.bytes,'BookWriter-reading-proof-'+a.pdfSha256.slice(0,24)+'.pdf');
 await verifyLiveSource(a.reader,a.book,'proof');const block:any=await a.reader.call(()=>notion.blocks.retrieve({block_id:a.block.id}));if(block.archived||block.in_trash||block.last_edited_time!==a.block.last_edited_time||text(block.file?.caption)!==text(a.block.file.caption))throw Error('Build artifact changed during upload; no product write attempted.');
 if(productHash(await api.product(input.productId))!==before)throw Error('Product changed during upload; no update attempted.');
 await api.call('PUT','/products/'+identifier(input.productId),{files:[...retained,{url}]});
 const actual=await api.product(input.productId),added=await verify(actual);let receiptBlockId:string|null=null,receiptWarning:string|null=null;
 try{receiptBlockId=await receipt(notion,a.book.id,{operation:'updateSmokeDraft',smokeTest:true,statusOverrideUsed:true,productId:actual.id,pdfFileId:added.id,notionPdfFileBlockId:a.block.id,pdfSha256:a.pdfSha256,sourceDigest:a.sourceDigest,published:false,deliveryVerified:true,metadataPreserved:true,at:new Date().toISOString()});}catch{receiptWarning='Gumroad PDF and unchanged unpublished metadata verified; Notion receipt failed. Do not repeat external update for logging.';}
 return{operation:'updateSmokeDraft',changed:true,smokeTest:true,statusOverrideUsed:true,bookTitle:a.book.title,chapterCount:a.book.chapters.length,product:summary(actual),pdfSha256:a.pdfSha256,notionPdfFileBlockId:a.block.id,deliveryVerified:true,published:false,audienceEmailApiCalled:false,receiptBlockId,receiptWarning,warnings:a.book.warnings};
}
