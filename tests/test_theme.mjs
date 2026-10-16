import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../web/theme.js',import.meta.url),'utf8');
function start(saved=null,dark=false,blocked=false){
 const listeners={},windowListeners={},systemListeners={},writes=[];
 const group=()=>{const g={style:{setProperty(k,v){this[k]=v;}}};g.buttons=['auto','dark','light'].map(mode=>({dataset:{themeMode:mode},setAttribute(k,v){this[k]=v;},closest:selector=>selector==='button[data-theme-mode]'?g.buttons.find(b=>b.dataset.themeMode===mode):g,focus(){this.focused=true;}}));g.querySelectorAll=()=>g.buttons;return g;};
 const groups=[group(),group()],root={dataset:{}},system={matches:dark,addEventListener:(k,fn)=>systemListeners[k]=fn};
 const context=vm.createContext({document:{documentElement:root,querySelectorAll:()=>groups,addEventListener:(k,fn)=>listeners[k]=fn},window:{matchMedia:()=>system,addEventListener:(k,fn)=>windowListeners[k]=fn},localStorage:{getItem(){if(blocked)throw Error('blocked');return saved;},setItem(k,v){if(blocked)throw Error('blocked');writes.push([k,v]);}}});
 vm.runInContext(source,context);listeners.DOMContentLoaded();
 return {root,groups,system,writes,click:mode=>listeners.click({target:{closest:()=>groups[0].buttons.find(b=>b.dataset.themeMode===mode)}}),os:dark=>{system.matches=dark;systemListeners.change();},storage:mode=>windowListeners.storage({key:'koma.theme',newValue:mode}),key:key=>listeners.keydown({target:groups[0].buttons.find(b=>b['aria-checked']==='true'),key,preventDefault(){}})};
}
test('automatic follows OS before first paint and on live OS changes',()=>{const t=start(null,true);assert.equal(t.root.dataset.theme,'dark');t.os(false);assert.equal(t.root.dataset.theme,'light');assert.equal(t.root.dataset.themeMode,'auto');});
test('explicit choice persists, syncs both switches, and ignores OS until auto',()=>{const t=start('light',true);assert.equal(t.root.dataset.theme,'light');t.click('dark');t.os(false);assert.equal(t.root.dataset.theme,'dark');for(const g of t.groups){assert.equal(g.buttons[1]['aria-checked'],'true');assert.equal(g.buttons[1].tabIndex,0);assert.equal(g.style['--theme-index'],1);}assert.deepEqual(t.writes,[['koma.theme','dark']]);t.click('auto');assert.equal(t.root.dataset.theme,'light');});
test('blocked storage and invalid stored values safely default to system',()=>{const t=start('bad',true,true);assert.equal(t.root.dataset.theme,'dark');t.click('light');assert.equal(t.root.dataset.theme,'light');assert.equal(start('unknown',false).root.dataset.themeMode,'auto');});
test('keyboard slides between modes and cross-tab changes stay synchronized',()=>{const t=start();t.key('ArrowRight');assert.equal(t.root.dataset.themeMode,'dark');assert.equal(t.groups[0].buttons[1].focused,true);t.key('End');assert.equal(t.root.dataset.theme,'light');t.key('Home');assert.equal(t.root.dataset.themeMode,'auto');t.storage('dark');assert.equal(t.root.dataset.theme,'dark');t.storage(null);assert.equal(t.root.dataset.themeMode,'auto');});
