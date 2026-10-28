import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

function fixture(){
 const nodes=new Map(),listeners={};
 const node=selector=>{if(!nodes.has(selector))nodes.set(selector,{innerHTML:'',value:'',addEventListener(type,fn){this[type]=fn;},remove(){nodes.delete(selector);},showModal(){},close(){this.closeEvent?.();}});return nodes.get(selector);};
 const context=vm.createContext({document:{querySelector:node,querySelectorAll:()=>[],addEventListener(type,fn){listeners[type]=fn;}},Intl,setTimeout:()=>{},clearTimeout:()=>{},setInterval:()=>{},requests:[]});
 const source=readFileSync(new URL('../web/app.js',import.meta.url),'utf8').replace(/^boot\(\);\s*$/m,'');
 vm.runInContext(source,context);
 vm.runInContext(`data={user:{id:'alice'},calendars:{},links:{}};toast=()=>{};api=async(path,options)=>{requests.push({path,options});return {token:'kw_test-secret',createdAt:'2026-10-28T00:00:00Z'};}`,context);
 return {node,context,listeners};
}

test('Token management stays in the calendar subscription section and handles pending/error status',()=>{
 const {context}=fixture();
 const html=vm.runInContext('subscriptions()',context);
 assert.match(html,/ics-panel[\s\S]*widget-token-panel[\s\S]*小组件 Token/);
 assert.match(html,/widget-generate" disabled/);
 vm.runInContext("widgetError='服务暂不可用'",context);
 assert.match(vm.runInContext('widgetTokenCard()',context),/widget-retry/);
});

test('generation uses the management endpoint, shows the secret once and clears it on close',async()=>{
 const {node,context,listeners}=fixture();
 await vm.runInContext("changeWidgetToken('rotate')",context);
 assert.equal(context.requests[0].path,'/api/widget/token');
 assert.deepEqual(JSON.parse(context.requests[0].options.body),{action:'rotate'});
 assert.equal(node('#widget-token-secret').value,'kw_test-secret');
 assert.doesNotMatch(vm.runInContext('widgetTokenCard()',context),/kw_test-secret/);
 assert.equal(vm.runInContext('JSON.stringify(widgetStatus)',context).includes('kw_test-secret'),false);
 listeners.close({target:{id:'modal'}});
 assert.equal(node('#widget-token-secret').value,'');
 await vm.runInContext("changeWidgetToken('revoke')",context);
 assert.equal(vm.runInContext('widgetStatus.configured',context),false);
});

test('an in-flight response cannot expose the previous account token after account changes',async()=>{
 const {node,context}=fixture();
 vm.runInContext('api=()=>new Promise(resolve=>globalThis.finish=resolve)',context);
 const pending=vm.runInContext("changeWidgetToken('rotate')",context);
 vm.runInContext("data={user:{id:'bob'}};finish({token:'kw_alice-private',createdAt:'2026-10-28T00:00:00Z'})",context);
 await pending;
 assert.equal(node('#widget-token-secret').value,'');
 assert.equal(vm.runInContext('widgetStatus',context),null);
});
