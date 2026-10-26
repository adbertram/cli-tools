declare module 'heic-convert' {
 const convert:(options:{buffer:Buffer;format:'JPEG'|'PNG';quality?:number})=>Promise<ArrayBuffer>;
 export default convert;
}
declare module 'heic-decode' {
 const decode:(options:{buffer:Buffer})=>Promise<{width:number;height:number;data:Uint8ClampedArray}>;
 export default decode;
}
