import {createHmac} from 'node:crypto';
export const ORIGIN='https://syjxgl.sdut.edu.cn';
const BODY_KEY='zhxintd201020301', TIME_KEY='zxtd_256-bit-secret-key-2025-8-7';
export function bodySignature(data,params,authorization=null){
 const values={};
 function flatten(value,key=''){
  if(Array.isArray(value)){for(const item of value)if(item!==null&&typeof item==='object')flatten(item,key);else(values[key]??=[]).push(item);}
  else if(value&&typeof value==='object'){for(const [name,item] of Object.entries(value))if(item!==null&&typeof item==='object')flatten(item,name);else(values[name]??=[]).push(item);}
 }
 if(data)flatten(data);if(params)flatten(params);
 if(!Object.keys(values).length)values.Authorization=[authorization];
 const text=Object.keys(values).sort((a,b)=>a.localeCompare(b,'zh-CN')).map(k=>values[k].sort().map(v=>k+'='+v).join('')).join('').replace(/\n|\r|\u0085|\u2028|\u2029/g,'');
 return createHmac('sha256',BODY_KEY).update(text).digest('hex').toUpperCase();
}
export function timestampSignature(timestamp,nonce){return createHmac('sha512',TIME_KEY).update(timestamp+'-'+nonce).digest('hex');}
export class LabClient{
 constructor(fetchImpl=globalThis.fetch,{base=ORIGIN}={}){this.fetchImpl=fetchImpl;this.base=base;this.authorization=null;this.cookies=new Map();this.offset=0;this.trace=[];}
 async post(path,{data,params,route=null}={}){
  const allowed=['/config/sys/cas/login','/teach/teach/stuTime/listStuTimePage'];
  if(!allowed.includes(path))throw Error('UNAPPROVED_ENDPOINT');
  const url=new URL(this.base.replace(/\/+$/,'')+path);if(params)for(const[k,v]of Object.entries(params))url.searchParams.set(k,String(v));
  const timestamp=String(Date.now()+this.offset),nonce=Math.random().toString(36).substring(2,15)+Math.random().toString(36).substring(2,15);
  const headers={'Accept':'application/json, text/plain, */*','Content-Type':'application/json;charset=UTF-8',
   Origin:new URL(this.base).origin,Referer:this.base+'/',MenuId:'null',currentRoutePath:route===null?'null':JSON.stringify(route),
   random:timestamp,timestamp,nonce,signature:timestampSignature(timestamp,nonce),
   zhxhsign:bodySignature(data,params,this.authorization)};
  if(this.authorization)headers.Authorization=this.authorization;
  if(this.cookies.size)headers.Cookie=[...this.cookies].map(([k,v])=>k+'='+v).join('; ');
  const res=await this.fetchImpl(url,{method:'POST',headers,body:data===undefined?undefined:JSON.stringify(data),redirect:'manual',signal:AbortSignal.timeout(20000)});
  for(const cookie of res.headers.getSetCookie()){const pair=cookie.split(';')[0],i=pair.indexOf('=');this.cookies.set(pair.slice(0,i),pair.slice(i+1));}
  const text=await res.text();let json;try{json=JSON.parse(text);}catch{throw Error('NON_JSON_RESPONSE');}
  this.trace.push({path,method:'POST',status:res.status,businessCode:json.code??null,requestFields:Object.keys(params??data??{}),responseBytes:Buffer.byteLength(text)});
  if(!res.ok)throw Error('HTTP_'+res.status);
  return json;
 }
 clear(){this.authorization=null;this.cookies.clear();}
}
