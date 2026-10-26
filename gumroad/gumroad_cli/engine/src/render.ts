import PDFDocument from 'pdfkit';
import {PDFDocument as PortablePDF} from 'pdf-lib';
import {Regular,Bold} from './fonts.js';
import {normalizeImage} from './media.js';
import type {Book,Block} from './book.js';
import {text} from './book.js';
const M=54,W=504,BOTTOM=720;
// Presentation only: source titles remain authoritative for structure matching.
export function displayChapterTitle(title:string):string {
 const cleaned=title.replace(/^Chapter\s+(?:\d+|[IVXLCDM]+|(?:One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Eleven|Twelve|Thirteen|Fourteen|Fifteen|Sixteen|Seventeen|Eighteen|Nineteen|Twenty)(?:[- ](?:One|Two|Three|Four|Five|Six|Seven|Eight|Nine))?)\s*:\s*/i,'');
 return cleaned.trim()?cleaned:title;
}
export async function render(book:Book,mode:string,author:string|null,fetchImage:(url:string)=>Promise<Buffer>):Promise<Buffer>{
 const doc=new PDFDocument({size:'LETTER',margins:{top:M,bottom:54,left:M,right:M},bufferPages:true,info:{Title:book.title,Author:author??'',Creator:'BookWriter PDF Export v1.7.0',CreationDate:new Date('2000-01-01T00:00:00Z'),ModDate:new Date('2000-01-01T00:00:00Z')}});
 doc.registerFont('Body',Regular);doc.registerFont('Bold',Bold);
 const frames:{page:number;x:number;y:number;width:number;height:number}[]=[];
 let left=M,width=W;
 let active:{x:number;width:number;top:number}|undefined;
 const pageIndex=()=>doc.bufferedPageRange().count-1;
 doc.on('pageAdded',()=>{if(active){frames.push({page:pageIndex()-1,x:active.x,y:active.top,width:active.width,height:BOTTOM-active.top});active.top=M;doc.page.margins.top=M+16;doc.page.margins.bottom=84;doc.y=M+16;}});
 const imports:{target:number;source:PortablePDF;page:number}[]=[];
 const parts:Buffer[]=[];const result=new Promise<Buffer>((resolve,reject)=>{doc.on('data',c=>parts.push(c));doc.on('end',()=>resolve(Buffer.concat(parts)));doc.on('error',reject);});
 function base(){doc.font('Body').fontSize(11).fillColor('#2C2C2B');}
 function room(h:number){if(doc.y+h>(active?BOTTOM-16:BOTTOM)){doc.addPage();}}
 function plain(s:string,size=11,bold=false,indent=0){doc.font(bold?'Bold':'Body').fontSize(size);room(Math.min(640,doc.heightOfString(s,{width:width-indent,lineGap:4})+8));doc.text(s,left+indent,doc.y,{width:width-indent,lineGap:4});doc.moveDown(.55);base();}
 function richLines(r:any[],prefix:string,indent:number){
  type Run={s:string;bold:boolean;url?:string;chapter:number;underline:boolean;strike:boolean};
  const max=width-indent;const lines:Run[][]=[];let line:Run[]=[],used=0;
  const flush=()=>{lines.push(line);line=[];used=0;};
  function add(run:Run){
   if(run.s==='\n'){flush();return;}
   doc.font(run.bold?'Bold':'Body').fontSize(11);let value=run.s;let w=doc.widthOfString(value);
   if(used+w>max&&line.length){flush();if(/^\s+$/.test(value))return;}
   if(w>max){for(const ch of value)add({...run,s:ch});return;}
   // Adjacent pieces of identical styling are combined before drawing.
   const last=line[line.length-1];if(last&&last.bold===run.bold&&last.url===run.url&&last.chapter===run.chapter&&last.underline===run.underline&&last.strike===run.strike)last.s+=value;else line.push({...run,s:value});used+=w;
  }
  if(prefix)add({s:prefix,bold:false,chapter:-1,underline:false,strike:false});
  for(const x of r){const url=x.href??x.text?.link?.url;const ref=x.mention?.page?.id??url?.match(/[0-9a-f]{8}-[0-9a-f-]{27}|[0-9a-f]{32}/i)?.[0];const chapter=ref?book.chapters.findIndex(c=>c.id.replaceAll('-','').toLowerCase()===ref.replaceAll('-','').toLowerCase()):-1;
   for(const word of text([x]).split(/(\n|[^\S\n]+|[^\s]+)/u).filter(Boolean))add({s:word,bold:!!x.annotations?.bold,url,chapter,underline:!!x.annotations?.underline,strike:!!x.annotations?.strikethrough});
  }
  if(line.length)flush();
  return lines;
 }
 function rich(r:any[],prefix='',indent=0){
  if(!r.length&&!prefix)return;
  const lines=richLines(r,prefix,indent);
  // Explicit shared line geometry: links/bold never restart PDFKit's wrapper.
  // Start paragraphs with at least two lines; retain two final lines together.
  room(Math.min(2,lines.length)*19);
  for(let i=0;i<lines.length;i++){
   room(Math.min(2,lines.length-i)*19);const y=doc.y;let x=left+indent;
   for(const run of lines[i]){doc.font(run.bold?'Bold':'Body').fontSize(11).fillColor(run.url||(active&&run.bold)?'#2468A0':'#2C2C2B');const w=doc.widthOfString(run.s);doc.text(run.s,x,y,{lineBreak:false,link:run.chapter<0?run.url:undefined,goTo:run.chapter>=0?`chapter-${run.chapter}`:undefined,underline:run.underline,strike:run.strike});x+=w;}
   doc.y=y+19;
  }
  doc.y+=8;doc.x=left;base();
 }
 type CaptionRun={s:string;bold:boolean;url?:string;chapter:number;underline:boolean;strike:boolean};
 function captionLines(caption:any[],max:number):CaptionRun[][] {
  const lines:CaptionRun[][]=[];let row:CaptionRun[]=[],used=0;
  const flush=()=>{lines.push(row);row=[];used=0;};
  function add(run:CaptionRun){
   if(run.s==='\n'){flush();return;}
   doc.font(run.bold?'Bold':'Body').fontSize(9);const w=doc.widthOfString(run.s);
   if(w>max){if([...run.s].length===1)throw Error('Caption figure is too narrow for readable 9-point text.');for(const ch of run.s)add({...run,s:ch});return;}
   if(used+w>max&&row.length){flush();if(/^\s+$/.test(run.s))return;}
   row.push(run);used+=w;
  }
  for(const r of caption){const url=r.href??r.text?.link?.url;const ref=r.mention?.page?.id??url?.match(/[0-9a-f]{8}-[0-9a-f-]{27}|[0-9a-f]{32}/i)?.[0];const chapter=ref?book.chapters.findIndex(c=>c.id.replaceAll('-','').toLowerCase()===ref.replaceAll('-','').toLowerCase()):-1;
   for(const word of text([r]).split(/(\n|[^\S\n]+|[^\s]+)/u).filter(Boolean))add({s:word,bold:!!r.annotations?.bold,url,chapter,underline:!!r.annotations?.underline,strike:!!r.annotations?.strikethrough});
  }
  if(row.length)flush();return lines;
 }
 const imageData=new Map<string,{bytes:Buffer;img:any}>();
 async function loadImage(b:Block){
  if(imageData.has(b.id))return imageData.get(b.id)!;
  const info=b.image,bytes=await normalizeImage(await fetchImage(info[info.type].url));let img;
  try{img=(doc as any).openImage(bytes);}catch{throw Error(`Image ${b.id} is not a readable PNG, JPEG or HEIC; export stopped.`);}
  const result={bytes,img};imageData.set(b.id,result);return result;
 }
 const figureLimits=new Map<string,number>();
 async function figureLayout(b:Block){
  const info=b.image,{bytes,img}=await loadImage(b);
  const caption=info.caption??[],hasCaption=!!text(caption).trim();
  let scale=Math.min(width/img.width,(figureLimits.get(b.id)??480)/img.height,hasCaption?Infinity:1.6),w=img.width*scale,h=img.height*scale;
  const capacity=active?BOTTOM-M-32:BOTTOM-M;
  let lines:CaptionRun[][]=[],band=0;
  if(hasCaption){
   // Find the largest feasible proportional image size. Caption wrapping changes
   // with figure width, so evaluate both dimensions together, never crop text.
   let found=false;
   for(let step=0;step<1000;step++){
    const trial=scale*(1-step/1000),tw=img.width*trial;if(tw<40)break;
    const tl=captionLines(caption,tw-16),tb=tl.length*13+16;
    if(img.height*trial+tb<=capacity){scale=trial;w=tw;h=img.height*trial;lines=tl;band=tb;found=true;break;}
   }
   if(!found)throw Error(`Image ${b.id}: image and caption cannot fit on one page at readable 9-point caption size. Shorten the source caption or change the image aspect ratio.`);
  }
  return {bytes,w,h,lines,band,hasCaption};
 }
 async function image(b:Block){
  const {bytes,w,h,lines,band,hasCaption}=await figureLayout(b);
  room(h+band);const y=doc.y,x=left+(width-w)/2;
  const {img}=await loadImage(b);
  // PNG alpha-mask references are allocated asynchronously by PDFKit. Finish
  // each embed before allocating subsequent objects, so reference IDs are stable.
  if(!img.obj){
   if(typeof img.finalize==='function'){
    await new Promise<void>((resolve,reject)=>{const finalize=img.finalize;img.finalize=function(){try{const value=finalize.call(this);resolve();return value;}catch(e){reject(e);}};try{img.embed(doc);}catch(e){reject(e);}});
   }else img.embed(doc);
  }
  doc.image(img,x,y,{width:w,height:h});
  if(hasCaption){
   doc.save().rect(x,y+h,w,band).fill('#F0EFED').rect(x,y,w,h+band).lineWidth(.6).stroke('#E6E5E3').restore();
   let cy=y+h+8;
   for(const row of lines){let cx=x+8;for(const run of row){doc.font(run.bold?'Bold':'Body').fontSize(9).fillColor('#565550');const rw=doc.widthOfString(run.s);doc.text(run.s,cx,cy,{lineBreak:false,link:run.chapter<0?run.url:undefined,goTo:run.chapter>=0?`chapter-${run.chapter}`:undefined,underline:run.underline||!!run.url,strike:run.strike});cx+=rw;}cy+=13;}
  }
  doc.y=y+h+band+14;doc.x=left;base();
 }
 async function importedPdf(b:Block){const v=b.pdf;const data=await fetchImage(v[v.type].url);let source:PortablePDF;try{source=await PortablePDF.load(new Uint8Array(data),{updateMetadata:false});}catch{throw Error(`PDF attachment ${b.id} cannot be read (possibly encrypted or malformed).`);}const count=source.getPageCount();if(!count||count>100)throw Error('An embedded PDF must contain 1–100 pages.');for(let i=0;i<count;i++){if(source.getPage(i).getRotation().angle!==0)throw Error('Rotated embedded PDF pages are not supported; normalize the source PDF first.');doc.addPage();imports.push({target:doc.bufferedPageRange().count-1,source,page:i});}doc.addPage();if(v.caption?.length)plain(text(v.caption),9);}
 function tableLayout(b:Block){
  const rows=b.children??[],n=b.table.table_width;
  if(!rows.length)throw Error('Empty or unreadable table.');if(!n||n>8)throw Error('PDF tables support 1–8 columns.');
  const cw=width/n;
  const sizes=rows.map((row,i)=>{const cells=row.table_row.cells as any[][];if(cells.length!==n)throw Error('Malformed table row.');doc.font(i===0&&b.table.has_column_header?'Bold':'Body').fontSize(9);const h=Math.max(...cells.map(c=>doc.heightOfString(text(c),{width:cw-16,lineGap:2})))+16;if(h>640)throw Error('A table row is too tall for one PDF page; split the source row.');return h;});base();return {rows,n,cw,sizes,header:!!b.table.has_column_header};
 }
 function table(b:Block){
  const {rows,n,cw,sizes,header}=tableLayout(b),capacity=active?BOTTOM-M-32:BOTTOM-M;
  const pair=sizes[0]+(header&&rows.length>1?sizes[1]:0);
  if(pair+4>capacity)throw Error('Table header and first data row cannot fit on one page; split the source row.');
  const total=sizes.reduce((a,b)=>a+b,0);room(total+4<=capacity?total+4:pair+4);
  function draw(i:number){const cells=rows[i].table_row.cells,h=sizes[i],y=doc.y;doc.font(i===0&&header?'Bold':'Body').fontSize(9);for(let j=0;j<n;j++){doc.rect(left+j*cw,y,cw,h).fillAndStroke(i===0&&header?'#F0EFED':'#FFFFFF','#E6E5E3');doc.fillColor('#2C2C2B').text(text(cells[j]),left+j*cw+8,y+8,{width:cw-16,lineGap:2});}doc.y=y+h;}
  for(let i=0;i<rows.length;i++){
   if(i>0&&doc.y+sizes[i]+4>(active?BOTTOM-16:BOTTOM)){
    if(header&&sizes[0]+sizes[i]+4>capacity)throw Error('Repeated table header and data row cannot fit on one page; split the source row.');
    doc.addPage();if(header)draw(0);
   }
   draw(i);
  }
  doc.y+=12;doc.x=left;base();
 }
 function flatten(bs:Block[]):Block[]{return bs.flatMap(b=>['column_list','column','synced_block'].includes(b.type)?flatten(b.children??[]):[b]);}
 function headingSize(b:Block){return b.type==='heading_4'?12:b.type==='heading_3'?14:18;}
 async function keepSection(title:string,size:number,following:Block[],indent:number){
  base();const before=doc.currentLineHeight(true)*.6;doc.font('Bold').fontSize(size);
  let fixed=before+doc.heightOfString(title,{width:width-indent,lineGap:4})+doc.currentLineHeight(true)*.55;const head=fixed;
  const images:Block[]=[];let found=false;
  for(const b of following){
   if(/^heading_[1234]$/.test(b.type)){doc.font('Bold').fontSize(headingSize(b));fixed+=10+doc.heightOfString(text(b[b.type].rich_text),{width:width-indent,lineGap:4})+doc.currentLineHeight(true)*.55;continue;}
   if(b.type==='image'){images.push(b);continue;}
   if(b.type==='divider'){fixed+=20;continue;}
   if(b.type==='table'){const t=tableLayout(b),total=t.sizes.reduce((a,b)=>a+b,0);fixed+=(total+4<=(active?BOTTOM-M-32:BOTTOM-M)?total:t.sizes[0]+(t.header&&t.sizes.length>1?t.sizes[1]:0))+4;found=true;break;}
   const r=b[b.type]?.rich_text;
   if(r&&text(r).trim()){const inset=indent+(b.type.endsWith('list_item')?12:0);fixed+=Math.min(2,richLines(r,'',inset).length)*19+(b.type==='callout'?32:0);found=true;break;}
   if(b.type==='pdf')break;
  }
  base();if(!found){room(Math.min(100,fixed));return;}
  const capacity=active?BOTTOM-M-32:BOTTOM-M;
  let required=fixed;
  // Keep heading + intervening figures + opening prose together. Only shrink
  // displayed figures if the group is otherwise taller than a fresh page.
  // Shrink leading figures to at most half their normal display limit. Beyond
  // that, a heading plus several figures cannot share a page with its opening
  // prose; start the section on a fresh page instead of failing the export.
  let fits=false;
  for(let step=0;step<=50;step++){
   required=fixed;let readable=true;
   for(const image of images){figureLimits.set(image.id,480*(1-step/100));try{const f=await figureLayout(image);required+=f.h+f.band+14;}catch{readable=false;break;}}
   if(readable&&required<=capacity){fits=true;break;}
   if(!readable||!images.length)break;
  }
  base();
  if(fits){room(required);return;}
  for(const image of images)figureLimits.delete(image.id);
  if(doc.y>(active?active.top+40:M+40))doc.addPage();
  // Never leave the heading alone: keep it with its first figure on the fresh page.
  if(following[0]?.type==='image'){
   const first=following[0];
   for(let step=0;step<=50;step++){figureLimits.set(first.id,480*(1-step/100));try{const f=await figureLayout(first);if(head+f.h+f.band+14<=capacity)return;}catch{break;}}
   figureLimits.delete(first.id);
  }
 }
 async function callout(b:Block,indent:number){
  // Nested callouts remain inside the parent container rather than double-boxing.
  if(active){rich(b.callout.rich_text,'',indent);if(b.children)await blocks(b.children,indent);return;}
  const boxX=left+indent,boxWidth=width-indent,pad=16;
  doc.font('Bold').fontSize(11);
  const estimate=doc.heightOfString(text(b.callout.rich_text),{width:boxWidth-pad*2,lineGap:4})+pad*2+8;
  room(Math.min(BOTTOM-M,estimate));
  const oldLeft=left,oldWidth=width;active={x:boxX,width:boxWidth,top:doc.y};
  left=boxX+pad;width=boxWidth-pad*2;
  doc.page.margins.top=M+pad;doc.page.margins.bottom=84;doc.y+=pad;base();
  rich(b.callout.rich_text);if(b.children)await blocks(b.children);
  const end=Math.min(BOTTOM,doc.y+8);
  frames.push({page:pageIndex(),x:active.x,y:active.top,width:active.width,height:Math.max(32,end-active.top)});
  active=undefined;left=oldLeft;width=oldWidth;doc.page.margins.top=M;doc.page.margins.bottom=54;doc.x=left;doc.y=end+12;base();
 }
 async function blocks(bs:Block[],indent=0){bs=flatten(bs);let number=0;for(let bi=0;bi<bs.length;bi++){const b=bs[bi];const v=b[b.type];if(b.type!=='numbered_list_item')number=0;switch(b.type){case 'heading_1':case 'heading_2':case 'heading_3':case 'heading_4':await keepSection(text(v.rich_text),headingSize(b),[...flatten(b.children??[]),...bs.slice(bi+1)],indent);doc.moveDown(.6);plain(text(v.rich_text),headingSize(b),true,indent);break;case 'paragraph':rich(v.rich_text,'',indent);break;case 'bulleted_list_item':rich(v.rich_text,'• ',indent+12);break;case 'numbered_list_item':rich(v.rich_text,`${++number}. `,indent+12);break;case 'to_do':rich(v.rich_text,v.checked?'[x] ':'[ ] ',indent+12);break;case 'callout':await callout(b,indent);continue;case 'quote':room(60);rich(v.rich_text,'',indent+12);break;case 'toggle':await keepSection(text(v.rich_text),12,flatten(b.children??[]),indent);plain(text(v.rich_text),12,true,indent);break;case 'code':plain(text(v.rich_text),9,false,indent+8);break;case 'divider':room(24);doc.moveTo(left,doc.y+6).lineTo(left+width,doc.y+6).strokeColor('#E6E5E3').stroke();doc.y+=20;break;case 'image':await image(b);break;case 'pdf':await importedPdf(b);break;case 'table':table(b);continue;case 'bookmark':case 'link_preview':rich([{text:{content:v.url,link:{url:v.url}},href:v.url}]);break;case 'table_of_contents':break;case 'column_list':case 'column':case 'synced_block':break;default:throw Error(`Unsupported block: ${b.type}`);}if(b.children)await blocks(b.children,Math.min(indent+(b.type.endsWith('list_item')?12:0),60));}}
  const front=book.frontMatter;let hasCover=false;
 if(front?.cover){const {bytes,img}=await loadImage(front.cover);const scale=Math.min(612/img.width,792/img.height);const cw=img.width*scale,ch=img.height*scale;doc.save().rect(0,0,612,792).fill('#102235');doc.image(bytes,(612-cw)/2,(792-ch)/2,{width:cw,height:ch});doc.restore();hasCover=true;doc.addPage();}
 doc.y=150;plain(mode==='proof'?'READING PROOF':'EBOOK',10,true);
 if(front?.titlePage.length){let first=true;for(const b of front.titlePage){if(b.type==='paragraph'&&text(b.paragraph.rich_text).trim()){if(first){plain(text(b.paragraph.rich_text),30,true);first=false;}else rich(b.paragraph.rich_text);}else await blocks([b]);}}else{plain(book.title,30,true);if(author)plain(author,14);}
 if(mode==='proof')plain('Unfinished material may be present. Not a publication-ready edition.',11);
 if(front?.notice.length){doc.addPage();plain('Copyright and Notices',20,true);await blocks(front.notice);}
 doc.addPage();plain('Contents',24,true);
 for(let i=0;i<book.chapters.length;i++){const c=book.chapters[i];room(40);doc.font('Body').fontSize(11).fillColor('#2468A0').text(displayChapterTitle(c.title),M,doc.y,{width:W,goTo:`chapter-${i}`,lineGap:4});doc.moveDown(.75);}base();
 for(let i=0;i<book.chapters.length;i++){doc.addPage();doc.addNamedDestination(`chapter-${i}`);doc.outline.addItem(displayChapterTitle(book.chapters[i].title));await keepSection(displayChapterTitle(book.chapters[i].title),24,flatten(book.chapters[i].blocks),0);plain(displayChapterTitle(book.chapters[i].title),24,true);await blocks(book.chapters[i].blocks);}
 const range=doc.bufferedPageRange();for(let i=0;i<range.count;i++){if(hasCover&&i===0)continue;doc.switchToPage(i);const bottom=doc.page.margins.bottom;doc.page.margins.bottom=0;doc.font('Body').fontSize(9).fillColor('#7D7A75').text(`${mode==='proof'?'PROOF • ':''}${i+1}`,M,747,{width:W,align:'center',lineBreak:false});doc.page.margins.bottom=bottom;}doc.end();const bytes=await result;/* Canonical object order also removes PNG async-stream completion ordering from the output bytes. */const combined=await PortablePDF.load(new Uint8Array(bytes),{updateMetadata:false});// Prepend an isolated graphics stream: backgrounds sit behind text and links.
 for(const frame of frames){const page=combined.getPage(frame.page),x=frame.x,y=page.getHeight()-frame.y-frame.height,w=frame.width,h=frame.height,r=5,k=0.5522847498*r;
 const path=`${x+r} ${y} m ${x+w-r} ${y} l ${x+w-r+k} ${y} ${x+w} ${y+r-k} ${x+w} ${y+r} c ${x+w} ${y+h-r} l ${x+w} ${y+h-r+k} ${x+w-r+k} ${y+h} ${x+w-r} ${y+h} c ${x+r} ${y+h} l ${x+r-k} ${y+h} ${x} ${y+h-r+k} ${x} ${y+h-r} c ${x} ${y+r} l ${x} ${y+r-k} ${x+r-k} ${y} ${x+r} ${y} c h`;
 const rgb=(hex:string)=>[0,2,4].map(i=>parseInt(hex.slice(i,i+2),16)/255).join(' ');
 const drawing=`q ${rgb('EAF3FC')} rg ${rgb('7CACD8')} RG 0.8 w ${path} B q ${path} W n ${rgb('2468A0')} rg ${x} ${y} 4 ${h} re f Q Q`;
 const underlay=combined.context.register(combined.context.flateStream(drawing));page.node.normalizedEntries().Contents!.insert(0,underlay);
 }
 for(const entry of imports){const original=entry.source.getPage(entry.page);if(!original.node.Contents())continue;const embedded=await combined.embedPage(original);const target=combined.getPage(entry.target);const scale=Math.min((target.getWidth()-48)/embedded.width,(target.getHeight()-100)/embedded.height);const width=embedded.width*scale,height=embedded.height*scale;target.drawPage(embedded,{x:(target.getWidth()-width)/2,y:70+(target.getHeight()-100-height)/2,width,height});}return Buffer.from(await combined.save({useObjectStreams:false}));
}
