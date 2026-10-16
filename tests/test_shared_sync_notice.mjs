import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
function notice(overrides={},plans={}){
 const context=vm.createContext({document:{querySelector:()=>({}),querySelectorAll:()=>[],addEventListener(){}},Intl,setInterval(){},setTimeout(){},clearTimeout(){}});
 vm.runInContext(readFileSync(new URL('../web/app.js',import.meta.url),'utf8').replace(/^boot\(\);\s*$/m,''),context);
 const settings={mode:'app',has_app_token:true,app_token_invalid:false,...overrides};
 const states={teaching:{enabled:true,interval_minutes:60},lab:{enabled:true,interval_minutes:60},...plans};
 vm.runInContext(`data=${JSON.stringify({settings,states})}`,context);
 return vm.runInContext('sharedSyncNotice()',context);
}
test('eligible mode clearly explains one CAS login, token reuse and paired manual sync',()=>{const html=notice();assert.match(html,/已启用两份课表合并同步/);assert.match(html,/复用 App token/);assert.match(html,/仅登录一次/);assert.match(html,/点击任一同步按钮/);assert.match(html,/role="status"/);assert.notEqual(notice({mode:'auto'}),'');});
test('notice disappears for other sources, unequal intervals, disabled or invalid-token plans',()=>{assert.equal(notice({mode:'jw'}),'');assert.equal(notice({has_app_token:false}),'');assert.equal(notice({app_token_invalid:true}),'');assert.equal(notice({}, {lab:{enabled:true,interval_minutes:30}}),'');assert.equal(notice({}, {lab:{enabled:false,interval_minutes:60}}),'');});
