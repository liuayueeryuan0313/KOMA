/* Paper cat: a small desktop glance with separate head, body, face and tail layers. */
(()=>{
 'use strict';
 const desktop=window.matchMedia('(min-width: 601px) and (hover: hover) and (pointer: fine)');
 const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
 const clamp=value=>Math.max(-1,Math.min(1,value));
 const selector='svg.paper-cat[data-cat-follow]';
 let cats=[],template=null,frame=0,lastTime=0,point=null,dirty=true,enabled=false;

 function pose(cat,x,y){
  const values={
   'cat-x':[x*1.6,'px'],'cat-y':[-Math.abs(x)*.6,'px'],
   'body-x':[x*1.8,'px'],'body-y':[y*.8,'px'],'body-turn':[x*1.8,'deg'],
   'head-x':[x*4.5,'px'],'head-y':[y*3,'px'],'head-turn':[x*6,'deg'],'head-skew':[-x*1.6,'deg'],
   'face-x':[x*1.4,'px'],'face-y':[y*.8,'px'],
   'eye-x':[x*2.8,'px'],'eye-y':[y*1.8,'px'],'tail-turn':[-x*5,'deg']
  };
  for(const [name,[value,unit]] of Object.entries(values))cat.node.style.setProperty('--'+name,value.toFixed(3)+unit);
 }
 function collect(){
  const previous=new Map(cats.map(cat=>[cat.node,cat]));
  cats=[...document.querySelectorAll(selector)].map(node=>previous.get(node)||{node,x:0,y:0,rect:null});
  dirty=true;
 }
 async function hydrate(){
  if(!enabled)return;
  const images=[...document.querySelectorAll('img[data-cat-follow]')];
  if(images.length){
   try{
    if(!template)template=fetch('/mascot.svg',{credentials:'same-origin'}).then(response=>{
     if(!response.ok)throw Error('mascot unavailable');return response.text();
    }).then(source=>{
     const svg=new DOMParser().parseFromString(source,'image/svg+xml').documentElement;
     if(svg.localName!=='svg'||!svg.querySelector('.cat-head-follow'))throw Error('mascot invalid');
     return svg;
    });
    const original=await template;
    if(!enabled)return;
    for(const image of images){
     if(!image.isConnected)continue;
     const svg=document.importNode(original,true);
     svg.classList.add('paper-cat',...image.classList);
     svg.setAttribute('data-cat-follow','');svg.setAttribute('role','img');
     svg.setAttribute('aria-label',image.alt||'抱着课本的纸猫');
     svg.removeAttribute('aria-labelledby');svg.querySelector('title')?.remove();
     image.replaceWith(svg);
    }
   }catch{template=null;/* Keep the original SVG image if enhancement fails. */}
  }
  if(!enabled)return;
  collect();schedule();
 }
 function schedule(){
  if(enabled&&!document.hidden&&!frame&&cats.length)frame=window.requestAnimationFrame(tick);
 }
 function tick(time){
  frame=0;
  if(!enabled||document.hidden)return;
  const alpha=1-Math.exp(-Math.min(lastTime?time-lastTime:16,64)/85);
  lastTime=time;
  let moving=false;
  cats=cats.filter(cat=>cat.node.isConnected);
  for(const cat of cats){
   if(dirty||!cat.rect)cat.rect=cat.node.getBoundingClientRect();
   const rect=cat.rect,visible=rect.width>0&&rect.height>0&&rect.bottom>0&&rect.top<window.innerHeight;
   const x=point&&visible?clamp((point.x-rect.left-rect.width*.52)/Math.max(rect.width*.9,240)):0;
   const y=point&&visible?clamp((point.y-rect.top-rect.height*.43)/Math.max(rect.height*.8,220)):0;
   cat.x+=(x-cat.x)*alpha;cat.y+=(y-cat.y)*alpha;
   const unsettled=Math.abs(x-cat.x)+Math.abs(y-cat.y)>.002;
   if(!unsettled){cat.x=x;cat.y=y;}
   if(visible)pose(cat,cat.x,cat.y);
   moving=unsettled||moving;
  }
  dirty=false;
  if(moving)schedule();else lastTime=0;
 }
 function neutral(immediate=false){
  point=null;
  if(immediate){
   window.cancelAnimationFrame(frame);frame=0;lastTime=0;
   for(const cat of cats){cat.x=cat.y=0;pose(cat,0,0);}
  }else schedule();
 }
 function configure(){
  enabled=desktop.matches&&!reduced.matches;
  if(enabled)hydrate();else neutral(true);
 }
 document.addEventListener('pointermove',event=>{
  if(!enabled||event.pointerType==='touch')return;
  point={x:event.clientX,y:event.clientY};schedule();
 },{passive:true});
 document.addEventListener('pointerout',event=>{if(!event.relatedTarget)neutral();},{passive:true});
 document.addEventListener('visibilitychange',()=>{if(document.hidden)neutral(true);else{dirty=true;schedule();}});
 document.addEventListener('koma:render',()=>{if(enabled)hydrate();});
 window.addEventListener('blur',()=>neutral());
 window.addEventListener('scroll',()=>{dirty=true;schedule();},{passive:true,capture:true});
 window.addEventListener('resize',()=>{dirty=true;schedule();},{passive:true});
 desktop.addEventListener('change',configure);reduced.addEventListener('change',configure);
 configure();
})();
