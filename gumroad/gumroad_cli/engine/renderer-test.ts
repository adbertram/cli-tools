import assert from 'node:assert/strict';
import {writeFileSync} from 'node:fs';
import {draftOnly,structureTitles,idOf,Reader,readBook,verifySnapshot,type Block,type Book} from './src/book.js';
import {render,displayChapterTitle} from './src/render.js';
import {PDFDocument as PortablePDF} from 'pdf-lib';
const rich=(s:string)=>[{type:'text',plain_text:s,text:{content:s},annotations:{}}];
let n=0;const block=(type:string,value:any,children?:Block[]):Block=>({id:`test-${++n}`,type,[type]:value,has_children:!!children?.length,children});
const p=(s:string)=>block('paragraph',{rich_text:rich(s)});const h=(s:string)=>block('heading_2',{rich_text:rich(s)});
assert.equal(idOf('https://app.notion.com/p/3f5aaa654fc74a11bc0fc3865cdfcedd'),'3f5aaa65-4fc7-4a11-bc0f-c3865cdfcedd');
assert.throws(()=>idOf('oops'));
assert.deepEqual(draftOnly([h('Plan'),p('SECRET EDITOR NOTES'),h('Draft'),p('PUBLISHED TEXT'),h('Section'),p('MORE TEXT')]).map(b=>b.type),['paragraph','heading_2','paragraph']);
assert.throws(()=>draftOnly([h('Plan')]));assert.throws(()=>draftOnly([h('Draft'),h('Draft'),p('x')]));assert.throws(()=>draftOnly([h('Draft')]));
assert.deepEqual(structureTitles([h('Structure'),p('intro'),block('numbered_list_item',{rich_text:rich('Chapter One')}),h('Themes'),p('secret')]),['Chapter One']);
const cid='11111111-1111-1111-1111-111111111111',root='22222222-2222-2222-2222-222222222222';let status='Final',title='Chapter One',body=[h('Plan'),p('SECRET EDITOR NOTES'),h('Draft'),p('PUBLISHED TEXT')];
const fake:any={pages:{retrieve:async({page_id}:any)=>({object:'page',id:page_id,last_edited_time:'2026-01-01',properties:{Chapter:{type:'title',title:rich(page_id===root?'Test Book':title)}}})},blocks:{children:{list:async({block_id}:any)=>({results:block_id===root?[h('Structure'),block('numbered_list_item',{rich_text:rich('Chapter One')}),h('Themes'),block('child_database',{title:'Chapters'})]:body,has_more:false})}},databases:{retrieve:async()=>({data_sources:[{id:'ds'}]})},dataSources:{retrieve:async()=>({properties:{Chapter:{type:'title'},Order:{type:'number'},Status:{type:'status'}}}),query:async()=>({results:[{id:cid,last_edited_time:'2026-01-01',properties:{Chapter:{type:'title',title:rich(title)},Order:{number:1},Status:{status:{name:status}}}}],has_more:false})}};
const reader=new Reader(fake);reader.call=async f=>f();
await readBook(reader,root,'publication');status='Rough';await assert.rejects(()=>readBook(reader,root,'publication'),/not Final/);const proof=await readBook(reader,root,'proof');assert.equal(proof.warnings.length,1);status='Final';title='Wrong';await assert.rejects(()=>readBook(reader,root,'proof'),/mismatch/);title='Chapter One';body=[h('Draft'),p('[DETAIL: author]')];await assert.rejects(()=>readBook(reader,root,'publication'),/DETAIL/);body=[h('Draft'),p('Text'),block('video',{external:{url:'https://example.com'}})];await assert.rejects(()=>readBook(reader,root,'proof'),/unsupported/);
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jL1sAAAAASUVORK5CYII=','base64');
const sample:Book={id:root,title:'A Practical Book',edited:'2026-01-01',dataSourceId:'ds',fingerprint:'abc',warnings:[],chapters:[{id:cid,title:'Chapter One: Getting Started',order:1,status:'Final',edited:'2026-01-01',blocks:[p('This is the published draft. Smart punctuation — and café should render correctly.'),h('An actionable section'),block('callout',{rich_text:rich('Check your real package weight before setting shipping rates.')}),block('table',{table_width:3,has_column_header:true},[block('table_row',{cells:[rich('Decision'),rich('Choice'),rich('Reason')]}),block('table_row',{cells:[rich('Shipping'),rich('Start domestic'),rich('Fewer customs and delivery variables. Long cell text wraps without overlap.')]})]),block('bulleted_list_item',{rich_text:rich('A useful list item')}),block('paragraph',{rich_text:[{text:{content:'An official reference'},href:'https://www.notion.com',annotations:{bold:true}}]}),block('image',{type:'external',external:{url:'https://example.com/pixel.png'},caption:rich('Test image caption')})]}]};
const a=await render(sample,'proof','Test Author',async()=>png);const b=await render(sample,'proof','Test Author',async()=>png);assert.equal(a.toString('hex'),b.toString('hex'));writeFileSync(new URL('./test-proof.pdf',import.meta.url),a);
console.log('PASS: draft-only selection, UUIDs, exact structure, status gating, DETAIL gating, unsupported blocks, deterministic PDF bytes, rich text/table/image rendering.');

