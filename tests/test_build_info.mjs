import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

function metadata(){
 const versions=[{},{}],dates=[{}],rows=[{hidden:true}];
 const groups={'[data-app-version]':versions,'[data-build-date]':dates,'.auth-build-info':rows};
 const context=vm.createContext({document:{querySelector:()=>({}),querySelectorAll:selector=>groups[selector]||[],addEventListener:()=>{}},Intl,setInterval:()=>{},setTimeout:()=>{},clearTimeout:()=>{}});
 vm.runInContext(readFileSync(new URL('../web/app.js',import.meta.url),'utf8').replace(/^boot\(\);\s*$/m,''),context);
 return {context,versions,dates,rows};
}

test('sign-in and workspace receive the same version before login',()=>{
 const {context,versions,dates,rows}=metadata();
 vm.runInContext('renderAppMetadata({version:"0.4.0",build_date:"2026-10-15T20:00:00Z"})',context);
 assert.deepEqual(versions.map(node=>node.textContent),['v0.4.0','v0.4.0']);
 assert.equal(dates[0].textContent,'构建于 2026-10-16');
 assert.match(dates[0].title,/北京时间/);assert.equal(rows[0].hidden,false);
});

test('source preview never labels launch time or malformed values as a build date',()=>{
 const {context,dates}=metadata();
 for(const value of ['null','""','"not a date"','"<img src=x>"']){
  vm.runInContext(`renderAppMetadata({version:"0.4.0",build_date:${value}})`,context);
  assert.equal(dates[0].textContent,'构建日期：待构建（开发预览）');
 }
});
