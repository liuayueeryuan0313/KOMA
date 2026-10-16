import {createCipheriv,randomInt} from 'node:crypto';
import {readFileSync,mkdirSync,writeFileSync,renameSync} from 'node:fs';
import {dirname,resolve} from 'node:path';
import {LabClient,ORIGIN} from './lab-core.mjs';
import {schoolProfile,schoolFetch,endpoint,requireEndpoints} from './school-profile.mjs';

function arg(name,fallback){const i=process.argv.indexOf(name);if(i<0)return fallback;if(!process.argv[i+1]||process.argv[i+1].startsWith('--'))throw Error('MISSING_ARGUMENT');return process.argv[i+1];}
function atomic(file,value){file=resolve(file);mkdirSync(dirname(file),{recursive:true});const temp=file+'.'+process.pid+'.tmp';writeFileSync(temp,JSON.stringify(value,null,2));renameSync(temp,file);}
const output=arg('--output','build/lab-response.sanitized.json'),evidenceOutput=arg('--evidence-output');
const authOnly=process.argv.includes('--auth-only');
const trace=[],jars=new Map();let loginSubmitted=false;const lab=new LabClient();
let school,labOrigin,ssoOrigin,fetchSchool;
function jar(origin){if(!jars.has(origin))jars.set(origin,new Map());return jars.get(origin);}
async function request(url,{method='GET',body}={}){
 url=new URL(url);if(url.protocol!=='https:'||![labOrigin,ssoOrigin].includes(url.origin))throw Error('UNEXPECTED_AUTH_ORIGIN');
 const headers={Cookie:[...jar(url.origin)].map(([k,v])=>k+'='+v).join('; ')};
 if(body){headers['Content-Type']='application/x-www-form-urlencoded';headers.Origin=url.origin;headers.Referer=url.href;}
 const res=await fetchSchool(url,{method,headers,body,redirect:'manual',signal:AbortSignal.timeout(20000)});
 for(const raw of res.headers.getSetCookie()){const p=raw.split(';')[0],i=p.indexOf('=');jar(url.origin).set(p.slice(0,i),p.slice(i+1));}
 const text=await res.text();trace.push({origin:url.origin,path:url.pathname,method,status:res.status,queryNames:[...url.searchParams.keys()],requestFieldNames:body?[...new URLSearchParams(body).keys()]:[],responseBytes:Buffer.byteLength(text)});
 return {url,res,text};
}
async function redirects(response){
 for(let count=0;[301,302,303,307,308].includes(response.res.status);count++){
  if(count>=10)throw Error('TOO_MANY_REDIRECTS');response=await request(new URL(response.res.headers.get('location'),response.url));
 }
 return response;
}
const attr=(tag,name)=>tag.match(new RegExp('\\b'+name+'=["\']([^"\']*)["\']','i'))?.[1]??'';
const sample=n=>{const chars='ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678';return Array.from({length:n},()=>chars[randomInt(chars.length)]).join('');};
function encrypt(password,salt){
 const cipher=createCipheriv('aes-128-cbc',Buffer.from(salt.trim()),Buffer.from(sample(16)));
 return Buffer.concat([cipher.update(sample(64)+password,'utf8'),cipher.final()]).toString('base64');
}
let report;
try{
 if(!process.argv.includes('--allow-password-login'))throw Error('EXPLICIT_PASSWORD_LOGIN_FLAG_REQUIRED');
 const config=JSON.parse(readFileSync(arg('--config','config.json'),'utf8'));
 school=schoolProfile(config);requireEndpoints(school,['lab_base','sso_base']);
 labOrigin=new URL(school.lab_base).origin;ssoOrigin=new URL(school.sso_base).origin;
 fetchSchool=schoolFetch(school,[school.lab_base,school.sso_base]);lab.base=school.lab_base;lab.fetchImpl=fetchSchool;
 if(!config.term)throw Error('CONFIG_TERM_REQUIRED');
 const user=process.env.SSO_USER,password=process.env.SSO_PASS;if(!user||!password)throw Error('CREDENTIALS_MISSING');
 let page=await redirects(await request(endpoint(school.lab_base,school.lab_cas_entry)));
 if(page.url.origin!==ssoOrigin||page.res.status!==200)throw Error('LOGIN_PAGE_UNEXPECTED');
 const form=page.text.match(/<form\b[^>]*id=["']pwdFromId["'][^>]*>([\s\S]*?)<\/form>/i)?.[1];
 if(!form)throw Error('PASSWORD_LOGIN_FORM_MISSING');
 const tags=[...form.matchAll(/<input\b[^>]*>/gi)].map(m=>m[0]);
 const salt=attr(tags.find(t=>attr(t,'id')==='pwdEncryptSalt')??'','value');
 if(salt.length!==16)throw Error('AES_SALT_UNEXPECTED');
 const check=await request(endpoint(school.sso_base,'/checkNeedCaptcha.htl')+'?'+new URLSearchParams({username:user,_:String(Date.now())}));
 const state=JSON.parse(check.text);if(state.isNeed!==false)throw Error('HUMAN_CAPTCHA_REQUIRED');
 const params=new URLSearchParams();
 for(const tag of tags)if(attr(tag,'type')==='hidden'&&attr(tag,'name'))params.set(attr(tag,'name'),attr(tag,'value'));
 params.set('username',user);params.set('password',encrypt(password,salt));params.set('captcha','');
 loginSubmitted=true;
 let logged=await request(page.url,{method:'POST',body:params.toString()});
 if(logged.res.status===200&&logged.url.origin===ssoOrigin){
  const message=logged.text.match(/id=["']showErrorTip["'][^>]*>([\s\S]*?)<\/span>/i)?.[1]?.replace(/<[^>]*>/g,'').trim();
  const safe=message?.replaceAll(user,'<account>').replaceAll(password,'<redacted>');
  report={state:'LOGIN_FAILED',message:safe||'Authentication page returned',loginAttempts:1,trace};
  process.exitCode=2;
 }else{
  logged=await redirects(logged);
  if(logged.url.origin!==labOrigin)throw Error('ADDITIONAL_AUTH_STEP_REQUIRED');
  // Official /common/cas component obtains key1 from its route query id.
  const hashQuery=logged.url.hash.split('?').slice(1).join('?');
  const authorization=new URLSearchParams(hashQuery).get('id');
  if(!authorization)throw Error('LAB_AUTHORIZATION_ROUTE_MISSING');
  lab.authorization=authorization;lab.cookies=jar(labOrigin);
  const identity=await lab.post('/config/sys/cas/login');
  if(identity.code!==200||identity.user_type!=='Student')throw Error('LAB_CAS_EXCHANGE_FAILED');
  if(identity.cts)lab.offset=Number(identity.cts)-Date.now();
  const pages=[];let totalPages=1,expectedTotal,expectedPages;
  for(let number=1;!authOnly&&number<=totalPages;number++){
   if(number>100)throw Error('PAGINATION_LIMIT');
   const body={yearterm:config.term,currpage:number,pagesize:15};
   const result=await lab.post('/teach/teach/stuTime/listStuTimePage',{data:body,route:'/6001/modules/teach/stu/result/result'});
   if(result.code!==200||!Array.isArray(result.result?.list))throw Error('LAB_FETCH_FAILED');
   const p=result.result,total=Number(p.totalCount),count=Number(p.totalPage);
   if(!Number.isInteger(total)||total<0||!Number.isInteger(count)||count<1||Number(p.currPage)!==number||Number(p.pageSize)!==15||count!==Math.max(1,Math.ceil(total/15))||p.list.length!==Math.min(15,Math.max(0,total-(number-1)*15)))throw Error('INVALID_PAGINATION');
   if(number===1){expectedTotal=total;expectedPages=count;}
   if(total!==expectedTotal||count!==expectedPages)throw Error('PAGINATION_CHANGED_DURING_FETCH');
   const fields=['course_name','exp_name','week','week_day','jc_start','jc_end','room_name','teacher_name','form','row_id'];
   pages.push({request:body,result:{totalCount:result.result.totalCount,pageSize:result.result.pageSize,totalPage:result.result.totalPage,currPage:result.result.currPage,list:result.result.list.map(row=>Object.fromEntries(fields.filter(k=>k in row).map(k=>[k,row[k]])))}});
   totalPages=Number(result.result.totalPage);if(!Number.isInteger(totalPages)||totalPages<1)throw Error('INVALID_PAGINATION');
  }
  if(!authOnly&&(pages.reduce((n,p)=>n+p.result.list.length,0)!==expectedTotal||!expectedTotal))throw Error('EMPTY_OR_INCOMPLETE_LAB_TIMETABLE');
  const studentIdentity={name:String(identity.realName??identity.userRealName??identity.userName??identity.user_name??identity.xm??identity.stu_name??identity.name??identity.username??user),studentId:String(identity.user_no??user)};
  if(studentIdentity.studentId!==user)throw Error('STUDENT_ID_MISMATCH');
  const payload={schemaVersion:1,adapter:'lab-har',calendarTerm:config.term,capturedAt:new Date().toISOString(),pages,sourceMode:'live_cas_signed_http',identity:studentIdentity,identityFields:Object.keys(identity)};
  atomic(output,payload);
  report={state:'VERIFIED',testedAt:new Date().toISOString(),freshHttpSession:true,loginMethod:'official_school_CAS',loginAttempts:1,
          signedRequestsGeneratedFresh:true,authorizationObtainedFromCAS:true,pages:pages.length,occurrences:pages.reduce((n,p)=>n+p.result.list.length,0),
          passwordSaved:false,cookiesSaved:false,authorizationSaved:false,trace:[...trace,...lab.trace]};
 }
}catch(e){report={state:'STOPPED',reason:/^[A-Z_0-9]+$/.test(e.message)?e.message:'NETWORK_OR_PROTOCOL_ERROR',loginAttempts:loginSubmitted?1:0,passwordSaved:false,cookiesSaved:false,authorizationSaved:false,trace:[...trace,...lab.trace]};process.exitCode=2;}
finally{lab.clear();jars.clear();}
if(evidenceOutput)atomic(evidenceOutput,report);
console.log(JSON.stringify(report,null,2));