const insert=await PortablePDF.create();insert.addPage([400,500]).drawText('Printable reference guide',{x:36,y:450,size:18});insert.setCreationDate(new Date('2000-01-01'));insert.setModificationDate(new Date('2000-01-01'));const insertBytes=Buffer.from(await insert.save());sample.chapters[0].blocks.push(block('pdf',{type:'external',external:{url:'https://example.com/guide.pdf'},caption:rich('Printable guide')}));const resolveAsset=async(url:string)=>url.endsWith('.pdf')?insertBytes:png;const withPdf=await render(sample,'proof',null,resolveAsset);assert.deepEqual(withPdf,await render(sample,'proof',null,resolveAsset));const inspected=await PortablePDF.load(new Uint8Array(withPdf));assert.equal(inspected.getPageCount(),(await PortablePDF.load(a)).getPageCount()+2);writeFileSync(new URL('./test-embedded.pdf',import.meta.url),withPdf);console.log('PASS: embedded PDF pages retained, page count and deterministic combined PDF.');

body=[h('Draft'),p('PUBLISHED TEXT'),block('child_page',{title:'Agent prompt: Test production task'})];status='Final';const excluded=await readBook(reader,root,'publication');assert.match(excluded.warnings[0],/excluded production subpage/);assert.equal(excluded.chapters[0].blocks.length,1);console.log('PASS: named production subpage excluded without altering manuscript.');
const {normalizeImage}=await import('./src/media.js');const {readFileSync}=await import('node:fs');const color=readFileSync(new URL('./assets/test-color.heic',import.meta.url));const converted=await normalizeImage(color);assert.equal(converted.subarray(0,2).toString('hex'),'ffd8');assert.deepEqual(converted,await normalizeImage(color));console.log('PASS: portable HEIC conversion, stable JPEG bytes.');
const {Jimp,JimpMime}=await import('jimp');const large=new Jimp({width:2000,height:1600,color:0x2783deff});const largePng=await large.getBuffer(JimpMime.png);const optimized=await normalizeImage(largePng,'ebook200');const decoded=await Jimp.read(optimized);assert.equal(decoded.bitmap.width,1400);assert.equal(decoded.bitmap.height,1120);assert.deepEqual(optimized,await normalizeImage(largePng,'ebook200'));assert.deepEqual(await normalizeImage(largePng,'native'),largePng);assert.deepEqual(await normalizeImage(insertBytes,'ebook200'),insertBytes);console.log('PASS: approved 200-dpi bounds, stable bytes, native pass-through and PDF preservation.');

// Callout regression fixture: short/linked text, near-page-bottom placement,
// long split text and nested lists must retain backgrounds without clipping.
const tip=(label:string,body:string)=>block('callout',{color:'gray_background',rich_text:[{text:{content:label},annotations:{bold:true}},...rich(body)]});
const calloutBook:Book={...sample,title:'Blue Tip regression proof',chapters:[{...sample.chapters[0],title:'Blue Tip layout tests',blocks:[
 tip('Tip: Open small on purpose. ','A tiny store that ships accurately teaches you more than a huge store that immediately creates mistakes.'),
 block('callout',{rich_text:[{text:{content:'Tip: Keep the current help page open. '},annotations:{bold:true}},{text:{content:'Read the official reference',link:{url:'https://www.bricklink.com/help.asp?helpID=2440'}},href:'https://www.bricklink.com/help.asp?helpID=2440',annotations:{underline:true}},...rich(' before you submit.')]},[p('A second paragraph stays inside the same padded panel.'),block('bulleted_list_item',{rich_text:rich('A nested checklist item stays inside the border.')})]),
 ...Array.from({length:10},(_,i)=>p(`Ordinary paragraph ${i+1}: this filler tests the Tip near a page boundary.`)),
 tip('Tip: Boundary test. ','This callout should move to the next page if its padded panel cannot fit in the remaining space. '.repeat(3)),
 tip('Tip: Long callout test. ','Pack a pretend order, weigh the package, check your rates, and keep a clear handling promise. '.repeat(65)),
 p('END OF CALLOUT TEST: ordinary prose resumes outside the blue panel.')
]}]};
const calloutPdf=await render(calloutBook,'proof','Test Author',async()=>png);assert.deepEqual(calloutPdf,await render(calloutBook,'proof','Test Author',async()=>png));writeFileSync(new URL('./test-callouts.pdf',import.meta.url),calloutPdf);
const calloutDoc=await PortablePDF.load(calloutPdf);assert.ok(calloutDoc.getPageCount()>=5);console.log('PASS: deterministic blue callout proof with rich links, child paragraphs/list, page boundary and long multi-page panel.');

