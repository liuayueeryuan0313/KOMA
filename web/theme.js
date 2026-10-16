/* Apply before CSS paints; the choice is local to this browser, including before sign-in. */
(() => {
 'use strict';
 const modes=['auto','dark','light'],key='koma.theme',root=document.documentElement;
 const system=window.matchMedia('(prefers-color-scheme: dark)');
 let mode='auto';
 try { const saved=localStorage.getItem(key);if(modes.includes(saved))mode=saved; } catch {}
 function apply(){
  root.dataset.theme=mode==='auto'?(system.matches?'dark':'light'):mode;
  root.dataset.themeMode=mode;
  for(const group of document.querySelectorAll('[data-theme-switch]')){
   group.style.setProperty('--theme-index',modes.indexOf(mode));
   for(const button of group.querySelectorAll('[data-theme-mode]')){
    const selected=button.dataset.themeMode===mode;
    button.setAttribute('aria-checked',String(selected));button.tabIndex=selected?0:-1;
   }
  }
 }
 function select(value){
  if(!modes.includes(value))return;
  mode=value;try{localStorage.setItem(key,mode);}catch{}apply();
 }
 apply();
 system.addEventListener('change',()=>{if(mode==='auto')apply();});
 window.addEventListener('storage',event=>{if(event.key===key){mode=modes.includes(event.newValue)?event.newValue:'auto';apply();}});
 document.addEventListener('DOMContentLoaded',()=>{
  apply();
  document.addEventListener('click',event=>{
   const button=event.target.closest('button[data-theme-mode]');if(button)select(button.dataset.themeMode);
  });
  document.addEventListener('keydown',event=>{
   const button=event.target.closest('button[data-theme-mode]');if(!button)return;
   const moves={ArrowRight:1,ArrowDown:1,ArrowLeft:-1,ArrowUp:-1};
   if(!(event.key in moves)&&!['Home','End'].includes(event.key))return;
   event.preventDefault();
   const index=event.key==='Home'?0:event.key==='End'?2:(modes.indexOf(mode)+moves[event.key]+3)%3;
   select(modes[index]);button.closest('[data-theme-switch]').querySelectorAll('[data-theme-mode]')[index].focus();
  });
 });
})();
