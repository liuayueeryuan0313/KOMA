import {readFileSync} from 'node:fs';
import {lookup} from 'node:dns/promises';
import {isIP} from 'node:net';
import {request as httpRequest} from 'node:http';
import {request as httpsRequest} from 'node:https';
import {gunzipSync,inflateSync,brotliDecompressSync} from 'node:zlib';
export const DEFAULT_SCHOOL=JSON.parse(readFileSync(new URL('../school-defaults.json',import.meta.url),'utf8'));
const urlFields=['app_origin','app_h5_base','jw_base','lab_base','sso_base'];
const fail=code=>{throw Object.assign(new Error(code),{code});};
export function publicAddress(address){
 if(isIP(address)===4){const [a,b,c]=address.split('.').map(Number);return !(a===0||a===10||a===127||a>=224||a===169&&b===254||a===172&&b>=16&&b<=31||a===192&&(b===168||b===0)||a===100&&b>=64&&b<=127||a===198&&(b===18||b===19||b===51&&c===100)||a===203&&b===0&&c===113);}
 if(isIP(address)===6)return /^[23][0-9a-f]{0,3}:/i.test(address)&&!address.toLowerCase().startsWith('2001:db8:');
 return false;
}
export function schoolProfile(config={}){
 const custom=config.school_profile==='custom';
 const school=custom?{...Object.fromEntries(Object.entries(DEFAULT_SCHOOL).map(([key,value])=>[key,urlFields.includes(key)||['name','app_school_id','app_yyid'].includes(key)?'':value])),...config.school_custom}:{...DEFAULT_SCHOOL};
 for(const key of urlFields){
  const value=school[key];if(!value)continue;
  let url;try{url=new URL(value);}catch{fail('SCHOOL_CONFIG_INVALID');}
  if(!['https:',...(key==='app_origin'?['http:']:[])].includes(url.protocol)||url.username||url.password||url.search||url.hash||/[\s\\%]/.test(value)||url.hostname==='localhost'||url.hostname.endsWith('.localhost')||url.hostname.endsWith('.local')||url.hostname.endsWith('.internal'))fail('SCHOOL_CONFIG_INVALID');
  if(isIP(url.hostname.replace(/^\[|\]$/g,''))&&!publicAddress(url.hostname.replace(/^\[|\]$/g,'')))fail('SCHOOL_CONFIG_INVALID');
  if(key==='app_origin'&&url.pathname!=='/')fail('SCHOOL_CONFIG_INVALID');
  school[key]=value.replace(/\/+$/,'');
 }
 return {...school,custom};
}
export function endpoint(base,path){if(!base)fail('SCHOOL_ENDPOINT_MISSING');return base.replace(/\/+$/,'')+'/'+path.replace(/^\/+/, '');}
export function requireEndpoints(school,keys){for(const key of keys)if(!school[key])fail('SCHOOL_ENDPOINT_MISSING');}
export function schoolFetch(school,origins,fetchImpl=globalThis.fetch,lookupImpl=lookup){
 const allowed=new Set(origins.filter(Boolean).map(base=>new URL(base).origin)),checked=new Map();
 return async function(url,options={}){
  url=new URL(url);if(!allowed.has(url.origin)||url.username||url.password)fail('UNEXPECTED_AUTH_ORIGIN');
  if(school.custom&&!checked.has(url.hostname)){
   const addresses=await lookupImpl(url.hostname.replace(/^\[|\]$/g,''),{all:true,verbatim:true});
   if(!addresses.length||addresses.some(entry=>!publicAddress(entry.address)))fail('SCHOOL_ADDRESS_NOT_PUBLIC');
   checked.set(url.hostname,addresses);
  }
  // Pin the validated DNS answer to the connection; never resolve a second time.
  if(school.custom&&fetchImpl===globalThis.fetch)return pinnedFetch(url,options,checked.get(url.hostname));
  return fetchImpl(url,{...options,redirect:'manual'});
 };
}
function pinnedFetch(url,options,addresses){
 return new Promise((resolve,reject)=>{
  const request=(url.protocol==='https:'?httpsRequest:httpRequest)(url,{method:options.method??'GET',headers:options.headers,signal:options.signal,agent:false,lookup:(_host,settings,callback)=>settings.all?callback(null,addresses):callback(null,addresses[0].address,addresses[0].family)},response=>{
   const chunks=[];let size=0;const max=8*1024*1024;
   response.on('data',chunk=>{size+=chunk.length;if(size>max)response.destroy(new Error('RESPONSE_TOO_LARGE'));else chunks.push(chunk);});
   response.on('error',reject);
   response.on('end',()=>{try{
    let body=Buffer.concat(chunks);const encoding=response.headers['content-encoding'];
    if(encoding==='gzip')body=gunzipSync(body,{maxOutputLength:max});else if(encoding==='deflate')body=inflateSync(body,{maxOutputLength:max});else if(encoding==='br')body=brotliDecompressSync(body,{maxOutputLength:max});
    const headers=new Headers();for(const [key,value] of Object.entries(response.headers)){if(Array.isArray(value))for(const item of value)headers.append(key,item);else if(value!==undefined)headers.append(key,value);}
    resolve(new Response([204,205,304].includes(response.statusCode)?null:body,{status:response.statusCode,headers}));
   }catch(error){reject(error);}});
  });
  request.on('error',reject);if(options.body!==undefined)request.write(options.body);request.end();
 });
}
export function jwProfile(profile,school){
 requireEndpoints(school,['jw_base']);const url=new URL(school.jw_base),prefix=url.pathname.replace(/\/+$/,'');
 return {...profile,origin:url.origin,contextPath:prefix,path:prefix+'/kbcx/xskbcx_cxXsgrkb.html',periodsPath:prefix+'/kbcx/xskbcx_cxRjc.html',periodsForm:{...profile.periodsForm,xqh_id:school.jw_campus_id},school_config:{school_profile:school.custom?'custom':'sdut',school_custom:school.custom?Object.fromEntries(Object.entries(school).filter(([key])=>key!=='custom')):{}}};
}