assert.equal(displayChapterTitle('Chapter 2: Setting Up the Store'),'Setting Up the Store');
assert.equal(displayChapterTitle('Chapter One: Getting Started'),'Getting Started');
assert.equal(displayChapterTitle('Chapter XI: Working Together'),'Working Together');
assert.equal(displayChapterTitle('Appendix A: Identifying Parts'),'Appendix A: Identifying Parts');
assert.equal(displayChapterTitle('Chapter 2: '),'Chapter 2: ');
assert.equal(displayChapterTitle('A Chapter: Story'),'A Chapter: Story');
const shapes=new Map<string,Buffer>();
for(const [name,w,h] of [['portrait',300,440],['landscape',700,250],['narrow',120,480],['full-width',900,500]] as [string,number,number][]){shapes.set(name,await new Jimp({width:w,height:h,color:0x8db5caff}).getBuffer(JimpMime.png));}
const figure=(name:string,caption:any[])=>block('image',{type:'external',external:{url:name},caption});
const figureBook:Book={...sample,title:'Integrated figure regression proof',chapters:[{...sample.chapters[0],title:'Chapter 1: Figure Tests',blocks:[
 p('BEFORE PORTRAIT'),figure('portrait',rich('Portrait caption: the band matches the image, not the whole page.')),
 p('AFTER PORTRAIT'),figure('landscape',[...rich('Landscape caption with a '),{text:{content:'clickable reference',link:{url:'https://www.notion.com'}},href:'https://www.notion.com',annotations:{underline:true}},...rich(' and ordinary text.')]),
 p('AFTER LANDSCAPE'),figure('narrow',rich('Narrow image caption remains readable and attached.')),
 p('AFTER NARROW'),figure('full-width',rich('Long caption. '.repeat(45))),
 ...Array.from({length:14},(_,i)=>p('Page-boundary filler '+i)),figure('landscape',rich('BOUNDARY FIGURE: move image and caption together.')),
 figure('landscape',[]),p('END OF FIGURE TEST')]}]};
const figures=await render(figureBook,'proof','Test Author',async u=>shapes.get(u)!);assert.deepEqual(figures,await render(figureBook,'proof','Test Author',async u=>shapes.get(u)!));writeFileSync(new URL('./test-figures.pdf',import.meta.url),figures);
const impossible={...figureBook,chapters:[{...figureBook.chapters[0],blocks:[figure('portrait',rich('Unfit caption. '.repeat(3000)))]}]};
await assert.rejects(()=>render(impossible,'proof',null,async u=>shapes.get(u)!),/cannot fit/);
console.log('PASS: title-only display, unchanged appendices, deterministic integrated figures, caption links, portrait/landscape/narrow/full-width/long/boundary cases and unreadable-figure rejection.');

const paginationBook:Book={...sample,title:'Pagination regression',chapters:[{...sample.chapters[0],title:'Layout Checks',blocks:[
 block('paragraph',{rich_text:[...rich('Before '),{text:{content:'linked words',link:{url:'https://example.com'}},href:'https://example.com',annotations:{}},...rich(' after the link, '),{text:{content:'bold words'},annotations:{bold:true}},...rich(' after bold. This sentence stays on natural measured lines.')]}),
 ...Array.from({length:17},(_,i)=>p('Filler paragraph '+i)),h('Keep Opening Text'),figure('landscape',rich('Attached caption')),
 p('OPENING BODY must remain on the heading page, even when a diagram comes first. This paragraph is deliberately long enough to occupy more than one line.'),
 ...Array.from({length:12},(_,i)=>p('Table boundary filler '+i)),
 block('table',{table_width:2,has_column_header:true},[block('table_row',{cells:[rich('COLUMN HEADER'),rich('DETAIL HEADER')]}),...Array.from({length:25},(_,i)=>block('table_row',{cells:[rich('ROW '+i),rich('Data text. '.repeat(12))]}))]),p('END OF PAGINATION TEST')]}]};
