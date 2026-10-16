import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

function tracker({desktop=true,reduced=false}={}){
 const events=new Map(),windowEvents=new Map(),frames=new Map(),queries=[];
 let nextFrame=0,time=0;
 const media=(matches)=>({matches,addEventListener(event,callback){this.change=callback;}});
 const desktopMedia=media(desktop),reducedMedia=media(reduced);
 const makeCat=()=>({isConnected:true,rect:{left:200,top:200,width:290,height:272,bottom:472},values:new Map(),style:{setProperty(name,value){this.owner.values.set(name,value);}},getBoundingClientRect(){return this.rect;}});
 let cat=makeCat();cat.style.owner=cat;
 const document={hidden:false,querySelectorAll(selector){queries.push(selector);return selector.startsWith('img')?[]:[cat];},addEventListener(name,callback){events.set(name,callback);}};
 const window={innerHeight:900,matchMedia:query=>query.includes('reduced')?reducedMedia:desktopMedia,requestAnimationFrame(callback){const id=++nextFrame;frames.set(id,callback);return id;},cancelAnimationFrame(id){frames.delete(id);},addEventListener(name,callback){windowEvents.set(name,callback);}};
 vm.runInNewContext(readFileSync(new URL('../web/cat-pointer.js',import.meta.url),'utf8'),{window,document,fetch:()=>{throw Error('unexpected fetch');}});
 function settle(){for(let i=0;frames.size&&i<200;i++){const scheduled=[...frames.values()];frames.clear();time+=16;scheduled.forEach(callback=>callback(time));}assert.equal(frames.size,0,'animation must stop after settling');}
 return {events,windowEvents,desktopMedia,reducedMedia,document,queries,frames,settle,get cat(){return cat;},replace(){cat.isConnected=false;cat=makeCat();cat.style.owner=cat;return cat;},move(x,y,type='mouse'){events.get('pointermove')({clientX:x,clientY:y,pointerType:type});}};
}

test('desktop glance moves head, body, book and tail as well as eyes, with bounded angles',()=>{
 const app=tracker();app.settle();app.move(3000,-1000);app.settle();
 const values=app.cat.values;
 assert.ok(parseFloat(values.get('--head-x'))>0);
 assert.ok(parseFloat(values.get('--body-x'))>0);
 assert.ok(parseFloat(values.get('--eye-x'))>0);
 assert.ok(parseFloat(values.get('--tail-turn'))<0);
 assert.equal(values.get('--head-turn'),'6.000deg');
 assert.equal(values.get('--body-turn'),'1.800deg');
 app.move(-3000,3000);app.settle();
 assert.equal(values.get('--head-turn'),'-6.000deg');
 assert.equal(values.get('--head-y'),'3.000px');
});

test('pointer leaving and hidden page return all layers to neutral without idle frames',()=>{
 const app=tracker();app.move(1000,0);app.settle();
 app.events.get('pointerout')({relatedTarget:null});app.settle();
 assert.equal(app.cat.values.get('--head-turn'),'0.000deg');
 app.move(1000,0);app.document.hidden=true;app.events.get('visibilitychange')();
 assert.equal(app.frames.size,0);assert.equal(app.cat.values.get('--body-turn'),'0.000deg');
});

test('mobile, coarse input and reduced motion never start tracking',()=>{
 for(const options of [{desktop:false},{reduced:true}]){
  const app=tracker(options);app.move(1000,0);assert.equal(app.frames.size,0);assert.equal(app.queries.length,0);
 }
 const app=tracker();app.settle();app.move(1000,0,'touch');assert.equal(app.frames.size,0);
 app.move(1000,0);app.reducedMedia.matches=true;app.reducedMedia.change();
 assert.equal(app.frames.size,0);assert.equal(app.cat.values.get('--head-x'),'0.000px');
});

test('scroll invalidates positions and page re-render tracks the replacement cat',()=>{
 const app=tracker();app.move(600,300);app.settle();
 assert.ok(parseFloat(app.cat.values.get('--head-x'))>0);
 app.cat.rect={...app.cat.rect,left:800};app.windowEvents.get('scroll')();app.settle();
 assert.ok(parseFloat(app.cat.values.get('--head-x'))<0);
 const old=app.cat,replacement=app.replace();app.events.get('koma:render')();app.settle();
 assert.ok(parseFloat(replacement.values.get('--head-x'))>0);assert.equal(old.isConnected,false);
});
