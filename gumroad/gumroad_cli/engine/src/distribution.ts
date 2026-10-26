import {Reader,text,type Block,type Book} from './book.js';
export type ReviewerDownload={pageId:string;fileBlockId:string};
const uuid='[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
export function reviewerDownloadOnly(blocks:Block[]):ReviewerDownload|undefined {
 const hits=blocks.map((b,i)=>b.type==='heading_2'&&text(b.heading_2.rich_text).trim()==='Reviewer Download'?i:-1).filter(i=>i>=0);
 if(hits.length>1)throw Error('Expected at most one Reviewer Download section.');if(!hits.length)return;
 const fields=new Map<string,string>();
 for(const b of blocks.slice(hits[0]+1)){if(b.type==='heading_1'||b.type==='heading_2')break;const s=text(b[b.type]?.rich_text).trim();if(b.type==='paragraph'&&!s)continue;
  const m=b.type==='paragraph'&&!b.has_children?s.match(new RegExp(`^(Page ID|File Block ID): (${uuid})$`,'i')):null;
  if(!m)throw Error('Reviewer Download requires only Page ID and File Block ID paragraphs containing UUIDs.');const key=m[1].toLowerCase();if(fields.has(key))throw Error('Duplicate Reviewer Download field.');fields.set(key,m[2].toLowerCase());
 }
 if(fields.size!==2)throw Error('Reviewer Download requires Page ID and File Block ID.');return{pageId:fields.get('page id')!,fileBlockId:fields.get('file block id')!};
}
export async function validateReviewerDownload(reader:Reader,book:Book){
 const target=book.reviewerDownload;if(!target)return;
 if([book.id,...book.chapters.map(c=>c.id)].includes(target.pageId))throw Error('Reviewer page must be separate from the manuscript.');
 const page:any=await reader.call(()=>reader.notion.pages.retrieve({page_id:target.pageId}));
 // Only an explicitly separate top-level page may be a public distribution target.
 if(page.object!=='page'||page.archived||page.in_trash||!['workspace','user_id'].includes(page.parent?.type))throw Error('Reviewer target must be an accessible, unarchived top-level page.');
 const block:any=await reader.call(()=>reader.notion.blocks.retrieve({block_id:target.fileBlockId}));
 if(block.archived||block.in_trash||block.type!=='file'||block.parent?.type!=='page_id'||block.parent.page_id!==target.pageId)throw Error('Reviewer File Block ID must identify a live file block directly on the configured reviewer page.');
}
export async function refreshReviewerDownload(reader:Reader,book:Book,uploadId:string,filename:string,mode:string,imageMode:string){
 const target=book.reviewerDownload;if(!target)return;
 await validateReviewerDownload(reader,book);
 const caption=`Full book • ${mode==='proof'?'advance reading proof':'publication'} • ${book.chapters.length} units • updated ${new Date().toISOString()} • ${imageMode} • source ${book.fingerprint}`;
 await reader.call(()=>reader.notion.blocks.update({block_id:target.fileBlockId,file:{file_upload:{id:uploadId},name:filename,caption:[{type:'text',text:{content:caption}}]}}));
 console.error('Reviewer download replaced successfully');return{pageUrl:`https://www.notion.so/${target.pageId.replaceAll('-','')}`,fileBlockId:target.fileBlockId};
}
