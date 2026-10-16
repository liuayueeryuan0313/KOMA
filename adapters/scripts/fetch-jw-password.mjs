import {readFileSync,writeFileSync,mkdirSync,renameSync} from 'node:fs';
import {createPublicKey,publicEncrypt,constants,createHash} from 'node:crypto';
import {sanitizeSchedule,sanitizePeriods,validateProfile} from './jw-core.mjs';
import {schoolProfile,schoolFetch} from './school-profile.mjs';

import {dirname,resolve} from 'node:path';
function arg(name,fallback){const i=process.argv.indexOf(name);if(i<0)return fallback;if(!process.argv[i+1]||process.argv[i+1].startsWith('--'))throw Error('MISSING_ARGUMENT');return process.argv[i+1];}
function atomic(file,value){file=resolve(file);mkdirSync(dirname(file),{recursive:true});const temp=file+'.'+process.pid+'.tmp';writeFileSync(temp,JSON.stringify(value,null,2));renameSync(temp,file);}
const output=arg('--output','build/jw-response.sanitized.json'),evidenceOutput=arg('--evidence-output');
const authOnly=process.argv.includes('--auth-only');
let origin,loginPath,fetchSchool;
const jar=new Map(),trace=[];
let loginSubmitted=false;
async function request(path,method='GET',body){
 const url=new URL(path,origin);if(url.origin!==origin)throw Error('EXTERNAL_REDIRECT_REQUIRES_REVIEW');
 const headers={'Accept':'text/html,application/json;q=0.9,*/*;q=0.8','Cookie':[...jar].map(([k,v])=>k+'='+v).join('; '),'Referer':origin+loginPath};
 if(body){headers['Content-Type']='application/x-www-form-urlencoded; charset=UTF-8';headers.Origin=origin;headers['X-Requested-With']='XMLHttpRequest';}
 const started=Date.now();const res=await fetchSchool(url,{method,headers,body,redirect:'manual',signal:AbortSignal.timeout(20000)});
 for(const line of res.headers.getSetCookie()){const pair=line.split(';')[0],i=pair.indexOf('=');jar.set(pair.slice(0,i),pair.slice(i+1));}
 const text=await res.text();
 const event={at:new Date().toISOString(),method,path:url.pathname,queryNames:[...url.searchParams.keys()],requestFieldNames:body?[...new URLSearchParams(body).keys()]:[],status:res.status,contentType:res.headers.get('content-type'),durationMs:Date.now()-started,responseBytes:Buffer.byteLength(text),setCookieNames:res.headers.getSetCookie().map(s=>s.split('=')[0])};
 if(res.headers.get('location')){const next=new URL(res.headers.get('location'),url);event.redirectOrigin=next.origin;event.redirectPath=next.pathname;}
 trace.push(event);
 return {res,text,url};
}
function attr(tag,name){return tag.match(new RegExp('\\b'+name+'\\s*=\\s*(?:"([^"]*)"|\'([^\']*)\'|([^\\s>]+))','i'))?.slice(1).find(v=>v!==undefined)??'';}
function inputs(html){return [...html.matchAll(/<input\b[^>]*>/gi)].map(m=>({name:attr(m[0],'name'),value:attr(m[0],'value'),id:attr(m[0],'id')}));}
function field(html,id){return inputs(html).find(v=>v.id===id)?.value;}
function json(response){try{return JSON.parse(response.text);}catch{throw Error('UNEXPECTED_NON_JSON');}}
function stopOnVerification(html){
 if(/<input\b[^>]*(?:name|id)=["'](?:yzm|dlyzm)["']/i.test(html))throw Error('HUMAN_VERIFICATION_REQUIRED');
 if(field(html,'dxsyrz')==='1')throw Error('SMS_VERIFICATION_REQUIRED');
 if(field(html,'userPolicyOn')==='1')throw Error('AGREEMENT_REQUIRES_REVIEW');
}
let report;
try{
 if(!process.argv.includes('--allow-password-login'))throw Error('EXPLICIT_PASSWORD_LOGIN_FLAG_REQUIRED');
 const profile=JSON.parse(readFileSync(arg('--request-config','jw-request.json'),'utf8'));validateProfile(profile);
 origin=profile.origin;loginPath=(profile.contextPath??'/jwglxt')+'/xtgl/login_slogin.html';
 fetchSchool=schoolFetch(schoolProfile(profile.school_config),[origin]);
 const user=process.env.JW_USER,password=process.env.JW_PASS;if(!user||!password)throw Error('CREDENTIALS_MISSING');
 const page=await request(loginPath);if(page.res.status!==200)throw Error('LOGIN_PAGE_FAILED');stopOnVerification(page.text);
 const csrf=field(page.text,'csrftoken');if(!csrf)throw Error('CSRF_FIELD_MISSING');
 if(field(page.text,'mmsfjm')!=='1')throw Error('UNKNOWN_PASSWORD_ENCRYPTION_MODE');
 const prefix=profile.contextPath??'/jwglxt';
 const pub=json(await request(prefix+'/xtgl/login_getPublicKey.html?time='+Date.now()));
 if(!pub.modulus||!pub.exponent)throw Error('PUBLIC_KEY_MISSING');
 const identityCheck=json(await request(prefix+'/xtgl/yhgl_cxXxqrCheck.html','POST',new URLSearchParams({yhm:user}).toString()));
 if(identityCheck!==false)throw Error('ADDITIONAL_IDENTITY_CONFIRMATION_REQUIRED');
 if(field(page.text,'mmsrddcshkzfs')==='1'){
  const state=json(await request(prefix+'/xtgl/login_cxDlxgxx.html','POST',new URLSearchParams({yhm:user}).toString()));
  if(String(state)==='0')throw Error('USER_NOT_FOUND');
  if(Number(String(state).split('_')[0])>=Number(field(page.text,'yzcskz')||5))throw Error('ACCOUNT_FAILURE_LIMIT_REQUIRES_HUMAN_REVIEW');
 }
 const publicKey=createPublicKey({key:{kty:'RSA',n:Buffer.from(pub.modulus,'base64').toString('base64url'),e:Buffer.from(pub.exponent,'base64').toString('base64url')},format:'jwk'});
 const encrypted=publicEncrypt({key:publicKey,padding:constants.RSA_PKCS1_PADDING},Buffer.from(password)).toString('base64');
 const data=new URLSearchParams({csrftoken:csrf,language:field(page.text,'language')||'zh_CN',ydType:field(page.text,'ydType')||'',yhm:user});
 data.append('mm',encrypted);data.append('mm',encrypted);
 loginSubmitted=true;
 let logged=await request(loginPath+'?time='+Date.now(),'POST',data.toString());
 const loginResponseStatus=logged.res.status;
 let redirects=0;
 while([301,302,303,307,308].includes(logged.res.status)&&redirects++<5){
  const next=new URL(logged.res.headers.get('location'),logged.url);if(next.origin!==origin)throw Error('EXTERNAL_AUTHENTICATION_REDIRECT');
  logged=await request(next.href);
 }
 if(logged.url.pathname===loginPath && logged.res.status===200){
  stopOnVerification(logged.text);
  const tips=logged.text.match(/<p\b[^>]*id=["']tips["'][^>]*>([\s\S]*?)<\/p>/i)?.[1]?.replace(/<[^>]*>/g,'').trim();
  report={state:'LOGIN_FAILED',loginSubmitted:true,loginAttempts:1,loginResponseStatus,serverMessage:tips?.replaceAll(user,'<account>')?.replaceAll(password,'<redacted>')||'Login page returned',trace};
 }else{
  const query='?'+new URLSearchParams(profile.query);
  const rawSchedule=json(await request(profile.path+query,'POST',new URLSearchParams(profile.form).toString()));
  const schedule=sanitizeSchedule(rawSchedule);
  const identity={name:String(rawSchedule.xsxx?.XM||user),studentId:String(rawSchedule.xsxx?.XH||user)};
  if(identity.studentId!==user)throw Error('STUDENT_ID_MISMATCH');
  if(!authOnly&&schedule.kbList.length===0)throw Error('EMPTY_TIMETABLE');
  const periods=authOnly?[]:sanitizePeriods(json(await request(profile.periodsPath+query,'POST',new URLSearchParams(profile.periodsForm).toString())));
  const payload={schemaVersion:1,adapter:'jw-web',fetchedAt:new Date().toISOString(),identity,request:{xnm:profile.form.xnm,xqm:profile.form.xqm,gnmkdm:'N2151'},calendarTerm:profile.calendarTerm,maxWeekNumber:profile.maxWeekNumber,...schedule,periods};
  atomic(output,payload);
  report={state:'VERIFIED',testedAt:new Date().toISOString(),freshHttpSession:true,source:'independent HTTP client trace; not Chrome HAR',loginSubmitted:true,loginAttempts:1,loginResponseStatus,scheduleRules:schedule.kbList.length,unscheduled:schedule.sjkList.length,periods:periods.length,passwordSaved:false,cookieSaved:false,csrfSaved:false,appLoginRequested:false,trace};
 }
}catch(e){report={state:'STOPPED',reason:/^[A-Z_]+$/.test(e.message)?e.message:'NETWORK_OR_PROTOCOL_ERROR',loginSubmitted,loginAttempts:loginSubmitted?1:0,passwordSaved:false,cookieSaved:false,appLoginRequested:false,trace};}
finally{jar.clear();}
if(evidenceOutput)atomic(evidenceOutput,report);
console.log(JSON.stringify(report,null,2));if(report.state!=='VERIFIED')process.exitCode=2;
