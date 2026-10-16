import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

function editor(){
 const nodes=new Map(),handlers={};
 const node=selector=>{if(!nodes.has(selector))nodes.set(selector,{innerHTML:'',showModal(){this.open=true;},close(){this.open=false;}});return nodes.get(selector);};
 const context=vm.createContext({document:{querySelector:node,querySelectorAll:()=>[],addEventListener:(event,handler)=>handlers[event]=handler},Intl,Date,setInterval:()=>{},setTimeout:()=>{},clearTimeout:()=>{}});
 const source=readFileSync(new URL('../web/app.js',import.meta.url),'utf8').replace(/boot\(\);\s*$/,'');
 vm.runInContext(source,context);
 vm.runInContext(`data={settings:{config:{week1_monday:'2026-08-31',maxWeekNumber:20,periods:{'1':['08:00','08:45'],'2':['08:55','09:40']}}},occurrences:[]};week=3;`,context);
 return {context,handlers,node};
}

test('new lesson opens a blank editor at the selected teaching week',()=>{
 const {context,node}=editor();
 vm.runInContext('lessonEditor()',context);
 const html=node('#modal-content').innerHTML;
 assert.match(html,/手动新建课程/);
 assert.match(html,/<option value="3" selected>3<\/option>/);
 assert.match(html,/id="lesson-lab-fields" hidden disabled/);
 assert.equal(node('#modal').open,true);
});

test('editing pre-fills one occurrence and escapes school-provided text',()=>{
 const {context,node}=editor();
 vm.runInContext(`lessonEditor({kind:'lab',occurrenceId:'abc',name:'<img onerror="x">',week:5,weekday:2,startPeriod:1,endPeriod:2,projectName:'实验项目'})`,context);
 const html=node('#modal-content').innerHTML;
 assert.match(html,/data-id="abc"/);
 assert.match(html,/<select name="kind" disabled>/);
 assert.match(html,/&lt;img onerror=&quot;x&quot;&gt;/);
 assert.doesNotMatch(html,/<img onerror/);
 assert.match(html,/value="实验项目"/);
});

test('switching new lesson kind toggles laboratory fields',async()=>{
 const {handlers,node}=editor();
 await handlers.change({target:{form:{id:'lesson-form'},name:'kind',value:'lab'}});
 assert.equal(node('#lesson-lab-fields').disabled,false);
 assert.equal(node('#lesson-lab-fields').hidden,false);
 await handlers.change({target:{form:{id:'lesson-form'},name:'kind',value:'teaching'}});
 assert.equal(node('#lesson-lab-fields').disabled,true);
});


test('override comparison exposes school restore and conflict acknowledgement',()=>{
 const {context,node}=editor();
 vm.runInContext(`lessonEditor({kind:'teaching',origin:'override',occurrenceId:'abc',revision:'rev1',name:'我的课程',week:3,weekday:1,startPeriod:1,endPeriod:2,date:'2026-09-14',startLocal:'2026-09-14T08:00:00',endLocal:'2026-09-14T09:40:00',location:'我的教室',conflictFields:['location'],schoolArrangement:{name:'学校课程',date:'2026-09-14',startLocal:'2026-09-14T08:00:00',endLocal:'2026-09-14T09:40:00',location:'学校教室'}})`,context);
 const html=node('#modal-content').innerHTML;
 assert.match(html,/学校最新安排/);
 assert.match(html,/我的教室/);
 assert.match(html,/学校教室/);
 assert.match(html,/data-action="restore-lesson"/);
 assert.match(html,/data-action="keep-lesson"/);
 assert.match(html,/data-revision="rev1"/);
});
