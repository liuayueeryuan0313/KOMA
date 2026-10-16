import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

function app(){
 const nodes=new Map(),handlers={},calls=[];
 const node=selector=>{if(!nodes.has(selector))nodes.set(selector,{innerHTML:'',value:'',disabled:false,showModal(){this.open=true;},close(){this.open=false;},setAttribute(){}});return nodes.get(selector);};
 const context=vm.createContext({document:{querySelector:node,querySelectorAll:()=>[],addEventListener:(event,handler)=>handlers[event]=handler},Intl,setInterval:()=>{},setTimeout:()=>{},clearTimeout:()=>{},FormData:class{constructor(form){return form.entries;}}});
 vm.runInContext(readFileSync(new URL('../web/app.js',import.meta.url),'utf8').replace(/^boot\(\);\s*$/m,''),context);
 context.calls=calls;
 vm.runInContext(`bootstrap={recovery_questions:[{id:'first_pet',label:'第一只宠物？'},{id:'first_school',label:'第一所学校？'}]};api=async(path,options)=>{calls.push({path,options});return {csrf:'test-csrf'};};`,context);
 const form=(id,values={},mode='register')=>({id,entries:Object.entries(values),dataset:{mode},querySelector:node,classList:{contains:name=>name==='recovery-form'},checkValidity:()=>true,reset(){this.wasReset=true;}});
 return {context,node,handlers,calls,form};
}

test('registration opens optional security-question dialog before sending credentials',async()=>{
 const {context,node,handlers,calls,form}=app();
 vm.runInContext('authMode="register"',context);
 await handlers.submit({target:form('auth-form',{username:'new-user',password:'Test-password-42',consent:'on'}),preventDefault(){}});
 assert.equal(calls.length,0);
 assert.match(node('#modal-content').innerHTML,/保存密保并创建账户/);
 assert.match(node('#modal-content').innerHTML,/稍后设置并创建账户/);
 assert.equal(node('#modal').open,true);
});

test('existing-account dialog requires current password and never pre-fills answers',()=>{
 const {context,node}=app();vm.runInContext('recoverySetup("settings")',context);
 const html=node('#modal-content').innerHTML;
 assert.match(html,/name="current_password"/);assert.doesNotMatch(html,/稍后设置/);
 assert.match(html,/name="answer0" type="password"/);assert.doesNotMatch(html,/name="answer0"[^>]+value=/);
 assert.throws(()=>vm.runInContext('recoveryEntries({question0:"first_pet",question1:"first_pet"})',context),/不同/);
});

test('skipping recovery creates only one account request when clicked twice',async()=>{
 const {context,node,calls}=app();
 Object.assign(node('#auth-form'),{entries:Object.entries({username:'new-user',password:'Test-password-42',consent:'on'}),checkValidity:()=>true,reset(){}});
 vm.runInContext('refresh=async()=>{};showWorkspace=()=>{};',context);
 // Use a controlled pending response rather than relying on test timers.
 context.pending=new Promise(resolve=>context.release=resolve);
 vm.runInContext('api=async(path,options)=>{calls.push({path,options});await pending;return {csrf:"test"};}',context);
 const first=vm.runInContext('finishRegistration()',context);
 await vm.runInContext('finishRegistration()',context);
 assert.equal(calls.length,1);
 context.release();await first;
 assert.equal(calls[0].path,'/api/register');
 assert.equal(JSON.parse(calls[0].options.body).recovery,null);
});

test('password confirmation mismatch stays in dialog without issuing reset request',async()=>{
 const {handlers,node,calls,form}=app();
 await handlers.submit({target:form('recovery-reset-form',{username:'tester',new_password:'New-password-42',confirm_password:'different'}),preventDefault(){}});
 assert.equal(calls.length,0);assert.match(node('#recovery-error').textContent,/不一致/);
 assert.equal(node('[type=submit]').disabled,false);
});

test('reset sends both answers, clears stale login password, and offers fresh login',async()=>{
 const {handlers,node,calls,form}=app();node('#auth-form [name=password]').value='old-password';
 await handlers.submit({target:form('recovery-reset-form',{username:'tester',question0:'first_pet',answer0:'My Pet',question1:'first_school',answer1:'My School',new_password:'New-password-42',confirm_password:'New-password-42'}),preventDefault(){}});
 assert.equal(calls[0].path,'/api/recovery/reset');
 const body=JSON.parse(calls[0].options.body);
 assert.equal(body.answers.length,2);assert.equal(body.new_password,'New-password-42');assert.ok(!('confirm_password' in body));
 assert.equal(node('#auth-form [name=password]').value,'');assert.match(node('#modal-content').innerHTML,/返回登录/);
});
