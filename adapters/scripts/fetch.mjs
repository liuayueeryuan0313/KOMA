import {readFileSync, mkdirSync, writeFileSync, renameSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {schoolProfile,schoolFetch,endpoint,requireEndpoints} from './school-profile.mjs';

function arg(name, fallback) { const i=process.argv.indexOf(name); if(i<0)return fallback; if(!process.argv[i+1]||process.argv[i+1].startsWith('--'))throw Error('Missing '+name);return process.argv[i+1]; }
function fail(code,message){const e=Error(message);e.code=code;throw e;}
function atomic(path,data){mkdirSync(dirname(path),{recursive:true});const temp=path+'.'+process.pid+'.tmp';writeFileSync(temp,data);renameSync(temp,path);}
async function main(){
 const configFile=arg('--config');const school=schoolProfile(configFile?JSON.parse(readFileSync(configFile,'utf8')):{});requireEndpoints(school,['app_h5_base']);const fetchSchool=schoolFetch(school,[school.app_h5_base]);
 const file=arg('--token-file','.local/h5-token.json');
 let token;
 try{ token=JSON.parse(readFileSync(file,'utf8')).token; }catch{fail('TOKEN_REQUIRED','Cannot read local token file');}
 if(typeof token!=='string'||!token.trim())fail('TOKEN_REQUIRED','Token missing');
 async function query(path,body){
  let response;
  try{response=await fetchSchool(endpoint(school.app_h5_base,'/service/schedule/'+path),{method:'POST',headers:{'content-type':'application/json',token},body:JSON.stringify(body),signal:AbortSignal.timeout(20000)});}catch{fail('FETCH_FAILED','Network request failed: '+path);}
  let json;try{json=await response.json();}catch{fail('FETCH_FAILED','Non-JSON response: '+path);}
  if([401,403].includes(response.status)||[401,403].includes(Number(json.code))||String(json.msg??'').includes('header[token]'))fail('TOKEN_REQUIRED','Token rejected; no re-login attempted');
  if(response.status!==200||String(json.code)!=='200')fail('FETCH_FAILED',`Request failed: ${path}; HTTP=${response.status}; code=${String(json.code).slice(0,20)}`);
  return json.data;
 }
 const meta=await query('currWeek',{});
 const max=Number(meta?.maxWeekNumber);
 if(!Number.isInteger(max)||max<1||max>53||!meta.xnxq||!meta.beginDate)fail('DATA_INVALID','Invalid term metadata');
 const rows=[],weeks=[];
 for(let week=1;week<=max;week++){
  const data=await query('getScheduleData',{skzc:week});
  if(!Array.isArray(data))fail('DATA_INVALID','Invalid weekly payload');
  for(const r of data)if(Number(r.skzc)!==week||r.xnxq!==meta.xnxq||!r.kcmc||!r.xq||!r.ksjc||!r.jsjc)fail('DATA_INVALID','Invalid course fields');
  rows.push(...data);weeks.push({week,count:data.length});
 }
 if(!rows.length&&!process.argv.includes('--allow-empty'))fail('DATA_INVALID','Entire term empty; retained previous file (use --allow-empty only if confirmed)');
 const result={fetchedAt:new Date().toISOString(),source:school.app_h5_base,xnxq:meta.xnxq,weekNumber:meta.weekNumber,maxWeekNumber:max,beginDate:meta.beginDate,endDate:meta.endDate,weeks,rows};
 const output=resolve(arg('--output','build/timetable.json'));
 atomic(output,JSON.stringify(result,null,2));
 console.log(JSON.stringify({state:'READY',output,term:meta.xnxq,occurrences:rows.length,courses:new Set(rows.map(r=>r.kcmc)).size,passwordLoginUsed:false}));
}
main().catch(e=>{console.error(JSON.stringify({state:e.code??'FETCH_FAILED',message:e.code?e.message:'Local input/output error; no re-login attempted'}));process.exitCode=e.code==='TOKEN_REQUIRED'?2:3;});