const pagination=await render(paginationBook,'proof','Test Author',async u=>shapes.get(u)!);assert.deepEqual(pagination,await render(paginationBook,'proof','Test Author',async u=>shapes.get(u)!));writeFileSync(new URL('./test-pagination.pdf',import.meta.url),pagination);
console.log('PASS: deterministic mixed inline text, heading/figure/opening prose and repeated-header table pagination fixture.');
const toggleBook:Book={...paginationBook,chapters:[{...paginationBook.chapters[0],blocks:[...Array.from({length:21},(_,i)=>p('Toggle boundary filler '+i)),block('toggle',{rich_text:rich('Expanded Toggle Section')},[figure('landscape',rich('Toggle figure caption')),p('TOGGLE OPENING BODY must remain with its expanded section label.')]),h('Following Section'),p('Following body.')] }]};
const togglePdf=await render(toggleBook,'proof',null,async u=>shapes.get(u)!);assert.deepEqual(togglePdf,await render(toggleBook,'proof',null,async u=>shapes.get(u)!));writeFileSync(new URL('./test-toggles.pdf',import.meta.url),togglePdf);console.log('PASS: expanded-toggle section label stays with leading figure and opening body.');
// v1.6.2: a heading followed by several captioned figures that cannot share one
// page with opening prose must start a fresh page, not fail the export.
const galleryBook:Book={...paginationBook,chapters:[{...paginationBook.chapters[0],blocks:[...Array.from({length:8},(_,i)=>p('Gallery filler '+i)),h('Photo Gallery Section'),...['narrow','portrait','narrow','portrait','narrow'].map((s,i)=>figure(s,rich(`Gallery caption ${i+1}: `+'descriptive words '.repeat(12)))),p('GALLERY OPENING BODY follows the figures.'),h('After Gallery'),p('Following body.')]}]};
const galleryPdf=await render(galleryBook,'proof',null,async u=>shapes.get(u)!);assert.deepEqual(galleryPdf,await render(galleryBook,'proof',null,async u=>shapes.get(u)!));writeFileSync(new URL('./test-gallery.pdf',import.meta.url),galleryPdf);console.log('PASS: oversized heading + figure group starts a fresh page instead of failing.');

// v1.7.0 optional explicit front matter: never include root production text.
const {frontMatterOnly,parseFrontMatter}=await import('./src/book.js');
const sub=(s:string)=>block('heading_3',{rich_text:rich(s)});
const fm=[sub('Cover'),block('image',{type:'external',external:{url:'cover'},caption:[]}),sub('Title Page'),p('Front Matter Book Title'),p('Explicit Author'),sub('Trademark and Non-Affiliation Notice'),p('LEGO® is a trademark of the LEGO Group of companies. This independent publication is not sponsored, authorized, or endorsed by the LEGO Group.')];
assert.deepEqual(frontMatterOnly([h('Publication Front Matter'),...fm,h('Rules'),p('SECRET ROOT RULES')]),fm);
assert.equal(frontMatterOnly([h('Rules')]),undefined);
assert.throws(()=>frontMatterOnly([h('Publication Front Matter'),h('Publication Front Matter')]),/at most one/);
assert.throws(()=>parseFrontMatter([sub('Surprise'),p('x')],'proof',[]),/Unsupported/);
assert.throws(()=>parseFrontMatter([sub('Cover'),p('not an image')],'proof',[]),/exactly one image/);
assert.throws(()=>parseFrontMatter([sub('Title Page')],'proof',[]),/empty/);
assert.throws(()=>parseFrontMatter([sub('Copyright Page'),p('[DETAIL: notice]')],'publication',[]),/DETAIL/);
assert.throws(()=>parseFrontMatter([sub('Cover'),fm[1],sub('Cover'),fm[1]],'proof',[]),/Duplicate/);
const frontMatter=parseFrontMatter(fm,'proof',[]);const fmImage=await new Jimp({width:848,height:1338,color:0x102235ff}).getBuffer(JimpMime.png);
const fmBook:Book={...sample,title:'Front Matter Book Title',frontMatter};
const fmPdf=await render(fmBook,'proof','Fallback Author',async u=>u==='cover'?fmImage:resolveAsset(u));
assert.deepEqual(fmPdf,await render(fmBook,'proof','Fallback Author',async u=>u==='cover'?fmImage:resolveAsset(u)));
assert.equal((await PortablePDF.load(fmPdf)).getPageCount(),(await PortablePDF.load(await render({...fmBook,frontMatter:undefined},'proof','Fallback Author',resolveAsset))).getPageCount()+2);
writeFileSync(new URL('./test-frontmatter.pdf',import.meta.url),fmPdf);
const oldRetrieve=fake.blocks.retrieve;fake.blocks.retrieve=async()=>({last_edited_time:'changed'});
await assert.rejects(async()=>verifySnapshot(reader,{...await readBook(reader,root,'proof'),frontMatter:{...frontMatter,revisions:[{id:'fm',edited:'old'}]}}),/Front matter changed/);fake.blocks.retrieve=oldRetrieve;
console.log('PASS: front matter selection boundaries, strict sections, cover/title/notice, publication DETAIL gating, deterministic bytes, legacy fallback and changed-front-matter rejection.');

