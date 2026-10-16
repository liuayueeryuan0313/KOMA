// Credentials arrive only on stdin; stdout is a private process pipe, never an application log.
import {keyExchange,login,h5Login} from './scripts/campus-auth.mjs';
import {readFileSync,writeFileSync,mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,dirname,resolve,sep,basename} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {schoolProfile,schoolFetch,endpoint,requireEndpoints,jwProfile} from './scripts/school-profile.mjs';
const base=dirname(fileURLToPath(import.meta.url));
const input=JSON.parse(readFileSync(0,'utf8'));
const creds=input.credentials??{},config=input.config;
let school,fetchH5;
const identity=(profile,user)=>({name:String(profile.realName??profile.userRealName??profile.userName??profile.user_name??profile.xm??profile.name??profile.stu_name??profile.username??profile.userId??user),studentId:String(user)});
let temp;
function fail(code){throw Object.assign(new Error(code),{code});}
async function h5(path,body){
 requireEndpoints(school,['app_h5_base']);
 const response=await (fetchH5??=schoolFetch(school,[school.app_h5_base]))(endpoint(school.app_h5_base,'/service/schedule/'+path),{method:'POST',headers:{'Content-Type':'application/json',token:creds.token},body:JSON.stringify(body),redirect:'manual',signal:AbortSignal.timeout(20000)});
 let data;try{data=await response.json();}catch{fail('FETCH_FAILED');}
 if([401,403].includes(response.status)||[401,403].includes(Number(data.code))||String(data.msg??'').includes('header[token]'))fail('TOKEN_REQUIRED');
 if(response.status!==200||String(data.code)!=='200')fail('FETCH_FAILED');return data.data;
}
try{
 school=schoolProfile(config);
 let result;
 if(input.operation==='app_init'){
  if(!creds.campus_password||!creds.student_id)fail('CREDENTIALS_MISSING');
  requireEndpoints(school,['app_origin','app_h5_base','app_school_id','app_yyid','app_exchange_path']);
  const keys=await keyExchange(school),session=await login(keys,creds.student_id,creds.campus_password);
  const token=await h5Login(session);if(!token)fail('TOKEN_REQUIRED');
  result={token,identity:identity(session.profile,creds.student_id),identityFields:Object.keys(session.profile)};
 }else if(input.operation==='app_fetch'){
  if(!creds.token)fail('TOKEN_REQUIRED');
  const meta=await h5('currWeek',{}),maximum=Number(meta?.maxWeekNumber);
  if(!Number.isInteger(maximum)||maximum<1||maximum>53||!meta.xnxq||!meta.beginDate)fail('DATA_INVALID');
  const rows=[];
  for(let week=1;week<=maximum;week++){
   const data=await h5('getScheduleData',{skzc:week});if(!Array.isArray(data))fail('DATA_INVALID');
   for(const row of data)if(Number(row.skzc)!==week||row.xnxq!==meta.xnxq)fail('DATA_INVALID');rows.push(...data);
  }
  if(!rows.length)fail('EMPTY_TIMETABLE');
  result={snapshot:{xnxq:meta.xnxq,beginDate:meta.beginDate,endDate:meta.endDate,maxWeekNumber:maximum,rows,sourceAdapter:'app-h5',fetchedAt:new Date().toISOString()},identity:creds.app_identity??identity(meta,creds.student_id)};
 }else if(['jw_fetch','lab_fetch','jw_login','lab_login'].includes(input.operation)){
  temp=mkdtempSync(join(tmpdir(),'komama-'));const output=join(temp,'response.json'),configPath=join(temp,'config.json');
  writeFileSync(configPath,JSON.stringify(config));
  let script,args,extra;
  if(input.operation.startsWith('jw_')){
   if(!creds.jw_password||!creds.student_id)fail('CREDENTIALS_MISSING');
   const profile=jwProfile(JSON.parse(readFileSync(join(base,'jw-request.json'),'utf8')),school);
   const year=String(config.term).split('-')[0];if(!/^\d{4}$/.test(year)||!/^\d{1,2}$/.test(String(config.jw_semester_code)))fail('INVALID_TERM_PROFILE');
   profile.form.xnm=profile.periodsForm.xnm=year;profile.form.xqm=profile.periodsForm.xqm=String(config.jw_semester_code);
   profile.calendarTerm=config.term;profile.maxWeekNumber=config.maxWeekNumber;
   const path=join(temp,'jw-request.json');writeFileSync(path,JSON.stringify(profile));
   script='fetch-jw-password.mjs';args=['--request-config',path];extra={JW_USER:creds.student_id,JW_PASS:creds.jw_password};
  }else{
   if(!creds.campus_password||!creds.student_id)fail('CREDENTIALS_MISSING');
   script='fetch-lab.mjs';args=['--config',configPath];extra={SSO_USER:creds.student_id,SSO_PASS:creds.campus_password};
  }
  const child=spawnSync(process.execPath,[join(base,'scripts',script),'--allow-password-login',...(input.operation.endsWith('_login')?['--auth-only']:[]),...args,'--output',output],{env:{...process.env,...extra},encoding:'utf8',timeout:160000,maxBuffer:3*1024*1024,windowsHide:true});
  if(child.status!==0){
   let report;try{report=JSON.parse(child.stdout);}catch{}
   fail(report?.reason??report?.state??'AUTHENTICATION_FAILED');
  }
  result={payload:JSON.parse(readFileSync(output,'utf8'))};
 }else fail('INVALID_OPERATION');
 process.stdout.write(JSON.stringify({ok:true,...result}));
}catch(e){process.stdout.write(JSON.stringify({ok:false,code:/^[A-Z_0-9]+$/.test(e.code??'')?e.code:'AUTHENTICATION_OR_NETWORK_FAILED'}));process.exitCode=2;}
finally{if(temp){if(!resolve(temp).startsWith(resolve(tmpdir())+sep)||!basename(temp).startsWith('komama-'))throw Error('Unexpected temporary directory');rmSync(temp,{recursive:true,force:true});}}
