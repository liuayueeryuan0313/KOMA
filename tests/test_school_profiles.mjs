import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createCipheriv,createDecipheriv,generateKeyPairSync,privateDecrypt,constants} from 'node:crypto';
import {schoolProfile,DEFAULT_SCHOOL,endpoint,requireEndpoints,schoolFetch,jwProfile} from '../adapters/scripts/school-profile.mjs';
import {validateProfile} from '../adapters/scripts/jw-core.mjs';
import {LabClient} from '../adapters/scripts/lab-core.mjs';
import {keyExchange,login,h5Login} from '../adapters/scripts/campus-auth.mjs';
const custom=(extra={})=>schoolProfile({school_profile:'custom',school_custom:{name:'测试学校',jw_base:'https://jw.example.edu.cn/newjw',...extra}});
test('legacy school defaults remain identical',()=>{const p=schoolProfile();assert.equal(p.custom,false);for(const [key,value] of Object.entries(DEFAULT_SCHOOL))assert.equal(p[key],value);});
test('unused custom platforms never fall back to SDUT',()=>{const p=custom();assert.equal(p.app_h5_base,'');assert.equal(p.lab_base,'');assert.throws(()=>requireEndpoints(p,['app_h5_base']),/SCHOOL_ENDPOINT_MISSING/);});
test('full base path and nonstandard port survive endpoint joining',()=>{assert.equal(endpoint('https://jw.example.edu.cn:8443/backend/','/login'),'https://jw.example.edu.cn:8443/backend/login');});
test('JW profile uses the selected origin, context and campus',()=>{const p=jwProfile(JSON.parse(readFileSync(new URL('../adapters/jw-request.json',import.meta.url),'utf8')),custom({jw_campus_id:'2'}));validateProfile(p);assert.equal(p.origin,'https://jw.example.edu.cn');assert.equal(p.path,'/newjw/kbcx/xskbcx_cxXsgrkb.html');assert.equal(p.periodsForm.xqh_id,'2');p.path='/other/path';assert.throws(()=>validateProfile(p));});
test('root-deployed JW profile also validates',()=>{validateProfile(jwProfile(JSON.parse(readFileSync(new URL('../adapters/jw-request.json',import.meta.url),'utf8')),custom({jw_base:'https://jw.example.edu.cn'})));});
test('rejects URLs carrying credentials or private literal hosts',()=>{for(const url of ['https://a:b@jw.example.edu.cn','https://localhost','https://127.0.0.1','https://169.254.169.254','https://jw.example.edu.cn?x=y'])assert.throws(()=>custom({jw_base:url}));});
test('request to an unrelated authentication origin is blocked before fetch',async()=>{let calls=0;const transport=schoolFetch(custom(),['https://jw.example.edu.cn'],()=>{calls++;},async()=>[{address:'93.184.216.34',family:4}]);await assert.rejects(transport('https://elsewhere.example.edu.cn'),/UNEXPECTED_AUTH_ORIGIN/);assert.equal(calls,0);});
test('DNS answers pointing to LAN are blocked before fetch',async()=>{let calls=0;const transport=schoolFetch(custom(),['https://jw.example.edu.cn'],()=>{calls++;},async()=>[{address:'192.168.1.10',family:4}]);await assert.rejects(transport('https://jw.example.edu.cn'),/SCHOOL_ADDRESS_NOT_PUBLIC/);assert.equal(calls,0);});
test('transport disables implicit redirects and checks DNS once per job',async()=>{let lookups=0;const calls=[];const transport=schoolFetch(custom(),['https://jw.example.edu.cn'],async(url,options)=>{calls.push(options);return new Response('{}');},async()=>{lookups++;return [{address:'93.184.216.34',family:4}];});await transport('https://jw.example.edu.cn/a');await transport('https://jw.example.edu.cn/b');assert.equal(lookups,1);assert.equal(calls[0].redirect,'manual');});
test('lab client preserves custom API prefix and generates fresh signatures',async()=>{const calls=[];const client=new LabClient(async(url,options)=>{calls.push({url:String(url),...options});return new Response(JSON.stringify({code:200}),{headers:{'Set-Cookie':'lab-session=synthetic; Path=/'}});},{base:'https://lab.example.edu.cn/labapi'});client.authorization='synthetic-test-authorization';await client.post('/config/sys/cas/login');await client.post('/teach/teach/stuTime/listStuTimePage',{data:{yearterm:'2026-2027-1',currpage:1,pagesize:15}});assert.equal(calls[0].url,'https://lab.example.edu.cn/labapi/config/sys/cas/login');assert.equal(calls[1].headers.Origin,'https://lab.example.edu.cn');assert.equal(calls[1].headers.Authorization,'synthetic-test-authorization');assert.notEqual(calls[0].headers.nonce,calls[1].headers.nonce);assert.match(calls[1].headers.signature,/^[a-f0-9]{128}$/);});
test('App key exchange, login and token exchange use custom school parameters',async()=>{
 const p=custom({app_origin:'https://app.example.edu.cn:8443',app_h5_base:'https://schedule.example.edu.cn/course/api',app_school_id:'TEST',app_yyid:'765432',app_exchange_path:'/sys/security/login_otherapp'});
 const pair=generateKeyPairSync('rsa',{modulusLength:2048}),pub=pair.publicKey.export({type:'spki',format:'der'}).toString('base64');
 let aes;const calls=[];
 const enc=(value)=>{const cipher=createCipheriv('aes-128-ecb',Buffer.from(aes,'base64'),null);return Buffer.concat([cipher.update(value,'utf8'),cipher.final()]).toString('base64');};
 const dec=(value)=>{const cipher=createDecipheriv('aes-128-ecb',Buffer.from(aes,'base64'),null);return Buffer.concat([cipher.update(Buffer.from(value,'base64')),cipher.final()]).toString('utf8');};
 const fake=async(url,options)=>{calls.push({url:String(url),options});let payload;
  if(options.headers['Asym-Key']==='public')payload={code:0,data:pub};
  else if(options.headers['Asym-Key']==='private'){const block=privateDecrypt({key:pair.privateKey,padding:constants.RSA_NO_PADDING},Buffer.from(options.body,'base64'));aes=JSON.parse(block.subarray(block.indexOf(0,2)+1).toString()).sk;payload={code:0,data:enc('synthetic-only-code')};}
  else if(String(url).endsWith('/open/auth/login')){const body=JSON.parse(dec(options.body));assert.equal(body.schoolId,'TEST');assert.equal(body.passw,'Synthetic-app-password');payload={code:0,data:enc(JSON.stringify({session_key:'synthetic-session',schoolId:'returned-school',userId:'25110000000'}))};}
  else {assert.equal(JSON.parse(options.body).yyid,'765432');payload={code:200,data:{tokenValue:'synthetic-h5-token'}};}
  return new Response(JSON.stringify(payload));
 };
 const keys=await keyExchange(p,fake);const session=await login(keys,'25110000000','Synthetic-app-password',fake);assert.equal(await h5Login(session,fake),'synthetic-h5-token');
 assert.equal(calls[0].url,'https://app.example.edu.cn:8443/mobileapi_ydxy/open/security/asym/key');assert.equal(calls[2].url,'https://app.example.edu.cn:8443/mobileapi_ydxy/open/auth/login');assert.equal(calls[3].url,'https://schedule.example.edu.cn/course/api/sys/security/login_otherapp');
});