// v1.8.0 explicit, stable reviewer-download destination; never expose sources.
const {reviewerDownloadOnly,validateReviewerDownload,refreshReviewerDownload}=await import('./src/distribution.js');
const reviewerId='33333333-3333-3333-3333-333333333333',fileId='44444444-4444-4444-4444-444444444444';
const distribution=[h('Reviewer Download'),p('Page ID: '+reviewerId),p('File Block ID: '+fileId)];
const target=reviewerDownloadOnly([...distribution,h('Rules'),p('PRIVATE RULES')])!;
assert.deepEqual(target,{pageId:reviewerId,fileBlockId:fileId});assert.equal(reviewerDownloadOnly([h('Rules')]),undefined);
assert.throws(()=>reviewerDownloadOnly([...distribution,...distribution]),/at most one/);
assert.throws(()=>reviewerDownloadOnly([h('Reviewer Download'),p('Page ID: bad')]),/requires/);
assert.throws(()=>reviewerDownloadOnly([h('Reviewer Download'),p('Page ID: '+reviewerId)]),/requires/);
assert.throws(()=>reviewerDownloadOnly([...distribution,p('Page ID: '+reviewerId)]),/Duplicate/);
let updates:any[]=[],validParent=true,updateFails=false,validPage=true;
const distReader=new Reader({pages:{retrieve:async()=>({object:'page',parent:{type:validPage?'workspace':'page_id'}})},blocks:{retrieve:async()=>({type:'file',parent:{type:'page_id',page_id:validParent?reviewerId:root}}),update:async(x:any)=>{if(updateFails)throw Error('API unavailable');updates.push(x);return x;}}} as any);distReader.call=async f=>f();
const distributed:Book={...sample,reviewerDownload:target};
await validateReviewerDownload(distReader,distributed);await refreshReviewerDownload(distReader,distributed,'uploaded-id','book.pdf','proof','ebook200');
assert.equal(updates.length,1);assert.equal(updates[0].block_id,fileId);assert.equal(updates[0].file.file_upload.id,'uploaded-id');assert.match(updates[0].file.caption[0].text.content,/advance reading proof/);
await refreshReviewerDownload(distReader,distributed,'new-upload','new.pdf','proof','ebook200');assert.equal(updates[1].block_id,fileId); // replace the same block, never append
await refreshReviewerDownload(distReader,sample,'ignored','unused.pdf','proof','ebook200');assert.equal(updates.length,2);
await assert.rejects(()=>validateReviewerDownload(distReader,{...distributed,reviewerDownload:{...target,pageId:root}}),/separate/);
validParent=false;await assert.rejects(()=>refreshReviewerDownload(distReader,distributed,'bad','bad.pdf','proof','native'),/directly/);assert.equal(updates.length,2);validParent=true;
validPage=false;await assert.rejects(()=>validateReviewerDownload(distReader,distributed),/top-level/);validPage=true;
updateFails=true;await assert.rejects(()=>refreshReviewerDownload(distReader,distributed,'bad','bad.pdf','proof','native'),/unavailable/);assert.equal(updates.length,2);
console.log('PASS: explicit reviewer target, malformed/duplicate rejection, isolated top-level page, direct file ownership, stable replacement, no-config no-op and failure retains prior file.');
