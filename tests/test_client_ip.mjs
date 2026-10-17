import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

function display(intl=Intl){
 const nodes=new Map();
 const node=selector=>{if(!nodes.has(selector))nodes.set(selector,{setAttribute(name,value){this[name]=value;},removeAttribute(name){delete this[name];}});return nodes.get(selector);};
 const context=vm.createContext({document:{querySelector:node,querySelectorAll:()=>[],addEventListener:()=>{}},Intl:intl,setInterval:()=>{},setTimeout:()=>{},clearTimeout:()=>{}});
 const source=readFileSync(new URL('../web/app.js',import.meta.url),'utf8').replace(/^boot\(\);\s*$/m,'');
 vm.runInContext(source,context);
 return {node,context};
}

test('country names use Chinese and flags, with special codes omitted',()=>{
 const {context}=display();
 for(const [code,label] of [['CN','🇨🇳 中国'],['SG','🇸🇬 新加坡'],['JP','🇯🇵 日本'],['US','🇺🇸 美国'],['XX',''],['T1',''],['',''],['<img>','']]){
  assert.equal(vm.runInContext(`formatCountry(${JSON.stringify(code)})`,context),label);
 }
 assert.equal(vm.runInContext('formatCountry("CN")',display({}).context),'🇨🇳 CN');
});

test('both views show full IPv6 in text and tooltip, with green protocol class',()=>{
 const {node,context}=display();
 vm.runInContext('renderClientIp({client_ip:"2001:db8:1234:5678:90ab:cdef:1234:5678",ip_proto:"IPv6",country:"CN"})',context);
 for(const selector of ['#auth-ip-badge','#sidebar-ip-badge','#auth-mobile-ip-badge','#workspace-mobile-ip-badge']){
  const badge=node(selector);
  assert.equal(badge.hidden,false);
  assert.match(badge.innerHTML,/tag-v6/);
  assert.match(badge.innerHTML,/2001:db8:1234:5678:90ab:cdef:1234:5678/);
  assert.match(badge.title,/🇨🇳 中国/);
  assert.equal(badge.href,'https://ip.net.coffee/ip/2001%3Adb8%3A1234%3A5678%3A90ab%3Acdef%3A1234%3A5678');
  assert.equal(badge.target,'_blank');
  assert.equal(badge.rel,'noopener noreferrer');
 }
 assert.equal(node('#auth-ip-badge').innerHTML,node('#sidebar-ip-badge').innerHTML);
});

test('IPv4 and missing location work, and empty IP hides stale badges',()=>{
 const {node,context}=display();
 vm.runInContext('renderClientIp({client_ip:"192.0.2.1",country:"XX"})',context);
 assert.match(node('#auth-ip-badge').innerHTML,/tag-v4/);
 assert.doesNotMatch(node('#auth-ip-badge').innerHTML,/ip-country/);
 assert.equal(node('#auth-ip-badge').href,'https://ip.net.coffee/ip/192.0.2.1');
 vm.runInContext('renderClientIp({})',context);
 assert.equal(node('#auth-ip-badge').hidden,true);
 assert.equal(node('#sidebar-ip-badge').innerHTML,'');
 assert.equal(node('#auth-ip-badge').href,undefined);
});

test('untrusted bootstrap strings cannot insert markup or protocol attributes',()=>{
 const {node,context}=display();
 vm.runInContext('renderClientIp({client_ip:"<img onerror=alert(1)>",ip_proto:"<svg>",country:"<img>"})',context);
 const html=node('#auth-ip-badge').innerHTML;
 assert.match(html,/&lt;img/);
 assert.doesNotMatch(html,/<img|<svg/);
});
