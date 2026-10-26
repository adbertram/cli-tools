import heicConvert from 'heic-convert';
import heicDecode from 'heic-decode';
import {Jimp,JimpMime} from 'jimp';
function jpegSize(bytes:Buffer):{width:number;height:number}|null{let i=2;while(i+9<bytes.length){if(bytes[i++]!==255)continue;while(bytes[i]===255)i++;const m=bytes[i++];if(m===217||m===218)break;if(m===216||m===1||(m>=208&&m<=215))continue;const length=bytes.readUInt16BE(i);if(length<2)break;if((m>=192&&m<=195)||(m>=197&&m<=199)||(m>=201&&m<=203)||(m>=205&&m<=207))return{height:bytes.readUInt16BE(i+3),width:bytes.readUInt16BE(i+5)};i+=length;}return null;}
export async function normalizeImage(input:Buffer,mode:'native'|'ebook200'='native'):Promise<Buffer>{
 if(input.subarray(0,5).toString()==='%PDF-')return input;
 const prefix=input.subarray(0,80).toString('latin1');const heic=prefix.includes('ftyp')&&/(heic|heix|hevc|hevx|mif1|msf1)/.test(prefix);
 if(mode==='native')return heic?Buffer.from(await heicConvert({buffer:input,format:'JPEG',quality:0.95})):input;
 const png=input.subarray(0,8).equals(Buffer.from('89504e470d0a1a0a','hex'));const jpeg=input.subarray(0,2).equals(Buffer.from('ffd8','hex'));
 if(!png&&!jpeg&&!heic)throw Error('ebook200 supports PNG, JPEG and HEIC still images only.');
 const size=png?{width:input.readUInt32BE(16),height:input.readUInt32BE(20)}:jpeg?jpegSize(input):null;
 if(size&&size.width*size.height>60_000_000)throw Error(`Image ${size.width}x${size.height} exceeds the 60-megapixel decoder safety limit.`);
 let image:Awaited<ReturnType<typeof Jimp.read>>;
 if(heic){const decoded=await heicDecode({buffer:input});if(decoded.width*decoded.height>60_000_000)throw Error('HEIC exceeds the 60-megapixel safety limit.');image=Jimp.fromBitmap({width:decoded.width,height:decoded.height,data:Buffer.from(decoded.data.buffer,decoded.data.byteOffset,decoded.data.byteLength)});}
 else {try{image=await Jimp.read(input,{'image/jpeg':{maxResolutionInMP:60,maxMemoryUsageInMB:1024}});}catch(error){throw Error(`Image ${size?.width??'?'}x${size?.height??'?'}: ${String(error)}`);}}
 const width=image.bitmap.width,height=image.bitmap.height;const scale=Math.min(1,(504/72*200)/width,(480/72*200)/height);
 if(scale>=1&&!heic)return input;
 if(scale<1)image.resize({w:Math.max(1,Math.round(width*scale)),h:Math.max(1,Math.round(height*scale))});
 if(png)return image.getBuffer(JimpMime.png);
 return image.getBuffer(JimpMime.jpeg,{quality:92});
}
