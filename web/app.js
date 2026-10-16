'use strict';
const $=(selector,root=document)=>root.querySelector(selector);
const $$=(selector,root=document)=>[...root.querySelectorAll(selector)];
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function formatCountry(code){
 code=String(code||'').trim().toUpperCase();
 if(!/^[A-Z]{2}$/.test(code)||code==='XX')return '';
 const flag=[...code].map(char=>String.fromCodePoint(char.charCodeAt(0)+127397)).join('');
 let name=code;
 try{name=new Intl.DisplayNames(['zh-CN'],{type:'region'}).of(code)||code;}catch{}
 return `${flag} ${name}`;
}
function renderClientIp(info){
 const ip=String(info?.client_ip||'');
 const proto=info?.ip_proto==='IPv6'||(!info?.ip_proto&&ip.includes(':'))?'IPv6':'IPv4';
 const isV6=proto==='IPv6',countryLabel=formatCountry(info?.country);
 const html=`<span class="ip-indicator ${isV6?'is-v6':''}" aria-hidden="true"></span><span class="ip-addr" title="${esc(ip)}">${esc(ip)}</span><span class="ip-tag ${isV6?'tag-v6':'tag-v4'}">${proto}</span>${countryLabel?`<span class="ip-country">${esc(countryLabel)}</span>`:''}`;
 for(const selector of ['#auth-ip-badge','#sidebar-ip-badge','#auth-mobile-ip-badge','#workspace-mobile-ip-badge']){
  const badge=$(selector);if(!badge)continue;
  badge.innerHTML=ip?html:'';badge.hidden=!ip;
  badge.title=ip?[ip,proto,countryLabel].filter(Boolean).join(' · '):'';
  badge.setAttribute('aria-label',ip?'当前访问：'+badge.title:'');
 }
}
const paths={home:'M3 10 12 3l9 7v10H3z M9 20v-7h6v7',calendar:'M5 5h14v15H5z M8 3v4m8-4v4M5 10h14m-11 4h2m4 0h2m-8 3h2',link:'m9 15 6-6 M8 16l-2 2a4 4 0 0 1-5-5l4-4a4 4 0 0 1 5 0 M14 15a4 4 0 0 0 5 0l4-4a4 4 0 0 0-5-5l-2 2',activity:'M3 13h4l3-8 4 14 3-6h4',settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M10 2h4l1 3 3 1 3 3-2 3 1 3-3 3-3-1-2 2-3-1-1-3-3-1-1-4 2-2-1-3 3-3z',users:'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M2 21v-3a7 7 0 0 1 14 0v3 M16 4a4 4 0 0 1 0 7m2 4a6 6 0 0 1 4 6',logout:'M9 4H4v16h5 M13 8l5 4-5 4m-4-4h12',refresh:'M20 8a9 9 0 0 0-15-3L2 8m0-5v5h5 M4 16a9 9 0 0 0 15 3l3-3m0 5v-5h-5',arrow:'M5 12h14m-6-6 6 6-6 6',chevron:'m9 5 7 7-7 7',alert:'m12 3 10 18H2z M12 9v5m0 3v1',book:'M12 5 3 3v16l9 2 9-2V3z M12 5v16',copy:'M8 8h12v12H8z M5 15H3V3h12v2',download:'M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4',clock:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v5l4 2',check:'m5 12 4 4L19 6',lock:'M6 10h12v11H6z M8 10V6a4 4 0 0 1 8 0v4'};
const icon=(name,extra='')=>`<svg class="icon ${extra}" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name]||paths.book}"/></svg>`;
$$('[data-icon]').forEach(el=>el.innerHTML=icon(el.dataset.icon));
let lastAnimatedPage='',registrationBusy=false;
let updateState=null,updateChecking=false;
let editingLessonKey='';
let csrf='',data=null,bootstrap=null,page='overview',authMode='login',week=1,kindFilter='all',logFilter='school',subscriptionTab='ics',adminUsers=[],polling=false;
const labels={overview:'我的课间',timetable:'课表一览',subscriptions:'订阅日历',logs:'同步记录',settings:'账户与同步',debug:'调试',admin:'用户管理'};
const kindNames={teaching:'教学课表',lab:'实验课表',combined:'聚合课表',account:'账户设置',admin:'用户管理'};
const sourceNames={app:'校园 App',jw:'教务系统','lab-cas':'学生服务大厅 · 统一门户'};
const stateNames={ok:'同步正常',warning:'已故障转移',error:'同步异常',idle:'等待同步',running:'正在同步',queued:'等待执行'};
const today=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date());
function fmt(value,short=false){if(!value)return '尚未更新';return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',...(short?{}:{year:'numeric'}),hour12:false}).format(new Date(value));}
function dateISO(date){return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(date);}
function shifted(date,days){return new Date(new Date(date+'T00:00:00+08:00').getTime()+days*86400000);}
function currentWeek(){return Math.max(1,Math.min(data.settings.config.maxWeekNumber,Math.floor((new Date(today()+'T00:00:00+08:00')-new Date(data.settings.config.week1_monday+'T00:00:00+08:00'))/604800000)+1));}
function enterEffect(element,frames=null,options={}){
 if(!element?.animate||window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)return;
 element.getAnimations?.().forEach(animation=>animation.cancel());
 element.animate(frames||[{opacity:0,transform:'translateY(9px)'},{opacity:1,transform:'translateY(0)'}],{duration:260,easing:'cubic-bezier(.22,1,.36,1)',...options});
}
function enterPage(){
 if(lastAnimatedPage===page)return;
 lastAnimatedPage=page;
 [...($('#content').children||[])].filter(el=>!el.classList.contains('lesson-create')).forEach((el,index)=>enterEffect(el,null,{delay:Math.min(index*24,100),fill:'backwards'}));
}
function toast(message,error=false){const el=$('#toast');el.textContent=message;el.className='toast'+(error?' error':'');el.hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.hidden=true,4500);}
async function api(path,options={}){
 const response=await fetch(path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...(csrf?{'X-CSRF-Token':csrf}:{}),...(options.headers||{})}});
 const value=await response.json();if(!response.ok){if(response.status===401&&data){data=null;showAuth();}throw Error(value.error||'请求未完成');}return value;
}
function modal(title,body,actions,closable=true){$('#modal-content').innerHTML=`<h2 id="modal-title">${esc(title)}</h2>${body}<div class="dialog-actions">${closable?'<button class="button" data-action="close-modal">关闭</button>':''}${actions||''}</div>`;$('#modal').showModal();enterEffect($('#modal'),[{opacity:0,transform:'translateY(12px) scale(.98)'},{opacity:1,transform:'translateY(0) scale(1)'}],{duration:230});}
function disclaimer(firstUse=false){modal('使用说明与免责声明',`${firstUse?'<p class="panel-description">首次使用课间，请先阅读以下说明。</p>':''}<p>${esc(bootstrap.disclaimer)}</p><p style="margin-top:17px;font-size:10px">版本 ${esc(bootstrap.disclaimer_version)} · 开发者 安稳 · <a class="credit-link" href="https://github.com/liuayueeryuan0313" target="_blank" rel="noopener noreferrer" aria-label="安稳的 GitHub，另开窗口">© 2026 安稳 <span aria-hidden="true">↗</span></a>，版权所有。</p>`,firstUse?'<button class="button primary" data-action="ack-disclaimer">我已阅读，继续使用</button>':'',!firstUse);}
function maybeFirstUseNotice(){let seen=false;try{seen=localStorage.getItem('koma.disclaimer.version')===bootstrap.disclaimer_version;}catch{}if(!seen)disclaimer(true);}
function showAuth(){csrf='';$('#workspace').hidden=true;$('#auth').hidden=false;$('#loading').hidden=true;$('#setup-tab').hidden=!bootstrap.setup_required;setAuthMode('login');lastAnimatedPage='';enterEffect($('.auth-story'),null,{duration:420});enterEffect($('.auth-box'),null,{duration:340,delay:60,fill:'backwards'});document.dispatchEvent?.(new Event('koma:render'));}
function setAuthMode(mode){const changed=authMode!==mode;authMode=mode;$$('[data-auth]').forEach(button=>{button.classList.toggle('active',button.dataset.auth===mode);button.setAttribute('aria-selected',button.dataset.auth===mode)});$('#auth-title').textContent=mode==='login'?'很高兴见到你。':mode==='register'?'给日常，一本新笔记。':'从这里开始。';$('#auth-description').textContent=mode==='setup'?'创建首个管理员账户。':'登录账户后，可配置自己的学校课表。';$('#auth-submit').innerHTML=(mode==='login'?'进入课间':mode==='register'?'创建我的账户':'创建管理员')+' <span>↗</span>';$('#consent-field').hidden=mode==='login';$('#forgot-password').hidden=mode!=='login';$('#register-recovery-hint').hidden=mode!=='register';$('#setup-field').hidden=mode!=='setup';$('#auth-error').textContent='';$('#auth-form [name=password]').autocomplete=mode==='login'?'current-password':'new-password';$('#auth-form [name=password]').minLength=mode==='login'?0:10;$('#auth-form [name=password]').maxLength=256;if(changed)enterEffect($('.auth-box'),null,{duration:200});}
async function refresh(force=false){
 if(polling)return;polling=true;
 try{const next=await api('/api/dashboard');const changed=JSON.stringify(next)!==JSON.stringify(data);data=next;if((changed||force)&&(!['INPUT','SELECT'].includes(document.activeElement?.tagName)||force)&&page!=='settings')render();if(page==='settings')updatePlatformStatuses();}
 finally{polling=false;}
}
function showWorkspace(){ $('#auth').hidden=true;$('#workspace').hidden=false;$('#loading').hidden=true;week=currentWeek();render();updateVersionBadge();if(!updateState)checkUpdates(false);}
function pageHeading(eyebrow,title,description,action=''){return `<div class="page-heading"><div><span class="eyebrow">${eyebrow}</span><h1>${title}</h1><p>${description}</p></div>${action}</div>`;}
function badge(state){return `<span class="badge ${esc(state||'idle')}">${stateNames[state]||'等待同步'}</span>`;}
function sourceCard(kind){
 const state=data.states[kind],settings=data.settings,calendar=data.calendars[kind],busy=['running','queued'].includes(state.state);
 const identity=state.identity_name||data.user.student_name||'尚未取得学校姓名';const id=state.identity_id||settings.student_id||'尚未设置学号';
 return `<article class="source-card ${kind==='lab'?'lab':''}"><div class="card-heading"><span class="card-index">${kind==='teaching'?'01 / TEACHING':'02 / LABORATORY'}</span>${badge(state.state)}</div><div class="source-title"><h3>${kindNames[kind]}</h3><span class="source-count">${calendar?.occurrences??'—'}<small>课次</small></span></div><p class="source-description">${kind==='teaching'?'日常课程，按教学周次整理。':'每一个实验项目，单独保留。'}</p><div class="source-mode">${icon(kind==='teaching'?'refresh':'lock')}${kind==='teaching'?`<select id="quick-mode" aria-label="教学课表来源"><option value="auto" ${settings.mode==='auto'?'selected':''}>App 优先 · token失效转教务</option><option value="app" ${settings.mode==='app'?'selected':''}>仅使用校园 App</option><option value="jw" ${settings.mode==='jw'?'selected':''}>仅使用教务系统</option></select>`:'学生服务大厅统一门户 · 与 App 共用密码'}</div>${state.warning?`<div class="warning-box ${state.state==='error'?'error':''}">${icon('alert')}<span>${esc(state.warning)}</span></div>`:''}<dl class="source-meta"><div><dt>学校姓名 / 用户名</dt><dd>${esc(identity)}</dd></div><div><dt>学号</dt><dd>${esc(id)}</dd></div><div><dt>上次学校同步成功</dt><dd>${fmt(state.last_success,true)}</dd></div><div><dt>下次学校自动同步</dt><dd>${state.enabled?fmt(state.next_run,true):'自动更新未开启'}</dd></div><div><dt>当前成功来源</dt><dd>${esc(sourceNames[state.active_source]||'尚未拉取')}</dd></div><div><dt>最近学校拉取尝试</dt><dd>${state.last_attempt?fmt(state.last_attempt,true):'尚未尝试'}</dd></div></dl><div class="source-bottom"><button class="button small" data-action="sync" data-scope="${kind}" ${busy?'disabled':''}>${icon('refresh',busy?'spin':'')}${busy?'正在同步':'同步'+(kind==='teaching'?'教学':'实验')}</button>${kind==='teaching'&&settings.mode!=='jw'?`<button class="text-button" data-action="app-init">${settings.has_app_token?'重新获取 App token':'获取 App token'}</button>`:`<button class="text-button" data-page="logs">学校拉取记录 ↗</button>`}</div></article>`;
}
function agendaRows(rows){return rows.map(row=>{const weekday=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',weekday:'short'}).format(new Date(row.date+'T12:00:00+08:00'));return `<div class="agenda-row"><div class="agenda-date"><strong>${row.date.slice(5).replace('-',' / ')}</strong>${weekday}</div><div class="agenda-time">${row.startLocal.slice(11,16)}<br>${row.endLocal.slice(11,16)}</div><div class="agenda-course"><strong>${esc(row.name)}</strong><small>${esc(row.location)}${row.teacher?' · '+esc(row.teacher):''}</small></div><div class="agenda-kind"><span class="kind-label ${row.kind==='lab'?'lab':''}">${row.kind==='lab'?'实验':'教学'}</span></div></div>`}).join('');}
function overview(){
 const end=dateISO(shifted(today(),7)),upcoming=data.occurrences.filter(row=>row.date>=today()&&row.date<end).slice(0,10),running=Object.values(data.states).some(s=>['running','queued'].includes(s.state));
 const name=data.user.student_name||data.user.username;
 const combined=data.calendars.combined;
 return `<section class="hero"><div><span class="eyebrow">YOUR DAYS, IN GOOD ORDER</span><h1>${esc(name)}的课间。</h1><p>第 ${currentWeek()} 教学周 <span style="padding:0 8px">/</span> ${esc(data.settings.config.term)} 学期</p><div class="hero-actions"><button class="button primary" data-action="sync" data-scope="all" ${running?'disabled':''}>${icon('refresh',running?'spin':'')}${running?'正在向学校同步':'同步两份课表'}</button><button class="button" data-page="subscriptions">订阅日历 ${icon('arrow')}</button></div></div><span class="date-stamp">日々の余白</span><button class="hero-cat ${running?'syncing':''}" data-action="cat" aria-label="和纸猫打个招呼"><img data-cat-follow src="/mascot.svg" alt="抱着课本的纸猫"><span class="cat-caption">纸猫 · ${running?'正在整理课表':'今天也从容一点'}</span></button></section><div class="section-title"><h2>两份课表，各有归处。</h2><button class="text-button" data-page="settings">管理同步设置 ↗</button></div><div class="sources-grid">${sourceCard('teaching')}${sourceCard('lab')}</div><div data-shared-sync-notice>${sharedSyncNotice()}</div><div class="hint-strip"><span>${icon('link')}${combined?`聚合订阅已就绪，共 ${combined.occurrences} 课次。`:'两份课表首次同步成功后，会自动生成聚合订阅。'}${combined?.overlaps?` 发现 ${combined.overlaps} 处时间重叠，请核对。`:''}</span><button class="text-button" data-page="subscriptions">查看订阅 ↗</button></div><div class="section-title"><h2>接下来七天</h2><button class="text-button" data-page="timetable">完整课表 ↗</button></div><section class="agenda">${upcoming.length?agendaRows(upcoming):`<div class="empty">${icon('book')}${data.occurrences.length?'这几天暂时没有课程安排。':'还没有课表。先在账户与同步中保存学校账户，再同步课表。'}</div>`}</section>`;
}
function filters(active,attr,values){return `<div class="filters">${values.map(([value,label])=>`<button class="filter ${active===value?'active':''}" data-${attr}="${value}">${label}</button>`).join('')}</div>`;}
function timetable(){
 const start=dateISO(shifted(data.settings.config.week1_monday,(week-1)*7));
 let html=pageHeading('YOUR WEEK AT A GLANCE','课表一览。','教学与实验使用不同标记；时间均为北京时间。');
 const conflicts=data.occurrences.filter(r=>r.conflictFields?.length);
 if(conflicts.length)html+=`<section class="conflict-summary"><strong>${conflicts.length} 次课程安排待核对</strong><p>学校安排有变更，已保留你的修改。点击下方课程比较并选择。</p><div>${conflicts.map(r=>`<button class="button small" data-action="edit-lesson" data-kind="${r.kind}" data-id="${esc(r.occurrenceId)}">${esc(r.name)} · ${esc(r.date)}</button>`).join('')}</div></section>`;
 html+=`<div class="week-controls"><div class="week-select"><button class="icon-button" data-action="prev-week" aria-label="上一周">←</button><select id="week-select" aria-label="教学周">${Array.from({length:data.settings.config.maxWeekNumber},(_,i)=>`<option value="${i+1}" ${week===i+1?'selected':''}>第 ${i+1} 教学周</option>`).join('')}</select><button class="icon-button" data-action="next-week" aria-label="下一周">→</button><button class="text-button muted" data-action="current-week">本周</button></div>${filters(kindFilter,'kind-filter',[['all','全部'],['teaching','教学'],['lab','实验']])}</div><div class="week-grid-wrap"><div class="week-grid">`;
 for(let day=0;day<7;day++){
  const date=dateISO(shifted(start,day)),rows=data.occurrences.filter(r=>r.date===date&&(kindFilter==='all'||r.kind===kindFilter));
  html+=`<section class="day-column ${date===today()?'today':''}"><div class="day-heading"><span>周${'一二三四五六日'[day]}</span><strong>${date.slice(8)}</strong></div>${rows.map(r=>`<button type="button" class="lesson ${r.kind==='lab'?'lab':''}" data-action="edit-lesson" data-kind="${r.kind}" data-id="${esc(r.occurrenceId)}" aria-label="修改 ${esc(r.name)} 本次课程" aria-haspopup="dialog" aria-expanded="${editingLessonKey===r.kind+':'+r.occurrenceId}">${r.kind==='lab'?'<span class="lesson-label">LAB / 实验</span>':''}<span class="lesson-status ${r.conflictFields?.length?'pending':''}">${r.conflictFields?.length?'待核对':r.origin==='manual'?'手动新增':r.origin==='override'?'已修改':''}</span>${r.timeOverlap?'<span class="lesson-status pending">时间重叠</span>':''}<span class="lesson-time">${r.startLocal.slice(11,16)} – ${r.endLocal.slice(11,16)}</span><span class="lesson-title">${esc(r.name)}</span><span class="lesson-location">${esc(r.location)}<br>${esc(r.teacher||'')}<br>第 ${r.startPeriod}–${r.endPeriod} 节</span></button>`).join('')||'<div class="no-lesson">今日留白</div>'}</section>`;
 }
 return html+`</div></div><button type="button" class="lesson-create" data-action="new-lesson" aria-label="手动新建课程" aria-haspopup="dialog" aria-expanded="${editingLessonKey==='new'}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg></button><p class="help-note">课表以学校实际安排为准。单双周按源数据精确展开；实验按具体项目与周次保留。</p>`;
}
function subscriptionInstructions(){return `<section class="import-guide"><div class="section-title"><h2>把课表带到手机</h2><small>订阅会更新 · 文件导入为一次性副本</small></div><div class="import-grid"><article class="panel"><span class="eyebrow">01 / APPLE</span><h3>iPhone / iPad</h3><ol><li>复制上方需要的订阅地址，通常选择聚合课表。</li><li>打开“日历”App，进入“日历”列表，选择“添加日历” → “添加订阅日历”。</li><li>粘贴地址，按系统提示查找并完成订阅。不同系统版本按钮名称可能略有区别。</li></ol><p>Mac：在“日历”中选择“文件” → “新建日历订阅”，粘贴相同地址。</p><a class="about-link" href="https://support.apple.com/zh-cn/guide/iphone/iph3d1110d4/ios" target="_blank" rel="noopener noreferrer">Apple 官方说明 ↗</a></article><article class="panel"><span class="eyebrow">02 / ANDROID</span><h3>安卓</h3><ol><li>日历 App 支持“从网址订阅 / 网络日历”时，直接粘贴上方地址。</li><li>没有订阅入口时，可使用 ICSx⁵ 添加订阅地址，并设置刷新间隔。</li><li>允许日历权限后，在系统日历或常用日历 App 中勾选这份订阅；需要时允许后台同步。</li></ol><p>打开下载的 .ics 文件导入，只保存当时的课表，不会持续更新。</p><a class="about-link" href="https://icsx5.bitfire.at/" target="_blank" rel="noopener noreferrer">ICSx⁵ 官方说明 ↗</a></article></div><p class="help-note">手机须能访问订阅地址。局域网地址需要连接同一网络；仅导入文件不具备订阅更新能力。已订阅聚合课表时，无需再订阅教学与实验，避免重复显示。</p></section>`;}
function subscriptions(){return pageHeading('CALENDARS THAT STAY WITH YOU','订阅你的日常。','选择订阅方式，将课程安排放进常用日历。')+`<div class="subscription-tabs" role="tablist" aria-label="日历订阅方式"><button id="ics-tab" role="tab" aria-controls="ics-panel" aria-selected="${subscriptionTab==='ics'}" tabindex="${subscriptionTab==='ics'?0:-1}" data-subscription-tab="ics">ICS 订阅</button><button id="caldav-tab" role="tab" aria-controls="caldav-panel" aria-selected="${subscriptionTab==='caldav'}" tabindex="${subscriptionTab==='caldav'?0:-1}" data-subscription-tab="caldav">CalDAV 订阅</button></div><section id="ics-panel" role="tabpanel" aria-labelledby="ics-tab" ${subscriptionTab==='ics'?'':'hidden'}>${icsSubscriptions()}${subscriptionInstructions()}</section><section id="caldav-panel" role="tabpanel" aria-labelledby="caldav-tab" ${subscriptionTab==='caldav'?'':'hidden'}><div class="caldav-placeholder panel">${icon('clock')}<span class="eyebrow">CALDAV</span><h2>正在开发，敬请期待。</h2><p>目前可使用 ICS 订阅课表。</p></div></section>`;}
function icsSubscriptions(){return `<div class="subscription-grid">${['combined','teaching','lab'].map((kind,i)=>{const cal=data.calendars[kind];return `<article class="subscription-card"><div><span class="eyebrow">0${i+1} / ${{combined:'TOGETHER',teaching:'TEACHING',lab:'LABORATORY'}[kind]}</span><h2>${kindNames[kind]}</h2><p>${cal?cal.occurrences+' 课次 · '+fmt(cal.updated_at,true):'首次同步成功后可用'}</p></div><div><div class="subscription-link">${esc(data.links[kind])}</div><div class="subscription-actions"><div><button class="button small primary" data-action="copy-link" data-kind="${kind}" ${cal?'':'disabled'}>${icon('copy')}复制订阅地址</button><a class="button small" ${cal?`href="${esc(data.links[kind])}" download="${kind}.ics"`:'aria-disabled="true"'}>${icon('download')}下载 .ics</a></div><button class="text-button" data-action="rotate-link" data-kind="${kind}">更换私密链接</button></div></div></article>`}).join('')}</div><div class="help-note">添加方式：在日历应用中选择“添加订阅日历”，粘贴链接。订阅会读取最新成功版本；下载文件后导入属于一次性副本。<br>学校自动同步由本服务执行，日历客户端何时刷新由客户端决定。链接持有者可读取课表，请只保留在自己的设备中。</div>`;}
function logs(){
 const rows=data.logs.filter(r=>logFilter==='all'||r.category===logFilter);
 return pageHeading('A RECORD OF EVERY UPDATE','每一次同步，都有记录。','学校平台的登录与拉取记录独立显示，和日历客户端访问区分开。')+filters(logFilter,'log-filter',[['school','学校平台拉取'],['sync','转换与同步'],['delivery','日历订阅访问'],['all','全部记录']])+`<div class="log-list">${rows.map(r=>`<div class="log-row ${r.level==='error'?'error':''}"><div class="log-time">${fmt(r.created_at)}</div><div class="log-event"><span class="log-dot ${r.level}"></span>${esc(kindNames[r.kind]||r.kind)}</div><div>${esc(r.message)}</div></div>`).join('')||'<div class="empty">'+(logFilter==='school'?'尚未向学校平台发起拉取。手动同步或自动任务开始后，记录会出现在这里。':'这个分类还没有记录。')+'</div>'}</div>`;
}
const platformNames={app:'校园 App',jw:'教务系统',lab:'实验平台'};
function platformStatus(platform){return ['test','login'].map(action=>{const result=data.platform_checks?.[platform]?.[action];return `<div class="platform-result ${esc(result?.state||'idle')}"><strong>${action==='test'?'课表拉取测试':platform==='app'?'token 获取':'登录验证'}</strong><span>${esc(result?.message||(action==='test'?'尚未测试':platform==='app'?'尚未获取 token':'尚未登录验证'))}</span>${result?`<small>${fmt(result.checked_at)}${result.identity_name?' · '+esc(result.identity_name):''}${result.identity_id?' · '+esc(result.identity_id):''}</small>`:''}</div>`}).join('');}
function platformControls(){return `<div class="form-section"><h3>三平台连接与登录</h3><p class="field-help">测试完整拉取并校验课表，显示实际课次数；不保存测试凭据、不更新订阅。App 仅用 token 拉取，登录只用于获取 token；教务和实验使用当前填写的账号密码（留空复用已保存值）。</p><div class="platform-list">${['app','jw','lab'].map(platform=>`<section class="platform-card"><div class="platform-heading"><strong>${platformNames[platform]}</strong><span>${platform==='app'?'教学 · App':platform==='jw'?'教学 · 独立密码':'实验 · 统一门户'}</span></div><div class="platform-actions"><button type="button" class="button small" data-action="platform-test" data-platform="${platform}" aria-label="测试${platformNames[platform]}课表拉取">${icon('activity')}测试课表拉取</button><button type="button" class="button small primary" data-action="platform-login" data-platform="${platform}" aria-label="${platform==='app'?'登录校园 App获取token':'登录'+platformNames[platform]}">${icon('lock')}${platform==='app'?'登录获取 token':'登录'}</button></div><div data-platform-status="${platform}" aria-live="polite">${platformStatus(platform)}</div>${platform==='app'?'<p class="field-help">App 登录仅获取 token。测试和同步直接使用 token；缺失或失效不会自动重新登录。获取新 token 可能使手机 App 退出，操作前会再次提示。</p>':''}</section>`).join('')}</div></div>`;}
function updatePlatformStatuses(){if(page!=='settings'||!data)return;$$('[data-shared-sync-notice]').forEach(el=>el.innerHTML=sharedSyncNotice());const busy=Object.values(data.platform_checks||{}).some(group=>Object.values(group).some(result=>result.state==='running'))||Object.values(data.states).some(state=>['queued','running'].includes(state.state));$$('[data-platform-status]').forEach(el=>el.innerHTML=platformStatus(el.dataset.platformStatus));$$('[data-action=platform-test],[data-action=platform-login]').forEach(el=>el.disabled=busy);}
async function platformAction(platform,action,ack=false){const form=$('#settings-form'),values=form?Object.fromEntries(new FormData(form)):{};const body={...schoolFormValues(values),...Object.fromEntries(['student_id','campus_password','jw_password','app_token'].filter(key=>key in values).map(key=>[key,values[key]]))};if(ack)body.ack_app_relogin=true;await api(`/api/platforms/${platform}/${action}`,{method:'POST',body:JSON.stringify(body)});if(action==='login'&&form){['campus_password','jw_password','app_token'].forEach(name=>form.elements[name].value='');}await refresh();updatePlatformStatuses();toast(action==='test'?'正在验证登录并拉取课表':'正在验证学校登录');}
function sharedSyncEnabled(){
 const s=data?.settings,states=data?.states;
 return !!(s&&states&&['app','auto'].includes(s.mode)&&s.has_app_token&&!s.app_token_invalid&&states.teaching.enabled&&states.lab.enabled&&states.teaching.interval_minutes===states.lab.interval_minutes);
}
function sharedSyncNotice(){return sharedSyncEnabled()?`<div class="shared-sync-notice" role="status">${icon('link')}<div><strong>已启用两份课表合并同步</strong><p>教学与实验更新间隔相同。每轮复用 App token，实验平台仅登录一次，随后拉取两份课表。点击任一同步按钮也会一起更新；不会自动重新登录 App。</p></div></div>`:'';}
function schoolFormValues(values){const result={school_profile:values.school_profile||data.settings.config.school_profile||'sdut'};if(result.school_profile==='custom')result.school_custom=Object.fromEntries(Object.entries(values).filter(([key])=>key.startsWith('school_custom.')).map(([key,value])=>[key.slice(14),value]));if(values.period_times!==undefined)result.period_times=values.period_times;return result;}
function schoolSettings(){
 const c=data.settings.config,selected=c.school_profile||'sdut',custom=c.school_custom||{};
 const parameterDefaults={app_exchange_path:'/sys/security/login_sdutapp',app_client_version:'3.2.0',jw_campus_id:'1',lab_cas_entry:'/zxcas'};
 const field=(key,label,placeholder='',note='')=>`<label>${label}<input name="school_custom.${key}" type="${['app_origin','app_h5_base','jw_base','lab_base','sso_base'].includes(key)?'url':'text'}" value="${esc(custom[key]??parameterDefaults[key]??'')}" placeholder="${esc(placeholder)}" maxlength="${key==='name'?80:500}" ${key==='name'?'required':''} autocomplete="off">${note?`<span class="field-help">${note}</span>`:''}</label>`;
 return `<section class="panel school-panel"><div class="section-title"><h2>学校与平台</h2><small>三种接入方式共用这份学校配置</small></div><label class="school-selector">学校<select name="school_profile" id="school-profile"><option value="sdut" ${selected==='sdut'?'selected':''}>山东理工大学</option><option value="custom" ${selected==='custom'?'selected':''}>自定义</option></select></label><p class="panel-description">自定义适用于与现有适配器使用相同协议的平台。同一厂商的不同版本、登录方式或返回格式仍可能需要单独适配。</p><div class="vendor-summary"><span>App：联奕系移动校园 + 兼容课表 H5</span><span>教务：正方新教务系统</span><span>实验：中新天达 ZXTD + 金智 CAS 风格认证</span></div><p class="field-help">App 与实验厂商归属按接口特征识别，须以本校合同或官方说明核实；“同厂商”不等于已验证兼容。只有山东理工大学已完成真实接口验收。</p><fieldset id="custom-school-fields" ${selected==='custom'?'':'hidden disabled'}>${field('name','学校名称','填写你的学校名称')}<div class="custom-platform-grid"><section class="custom-platform"><h3>教学 · 校园 App</h3><p class="field-help">适配 mobileapi_ydxy 登录与当前课表 H5 数据结构。</p><div class="form-stack">${field('app_origin','App 服务地址','https://mcp.example.edu.cn:8080','填写协议、域名及端口，不带接口路径；旧版接口可使用 HTTP。')}${field('app_h5_base','课表 H5 API 基址','https://schedule.example.edu.cn/schedule/api','需要完整 API 前缀，不能填写课表页面网址。')}${field('app_school_id','学校代码','从学校 App 请求中获取')}${field('app_yyid','课表应用编号 YYID','从学校 App 应用列表获取')}${field('app_exchange_path','换取 token 的接口路径','','可按同协议学校实际路径修改，不能带域名。')}${field('app_client_version','客户端版本')}</div></section><section class="custom-platform"><h3>教学 · 教务系统</h3><p class="field-help">正方新教务：RSA 登录、kbList/jcs/zcd 课表接口。</p><div class="form-stack">${field('jw_base','教务系统基址','https://jw.example.edu.cn/jwglxt','保留 /jwglxt 等部署前缀，不带 login_slogin.html。')}${field('jw_campus_id','校区编号','','用于查询节次时间；学期编码在下方单独设置。')}</div></section><section class="custom-platform"><h3>实验 · 统一门户</h3><p class="field-help">ZXTD 签名分页接口 + 当前 AES-CBC CAS 登录表单，仅适配相同接口与签名版本。</p><div class="form-stack">${field('lab_base','实验平台 API 基址','https://lab.example.edu.cn','填写接口站点及部署前缀，不带 /TEACH/# 等页面路由。')}${field('lab_cas_entry','实验 CAS 入口路径')}${field('sso_base','统一认证基址','https://auth.example.edu.cn/authserver','与实验域名分别填写，保留 /authserver 等前缀。')}</div></section></div><details class="school-help clock-editor"><summary>核对本校作息时间</summary><p>目前填入已配置的作息时间；首次自定义沿用山理工参考时间。如本校不同，请修改后保存。每行填写“节次 开始时间 结束时间”，连续节次可写成 11-12 21:05 22:45。教学和实验共用此时间表。</p><label>节次与起止时间<textarea name="period_times" rows="11" spellcheck="false">${esc([...Object.entries(c.periods||{}),...Object.entries(c.period_ranges||{})].map(([key,times])=>key+' '+times.join(' ')).join('\n'))}</textarea></label></details><p class="school-change-note">修改服务地址、学校代码等连接参数后，原学校密码、token、身份与课表会清除，订阅地址也会更换。请重新填写本校凭据，避免把旧学校凭据用于新站点。仅修改显示名称不清除数据。</p><details class="school-help"><summary>参数怎么填</summary><p>只配置要使用的平台即可，未填写的平台会提示未配置，不会访问山东理工大学。地址来自本校已登录页面的网络请求，应用编号与学校代码来自 App 请求；默认接口路径只作参考。测试会使用当前填写的配置，完整拉取但不保存；保存或登录后，定时与手动同步使用各自账户已保存的学校配置。</p></details></fieldset></section>`;
}
function reminderSettings(c){
 const enabled=c.reminder_enabled!==false;
 return `<section class="panel reminder-panel" id="calendar-reminder-settings"><form id="reminder-form"><span class="eyebrow">04 / REMINDERS</span><h2>日历提醒</h2><p class="panel-description">选择是否在上课前提醒，以及提前多久。</p><label class="reminder-toggle" for="reminder-enabled"><span>提前提醒<small id="reminder-status">${enabled?'已开启':'已关闭'}</small></span><input class="reminder-switch" id="reminder-enabled" name="reminder_enabled" type="checkbox" role="switch" aria-controls="reminder-minutes" ${enabled?'checked':''}></label><label for="reminder-minutes">提前时长（分钟）<input id="reminder-minutes" name="reminder_minutes" type="number" min="1" max="10080" step="1" value="${esc(c.reminder_minutes??20)}" ${enabled?'required':'disabled'}><span class="field-help">可设置 1–10080 分钟（最多 7 天）。</span></label><p class="field-help reminder-help">保存后应用于教学、实验及聚合订阅，日历客户端刷新后生效。</p><button type="submit" class="button primary small reminder-save">保存提醒设置</button></form></section>`;
}
function settings(){
 const s=data.settings,c=s.config;
 const plan=kind=>`<div class="plan"><div class="plan-heading"><span>${kindNames[kind]}</span><label class="check-label"><input type="checkbox" name="${kind}_enabled" ${data.states[kind].enabled?'checked':''}>自动同步</label></div><select name="${kind}_interval" aria-label="${kindNames[kind]}更新间隔">${[[30,'每30分钟'],[60,'每小时'],[360,'每6小时'],[720,'每12小时'],[1440,'每天']].map(([v,t])=>`<option value="${v}" ${data.states[kind].interval_minutes===v?'selected':''}>${t}</option>`).join('')}</select><small>下次向学校拉取：${data.states[kind].enabled?fmt(data.states[kind].next_run):'未开启'}</small></div>`;
 return pageHeading('ACCOUNT & CONNECTIONS','把连接，安放妥当。','学校密码加密保存，用于你授权的同步；管理员界面不回显密码。')+`<form id="settings-form">${schoolSettings()}<div class="settings-grid"><section class="panel"><span class="eyebrow">01 / SCHOOL ACCOUNT</span><h2>学校账户</h2><p class="panel-description">三种方式共用学号。校园 App 与实验平台共用学生服务大厅统一门户密码，教务系统使用单独密码。</p><div class="form-stack"><label>学号<input name="student_id" value="${esc(s.student_id)}" autocomplete="off" placeholder="请输入学校学号" required></label><label>App / 学生服务大厅统一门户密码<input name="campus_password" type="password" autocomplete="new-password" placeholder="${s.has_campus_password?'已加密保存，留空保留':'请输入统一门户密码'}"><span class="field-help">用于校园App授权，以及实验平台的学校统一身份认证。</span></label><label>教务系统密码<input name="jw_password" type="password" autocomplete="new-password" placeholder="${s.has_jw_password?'已加密保存，留空保留':'请输入单独的教务系统密码'}"></label><label>教学课表来源<select name="mode"><option value="auto" ${s.mode==='auto'?'selected':''}>优先App，token失效时转教务系统</option><option value="app" ${s.mode==='app'?'selected':''}>仅校园App</option><option value="jw" ${s.mode==='jw'?'selected':''}>仅教务系统</option></select></label></div><div class="form-section"><h3>已有 App token（可选）</h3><label>直接复用token<input name="app_token" type="password" autocomplete="off" placeholder="${s.has_app_token?'已有加密token，留空保留':'可粘贴已有token，避免重新登录App'}"></label><p class="field-help">首次授权App需要手动确认，可能使手机App退出。定时更新不会隐式重新登录App。</p></div></section><div class="settings-aside"><section class="panel"><span class="eyebrow">02 / UPDATE RHYTHM</span><h2>自动同步的节奏</h2><p class="panel-description">这是向学校平台拉取数据的时间安排。相同间隔且教学使用有效 App token 时，两份课表合并同步；其他来源和间隔仍独立执行。</p>${plan('teaching')}${plan('lab')}<div data-shared-sync-notice>${sharedSyncNotice()}</div></section><section class="panel"><span class="eyebrow">03 / TERM</span><h2>学期与时间</h2><div class="form-stack"><label>学期<input name="term" value="${esc(c.term)}" pattern="[0-9]{4}-[0-9]{4}-[12]" required></label><div class="field-row"><label>第一周星期一<input name="week1_monday" type="date" value="${esc(c.week1_monday)}" required></label><label>总周数<input name="maxWeekNumber" type="number" min="1" max="53" value="${c.maxWeekNumber}" required></label></div><label>教务系统学期编码<input name="jw_semester_code" value="${esc(c.jw_semester_code)}" required><span class="field-help">本学期已验证为3。其他学期请使用学校实际编码。</span></label></div><div class="times-note">北京时间<br>第11–12节：${esc((c.period_ranges?.['11-12']||(c.periods?.['11']&&c.periods?.['12']?[c.periods['11'][0],c.periods['12'][1]]:[])).join(' – ')||'未配置')}<br>单双周按学校返回的实际排课生成。</div></section></div></div><div class="settings-save"><button type="submit" class="button primary">${icon('check')}保存设置</button><span>密码输入留空会保留已保存值。修改学号或学校连接参数会清除旧凭据、课表并更换订阅链接。</span></div></form>${reminderSettings(c)}<section class="panel platform-panel">${platformControls()}</section><div class="section-title"><h2>站内账户</h2><small>${esc(data.user.username)} / ${data.user.role==='admin'?'管理员':'普通用户'}</small></div><section class="panel"><div class="source-bottom"><span class="muted" style="font-size:11px">站内登录密码与学校密码分别管理。</span><div class="filters">${data.user.role==='user'?`<button class="button small" data-action="setup-recovery">${s.recovery_enabled?'修改密保问题':'设置密保问题'}</button>`:''}<button class="button small" data-action="change-password">修改站内密码</button><button class="button small danger" data-action="clear-credentials">清除学校凭据</button></div></div></section>`;
}
function debug(){return pageHeading('DEBUG','调试。','')+`<section class="panel"><label class="reminder-toggle"><span>在日历订阅访问日志中显示源 IP</span><input id="debug-source-ip" class="reminder-switch" type="checkbox" role="switch" ${data.settings.config.debug_source_ip?'checked':''}></label></section>`;}
function admin(){return pageHeading('ADMINISTRATION','用户管理。','管理账户权限与可用状态。学校密码不会在这里展示。')+`<div style="overflow:auto"><table class="admin-table"><thead><tr><th>账户</th><th>权限组</th><th>创建日期</th><th>状态</th><th>管理</th></tr></thead><tbody>${adminUsers.map(u=>`<tr><td>${esc(u.username)}<small>${esc(u.student_name||'未同步学校姓名')}</small></td><td><select data-role-user="${u.id}" aria-label="${esc(u.username)}权限组"><option value="user" ${u.role==='user'?'selected':''}>普通用户</option><option value="admin" ${u.role==='admin'?'selected':''}>管理员</option></select></td><td>${fmt(u.created_at,true)}</td><td>${u.disabled?'已停用':'可用'}</td><td><button class="button small ${u.disabled?'':'danger'}" data-action="toggle-user" data-user="${u.id}" data-disabled="${u.disabled?'0':'1'}">${u.disabled?'启用':'停用'}</button></td></tr>`).join('')}</tbody></table></div>`;}
function aboutContent(){return `<section class="panel about-card"><div class="about-identity"><span class="brand-mark" aria-hidden="true"><svg class="brand-symbol" viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8 21c6-2 11-1 16 3 5-4 10-5 16-3v18c-6-2-11-1-16 3-5-4-10-5-16-3Z" fill="currentColor" fill-opacity=".07"/><path d="M24 24v18M12 27c3-.4 5 .1 8 1.7m-8 4.1c3-.4 5 .1 8 1.7m8-5.8c3-1.6 5-2.1 8-1.7m-8 7.5c3-1.6 5-2.1 8-1.7"/><circle cx="24" cy="12" r="4" fill="currentColor" fill-opacity=".16"/><path d="M24 3v2M14.8 7.3l1.6 1.1M33.2 7.3l-1.6 1.1M16 15.5l-1.8.8m17.8-.8 1.8.8"/></svg></span><div><span class="eyebrow">KOMA / ABOUT</span><h2>课间 · KOMA</h2><span class="muted">v${esc(bootstrap?.version||'—')}</span></div></div><p class="about-description">将学校的教学课表与实验课表整理成日历订阅。自动同步安排，让每天的课程清楚、有序。</p><dl class="about-details"><div><dt>构建日期</dt><dd>${esc(buildDateLabel(bootstrap).replace(/^构建(?:于 |日期：)/,''))}</dd></div><div><dt>开发者</dt><dd>安稳</dd></div><div><dt>GitHub</dt><dd><a class="about-link" href="https://github.com/liuayueeryuan0313" target="_blank" rel="noopener noreferrer">liuayueeryuan0313 <span aria-hidden="true">↗</span></a></dd></div><div><dt>Telegram</dt><dd><a class="about-link" href="https://t.me/aweodev" target="_blank" rel="noopener noreferrer">@aweodev <span aria-hidden="true">↗</span></a></dd></div></dl><div class="about-update"><button class="button small" data-action="check-updates">检测更新</button><span class="muted">只检测正式版本</span></div><p class="about-note">非学校官方工具，课程安排以学校公布的信息为准。</p></section>`;}
function buildDateLabel(info){
 const date=info?.build_date?new Date(info.build_date):null;
 if(!date||!Number.isFinite(date.getTime()))return '构建日期：待构建（开发预览）';
 return '构建于 '+new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(date);
}
function renderAppMetadata(info){
 $$('[data-app-version]').forEach(el=>el.textContent='v'+(info?.version||'—'));
 $$('[data-build-date]').forEach(el=>{const label=buildDateLabel(info);el.textContent=label;el.title=label.startsWith('构建于 ')?'构建时间（北京时间）：'+fmt(info.build_date):'本地源码预览，正式构建时自动记录日期';});
 $$('.auth-build-info').forEach(el=>el.hidden=false);
}
function updateVersionBadge(){
 const version=bootstrap?.version||'—',button=$('#version-status');
 $$('[data-app-version]').forEach(el=>el.textContent='v'+version);
 if(!button)return;
 const state=updateChecking?'checking':updateState?.status||'unknown';
 button.dataset.state=state;button.disabled=updateChecking;button.setAttribute('aria-busy',String(updateChecking));
 $('.version-update-label',button).hidden=state!=='available';
 button.setAttribute('aria-label',`当前版本 v${version}，${state==='available'?'有新版本可更新':state==='current'?'已是最新正式版本':state==='checking'?'正在检测更新':'点击检测更新'}`);
 button.title=state==='available'?`发现 v${updateState.latest_version}，点击查看`:state==='current'?'已是最新正式版本，点击重新检测':'点击检测更新';
}
async function checkUpdates(showResult=true){
 if(updateChecking)return;
 updateChecking=true;updateVersionBadge();
 try{
  updateState=await api('/api/updates');
  if(showResult){
   const status=updateState.status,title=status==='available'?'发现新版本':status==='current'?'当前已是最新正式版本':'暂时无法检测更新';
   modal(title,`<p>当前版本：v${esc(updateState.current_version)}${updateState.latest_version?`<br>最新正式版本：v${esc(updateState.latest_version)}`:''}</p>${updateState.message?`<p>${esc(updateState.message)}</p>`:''}${status==='available'?'<p>请查看发布说明后再决定更新。</p>':''}`,`<a class="button ${status==='available'?'primary':''}" href="${esc(updateState.release_url)}" target="_blank" rel="noopener noreferrer">查看发布页 ↗</a>`);
  }
 }catch(error){updateState={status:'error'};if(showResult)toast(error.message,true);}
 finally{updateChecking=false;updateVersionBadge();}
}
function renderAvatar(){
 const avatar=$('#account-avatar');if(!avatar||!data)return;
 const version=data.user.avatar_version||'',initial=(data.user.student_name||data.user.username).slice(0,1);
 if(avatar.dataset.avatarVersion===version&&avatar.dataset.initial===initial)return;
 avatar.dataset.avatarVersion=version;avatar.dataset.initial=initial;
 avatar.innerHTML=version?`<img src="/api/account/avatar?v=${esc(version)}" alt="">`:esc(initial);
}
function avatarEditor(){
 const version=data.user.avatar_version;
 modal('更换头像',`<form id="avatar-form" class="avatar-form"><div class="avatar-preview">${version?`<img src="/api/account/avatar?v=${esc(version)}" alt="头像预览">`:`<span>${esc((data.user.student_name||data.user.username).slice(0,1))}</span>`}</div><label class="button avatar-file">选择图片<input type="file" name="avatar" accept="image/png,image/jpeg,image/webp" aria-label="选择头像图片"></label><p class="field-help">PNG、JPG 或 WebP，最大 5 MB。自动居中裁剪。</p><p id="avatar-error" class="form-error" role="alert"></p><div class="avatar-actions"><button type="submit" class="button primary" disabled>保存</button>${version?'<button type="button" class="text-button" data-action="reset-avatar">恢复默认</button>':''}</div></form>`);
}
async function prepareAvatar(input){
 const form=input.form,file=input.files?.[0];if(!file)return;
 const selection=String(Number(form.dataset.selection||0)+1);form.dataset.selection=selection;
 const error=$('#avatar-error',form),save=$('[type=submit]',form);error.textContent='';save.disabled=true;delete form.dataset.image;
 if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>5*1024*1024){error.textContent='请选择 5 MB 以内的 PNG、JPG 或 WebP 图片';return;}
 try{
  const bitmap=await createImageBitmap(file);
  if(!form.isConnected||form.dataset.selection!==selection){bitmap.close();return;}
  const canvas=document.createElement('canvas');canvas.width=canvas.height=192;
  const side=Math.min(bitmap.width,bitmap.height);
  canvas.getContext('2d').drawImage(bitmap,(bitmap.width-side)/2,(bitmap.height-side)/2,side,side,0,0,192,192);bitmap.close();
  const image=canvas.toDataURL('image/png');
  if(image.length>218480)throw Error();
  form.dataset.image=image;$('.avatar-preview',form).innerHTML=`<img src="${image}" alt="头像预览">`;save.disabled=false;
 }catch{if(form.isConnected&&form.dataset.selection===selection)error.textContent='图片无法读取，请换一张图片';}
}
function render(){
 if(!data)return;
 $('#account-name').textContent=data.user.student_name||data.user.username;renderAvatar();$('#account-role').textContent=data.user.role==='admin'?'管理员 / ADMIN':'普通用户 / MEMBER';$('#admin-nav').hidden=data.user.role!=='admin';$('#page-label').textContent=labels[page];$$('[data-page]').forEach(el=>el.classList.toggle('active',el.dataset.page===page));$('#top-date').textContent=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',weekday:'short'}).format(new Date());
 $('#content').innerHTML=({overview,timetable,subscriptions,logs,settings,debug,admin}[page]||overview)();enterPage();document.dispatchEvent?.(new Event('koma:render'));
}
async function navigate(next){page=next;if(next==='admin'){adminUsers=(await api('/api/admin/users')).users;}render();window.scrollTo({top:0,behavior:'instant'});}
function arrangementDetails(row){
 return `<dl class="arrangement-details"><dt>课程</dt><dd>${esc(row.name)}</dd><dt>时间</dt><dd>${esc(row.date)} ${esc(row.startLocal?.slice(11,16))}–${esc(row.endLocal?.slice(11,16))}</dd><dt>地点</dt><dd>${esc(row.location||'未填写')}</dd><dt>教师</dt><dd>${esc(row.teacher||'未填写')}</dd>${row.projectName?`<dt>实验项目</dt><dd>${esc(row.projectName)}</dd>`:''}</dl>`;
}
function lessonComparison(row){
 if(row?.origin!=='override')return '';
 const pending=!!row.conflictFields?.length;
 return `<section class="lesson-comparison ${pending?'pending':''}"><h3>${pending?'学校安排有变更，请核对':'这次课程有手动修改'}</h3>${row.schoolMissing?'<p>学校已取消此安排，或本次同步无法唯一匹配。你的修改暂时保留。</p>':''}<div class="arrangement-grid"><div><strong>学校最新安排</strong>${row.schoolArrangement?arrangementDetails(row.schoolArrangement):'<p>当前无对应安排</p>'}</div><div><strong>你的安排</strong>${arrangementDetails(row)}</div></div><div class="resolution-actions"><button type="button" class="button small" data-action="restore-lesson" data-kind="${row.kind}" data-id="${row.occurrenceId}" data-revision="${row.revision||''}">恢复学校安排</button>${pending?`<button type="button" class="button small primary" data-action="keep-lesson" data-kind="${row.kind}" data-id="${row.occurrenceId}" data-revision="${row.revision||''}">保留我的修改</button>`:''}</div></section>`;
}
function lessonEditor(row=null){
 editingLessonKey=row?row.kind+':'+row.occurrenceId:'new';
 const c=data.settings.config,kind=row?.kind||(kindFilter==='lab'?'lab':'teaching');
 const options=(max,selected)=>Array.from({length:max},(_,i)=>`<option value="${i+1}" ${Number(selected)===i+1?'selected':''}>${i+1}</option>`).join('');
 const periods=[...new Set([...Object.keys(c.periods||{}),...Object.keys(c.period_ranges||{}).flatMap(range=>range.split('-'))].map(Number))].sort((a,b)=>a-b);
 const periodOptions=selected=>periods.map(n=>`<option value="${n}" ${Number(selected)===n?'selected':''}>第 ${n} 节</option>`).join('');
 const input=(key,label,value='',required=false)=>`<label>${label}<input name="${key}" value="${esc(value)}" maxlength="200" ${required?'required':''}></label>`;
 modal(row?'编辑本次课程':'手动新建课程',`${lessonComparison(row)}<form id="lesson-form" class="form-stack" data-revision="${esc(row?.revision||'')}" data-id="${esc(row?.occurrenceId||'')}" data-kind="${kind}"><p class="field-help">保存后更新课表与 ICS 订阅。本次手动修改会保留，未修改的字段继续跟随学校更新。</p><label>课表类型<select name="kind" ${row?'disabled':''}><option value="teaching" ${kind==='teaching'?'selected':''}>教学</option><option value="lab" ${kind==='lab'?'selected':''}>实验</option></select></label>${input('name','课程名称',row?.name||'',true)}<div class="field-row"><label>教学周<select name="week">${options(c.maxWeekNumber,row?.week||week)}</select></label><label>星期<select name="weekday">${Array.from({length:7},(_,i)=>`<option value="${i+1}" ${Number(row?.weekday||1)===i+1?'selected':''}>星期${'一二三四五六日'[i]}</option>`).join('')}</select></label></div><div class="field-row"><label>开始节次<select name="startPeriod">${periodOptions(row?.startPeriod||periods[0])}</select></label><label>结束节次<select name="endPeriod">${periodOptions(row?.endPeriod||periods[1]||periods[0])}</select></label></div>${input('location','地点',row?.location||'')}${input('teacher','教师',row?.teacher||'')}<fieldset id="lesson-lab-fields" ${kind==='lab'?'':'hidden disabled'}>${input('courseName','实验所属课程',row?.courseName||'')}${input('projectName','实验项目',row?.projectName||'')}</fieldset><p class="field-help">起止时间按当前学校作息计算，使用北京时间。</p><button type="submit" class="button primary">保存课程</button></form>`);
 $$('.lesson[aria-expanded],.lesson-create[aria-expanded]').forEach(button=>button.setAttribute('aria-expanded',String(button.dataset.action==='new-lesson'?editingLessonKey==='new':editingLessonKey===button.dataset.kind+':'+button.dataset.id)));
}
document.addEventListener('close',event=>{
 if(event.target.id!=='modal')return;
 const recoveryForm=$('.recovery-form',$('#modal-content'));if(recoveryForm){recoveryForm.reset();$('#modal-content').innerHTML='';}
 editingLessonKey='';
 $$('.lesson[aria-expanded],.lesson-create[aria-expanded]').forEach(button=>button.setAttribute('aria-expanded','false'));
},true);
function recoveryEntries(values){
 const entries=[0,1].map(index=>({question:values['question'+index],answer:values['answer'+index]}));
 if(entries[0].question===entries[1].question)throw Error('请选择两道不同的密保问题');
 return entries;
}
function recoverySetup(mode='register'){
 const questions=bootstrap.recovery_questions||[];
 const fields=[0,1].map(index=>`<section class="recovery-question"><span class="recovery-number">0${index+1}</span><div><label>密保问题 ${index+1}<select name="question${index}" required>${questions.map((question,q)=>`<option value="${esc(question.id)}" ${q===index?'selected':''}>${esc(question.label)}</option>`).join('')}</select></label><label>密保答案 ${index+1}<input name="answer${index}" type="password" autocomplete="off" spellcheck="false" minlength="2" maxlength="128" placeholder="填写只有你记得的答案" required></label></div></section>`).join('');
 modal(mode==='register'?'为账户留一把备用钥匙。':'设置密保问题',`<form id="recovery-setup-form" class="form-stack recovery-form" data-mode="${mode}"><p class="panel-description">选择两道不同的问题。找回时需答对两题；请使用不易被别人猜到的答案，不要重复站内密码，并妥善记住。</p>${mode==='settings'?'<label>当前站内密码<input name="current_password" type="password" autocomplete="current-password" required maxlength="256"></label>':''}${fields}<p id="recovery-error" class="form-error" role="alert"></p><button type="submit" class="button primary">${mode==='register'?'保存密保并创建账户':'保存密保'}</button></form>`,mode==='register'?'<button type="button" class="button" data-action="skip-recovery">稍后设置并创建账户</button>':'');
}
async function finishRegistration(recovery=null){
 if(registrationBusy)return;
 const form=$('#auth-form');if(!form.checkValidity())throw Error('请关闭弹窗，先填写有效的用户名与站内密码');
 const values=Object.fromEntries(new FormData(form));
 if(!values.consent)throw Error('请先阅读并同意使用说明与免责声明');
 registrationBusy=true;$$('#modal button').forEach(button=>button.disabled=true);
 try{
  const result=await api('/api/register',{method:'POST',body:JSON.stringify({...values,consent:true,recovery})});
  csrf=result.csrf;form.reset();$('#modal').close();await refresh(true);showWorkspace();
 }finally{registrationBusy=false;$$('#modal button').forEach(button=>button.disabled=false);}
}
function forgotPassword(){
 modal('找回站内密码',`<form id="recovery-lookup-form" class="form-stack recovery-form"><p class="panel-description">输入账户名，回答注册时设置的两道密保问题，即可重设站内密码。</p><label>账户名<input name="username" autocomplete="username" minlength="3" maxlength="32" value="${esc($('#auth-form [name=username]').value)}" required></label><p id="recovery-error" class="form-error" role="alert"></p><button class="button primary" type="submit">下一步 · 回答密保</button><p class="field-help">尚未设置密保、忘记答案，或管理员账户，请联系站点管理员处理。</p></form>`);
}
function recoveryReset(username,questions){
 const fields=questions.map((question,index)=>`<label>${esc(question.label)}<input type="hidden" name="question${index}" value="${esc(question.id)}"><input name="answer${index}" type="password" autocomplete="off" minlength="2" maxlength="128" required placeholder="请输入密保答案"></label>`).join('');
 modal('回答密保，重新登录。',`<form id="recovery-reset-form" class="form-stack recovery-form"><p class="panel-description">两道答案都需正确。成功后，所有旧登录会话将退出。</p><label>账户名<input name="username" value="${esc(username)}" readonly autocomplete="username"></label>${fields}<div class="recovery-divider"></div><label>新站内密码<input name="new_password" type="password" autocomplete="new-password" minlength="10" maxlength="256" placeholder="至少10个字符" required></label><label>再次输入新密码<input name="confirm_password" type="password" autocomplete="new-password" minlength="10" maxlength="256" required></label><p id="recovery-error" class="form-error" role="alert"></p><button class="button primary" type="submit">验证并重设密码</button><button type="button" class="text-button recovery-back" data-action="forgot-password">返回修改账户名</button></form>`);
}
async function sync(scope,initialize=false){await api('/api/sync',{method:'POST',body:JSON.stringify({scope,initialize_app:initialize,ack_app_relogin:initialize})});toast('已开始向学校平台同步课表');await refresh(true);}
async function copy(text){if(navigator.clipboard)await navigator.clipboard.writeText(text);else{const field=document.createElement('textarea');field.value=text;document.body.append(field);field.select();document.execCommand('copy');field.remove();}toast('订阅地址已复制');}
document.addEventListener('click',async event=>{
 const target=event.target.closest('[data-action],[data-page],[data-auth],[data-kind-filter],[data-log-filter],[data-subscription-tab]');if(!target)return;
 try{
  if(target.dataset.subscriptionTab){subscriptionTab=target.dataset.subscriptionTab;render();$('#'+subscriptionTab+'-tab').focus();return;}
  if(target.dataset.auth)return setAuthMode(target.dataset.auth);
  if(target.dataset.page)return await navigate(target.dataset.page);
  if(target.dataset.action==='about')return modal('关于课间',aboutContent());
  if(target.dataset.kindFilter){kindFilter=target.dataset.kindFilter;return render();}
  if(target.dataset.logFilter){logFilter=target.dataset.logFilter;return render();}
  const action=target.dataset.action;
  if(action==='change-avatar')return avatarEditor();
  if(action==='reset-avatar'){await api('/api/account/avatar',{method:'PUT',body:JSON.stringify({image:null})});$('#modal').close();await refresh();renderAvatar();return toast('已恢复默认头像');}
  if(action==='forgot-password')return forgotPassword();
  if(action==='register-recovery')return recoverySetup('register');
  if(action==='setup-recovery')return recoverySetup('settings');
  if(action==='skip-recovery'){
   try{return await finishRegistration();}catch(error){$('#recovery-error').textContent=error.message;return;}
  }
  if(action==='recovery-login'){$('#modal').close();data=null;showAuth();$('#auth-form [name=password]').value='';return;}
  if(action==='check-updates')return await checkUpdates();
  if(action==='new-lesson')return lessonEditor();
  if(action==='edit-lesson'){const row=data.occurrences.find(r=>r.kind===target.dataset.kind&&r.occurrenceId===target.dataset.id);if(!row)throw Error('课程已变更，请刷新后再编辑');return lessonEditor(row);}
  if(action==='restore-lesson'){
   const row=data.occurrences.find(r=>r.kind===target.dataset.kind&&r.occurrenceId===target.dataset.id);
   return modal('恢复学校安排？',`<p>${row?.schoolMissing?'学校当前没有可对应的安排，恢复后将移除此课次的手动覆盖。':'将撤销本次课程的全部手动修改，使用学校最新安排。'}</p>`,`<button class="button primary" data-action="confirm-restore-lesson" data-kind="${target.dataset.kind}" data-id="${target.dataset.id}" data-revision="${target.dataset.revision}">确认恢复</button>`);
  }
  if(action==='keep-lesson'||action==='confirm-restore-lesson'){
   await api('/api/occurrences/'+target.dataset.kind+'/'+target.dataset.id+'/'+(action==='keep-lesson'?'keep':'restore'),{method:'POST',body:JSON.stringify({revision:target.dataset.revision})});
   editingLessonKey='';$('#modal').close();await refresh(true);return toast(action==='keep-lesson'?'已保留你的修改':'已恢复学校安排');
  }
  if(action==='disclaimer')return disclaimer();
  if(action==='ack-disclaimer'){try{localStorage.setItem('koma.disclaimer.version',bootstrap.disclaimer_version);}catch{}return $('#modal').close();}
  if(action==='close-modal')return $('#modal').close();
  if(action==='logout'){await api('/api/logout',{method:'POST',body:'{}'});data=null;return showAuth();}
  if(action==='platform-test')return await platformAction(target.dataset.platform,'test');
  if(action==='platform-login'){
   if(target.dataset.platform==='app')return modal('登录获取 App token','<p>将保存当前填写的学校凭据，并登录 App 获取新 token，可能使手机 App 退出。测试和同步仅复用 token，不会触发 App 登录。</p><label class="check-label"><input id="ack-app" type="checkbox">我接受本次登录可能影响手机会话</label>','<button class="button primary" id="confirm-app" data-action="confirm-platform-login" disabled>登录并保存 token</button>');
   return await platformAction(target.dataset.platform,'login');
  }
  if(action==='confirm-platform-login'){$('#modal').close();return await platformAction('app','login',true);}
  if(action==='sync')return await sync(target.dataset.scope);
  if(action==='cat'){target.classList.remove('nod');void target.offsetWidth;target.classList.add('nod');return;}
  if(action==='prev-week'||action==='next-week'){week=Math.min(data.settings.config.maxWeekNumber,Math.max(1,week+(action==='prev-week'?-1:1)));return render();}
  if(action==='current-week'){week=currentWeek();return render();}
  if(action==='copy-link')return await copy(data.links[target.dataset.kind]);
  if(action==='rotate-link')return modal('更换这份订阅链接？','<p>旧链接会立即失效。你需要在日历应用中替换为新链接；课表内容保持。</p>',`<button class="button danger" data-action="confirm-rotate" data-kind="${target.dataset.kind}">更换链接</button>`);
  if(action==='confirm-rotate'){await api('/api/links/'+target.dataset.kind+'/rotate',{method:'POST',body:'{}'});editingLessonKey='';$('#modal').close();await refresh(true);return toast('链接已更换，旧链接已失效');}
  if(action==='app-init')return modal('重新授权校园 App','<p>这会使用已保存的校园密码登录App后台并取得新token，可能使手机App退出。日常自动更新会复用token，token失效时按教学来源设置处理。</p><label class="check-label"><input id="ack-app" type="checkbox">我接受本次登录可能影响手机会话</label>','<button class="button primary" id="confirm-app" data-action="confirm-app" disabled>登录并获取 token</button>');
  if(action==='confirm-app'){$('#modal').close();return await platformAction('app','login',true);}
  if(action==='clear-credentials')return modal('清除学校凭据？','<p>将删除保存的学校密码和App token。最近成功课表继续保留；重新配置前，学校同步会失败。</p>','<button class="button danger" data-action="confirm-clear">确认清除</button>');
  if(action==='confirm-clear'){await api('/api/settings',{method:'PUT',body:JSON.stringify({clear_credentials:true})});editingLessonKey='';$('#modal').close();await refresh();render();return toast('学校凭据已清除');}
  if(action==='change-password')return modal('修改站内密码','<form id="password-form" class="form-stack"><label>当前密码<input name="current_password" type="password" autocomplete="current-password" required></label><label>新密码<input name="new_password" type="password" autocomplete="new-password" minlength="10" required></label><button class="button primary" type="submit">保存并重新登录</button></form>');
  if(action==='toggle-user'){await api('/api/admin/users/'+target.dataset.user,{method:'PATCH',body:JSON.stringify({disabled:target.dataset.disabled==='1'})});return await navigate('admin');}
 }catch(error){toast(error.message,true);}
});
document.addEventListener('change',async event=>{
 const target=event.target;
 try{
  if(target.id==='debug-source-ip'){target.disabled=true;try{await api('/api/debug',{method:'PUT',body:JSON.stringify({show_source_ip:target.checked})});await refresh(true);}finally{target.disabled=false;}return;}
  if(target.form?.id==='avatar-form'&&target.name==='avatar'){await prepareAvatar(target);return;}
  if(target.form?.id==='lesson-form'&&target.name==='kind'){const fields=$('#lesson-lab-fields');fields.hidden=target.value!=='lab';fields.disabled=target.value!=='lab';return;}
  if(target.id==='reminder-enabled'){const input=$('#reminder-minutes');input.disabled=!target.checked;input.required=target.checked;$('#reminder-status').textContent=target.checked?'已开启':'已关闭';return;}
  if(target.id==='ack-app')$('#confirm-app').disabled=!target.checked;
  if(target.id==='school-profile'){const fields=$('#custom-school-fields');fields.hidden=target.value!=='custom';fields.disabled=target.value!=='custom';return;}
  if(target.id==='week-select'){week=Number(target.value);render();}
  if(target.id==='quick-mode'){await api('/api/settings',{method:'PUT',body:JSON.stringify({mode:target.value})});await refresh(true);toast('教学课表来源已保存');}
  if(target.dataset.roleUser){await api('/api/admin/users/'+target.dataset.roleUser,{method:'PATCH',body:JSON.stringify({role:target.value})});await navigate('admin');toast('权限组已更新');}
 }catch(error){toast(error.message,true);render();}
});
document.addEventListener('submit',async event=>{
 const form=event.target;event.preventDefault();const values=Object.fromEntries(new FormData(form));const button=$('[type=submit]',form);button.disabled=true;
 try{
  if(form.id==='avatar-form'){
   if(!form.dataset.image)throw Error('请先选择头像图片');
   await api('/api/account/avatar',{method:'PUT',body:JSON.stringify({image:form.dataset.image})});$('#modal').close();await refresh();renderAvatar();toast('头像已更新');
  }else if(form.id==='auth-form'){
   if(authMode==='register'){if(!values.consent)throw Error('请先阅读并同意使用说明与免责声明');return recoverySetup('register');}
   const result=await api('/api/'+authMode,{method:'POST',body:JSON.stringify({...values,consent:!!values.consent})});csrf=result.csrf;form.reset();await refresh(true);showWorkspace();
  }else if(form.id==='recovery-setup-form'){
   const recovery=recoveryEntries(values);
   if(form.dataset.mode==='register')await finishRegistration(recovery);
   else{await api('/api/account/recovery',{method:'PUT',body:JSON.stringify({current_password:values.current_password,recovery})});$('#modal').close();await refresh(true);render();toast('密保已保存，请妥善记住两道答案');}
  }else if(form.id==='recovery-lookup-form'){
   const result=await api('/api/recovery/questions',{method:'POST',body:JSON.stringify({username:values.username})});recoveryReset(values.username,result.questions);
  }else if(form.id==='recovery-reset-form'){
   if(values.new_password!==values.confirm_password)throw Error('两次输入的新密码不一致');
   await api('/api/recovery/reset',{method:'POST',body:JSON.stringify({username:values.username,answers:recoveryEntries(values),new_password:values.new_password})});
   $('#auth-form [name=username]').value=values.username;$('#auth-form [name=password]').value='';
   modal('密码已更新。','<p>请使用新密码重新登录课间。所有旧登录会话已失效。</p>','<button class="button primary" data-action="recovery-login">返回登录</button>');
  }else if(form.id==='settings-form'){
   const body={...values,...schoolFormValues(values),maxWeekNumber:Number(values.maxWeekNumber),teaching:{enabled:!!values.teaching_enabled,interval_minutes:Number(values.teaching_interval)},lab:{enabled:!!values.lab_enabled,interval_minutes:Number(values.lab_interval)}};
   await api('/api/settings',{method:'PUT',body:JSON.stringify(body)});await refresh();render();toast('设置已保存，学校密码已加密存储');
  }else if(form.id==='reminder-form'){
   const body={reminder_enabled:!!values.reminder_enabled,...('reminder_minutes' in values?{reminder_minutes:Number(values.reminder_minutes)}:{})};
   await api('/api/settings',{method:'PUT',body:JSON.stringify(body)});await refresh();toast('提醒设置已保存，订阅内容已更新');
  }else if(form.id==='lesson-form'){
   const kind=values.kind||form.dataset.kind,id=form.dataset.id;
   await api('/api/occurrences/'+kind+(id?'/'+id:''),{method:id?'PUT':'POST',body:JSON.stringify({...values,revision:form.dataset.revision})});
   week=Number(values.week);editingLessonKey='';$('#modal').close();await refresh(true);toast('课程已保存，课表和订阅内容已更新');
  }else if(form.id==='password-form'){
   await api('/api/account/password',{method:'POST',body:JSON.stringify(values)});$('#modal').close();data=null;showAuth();toast('密码已修改，请重新登录');
  }
 }catch(error){if(form.classList.contains('recovery-form')){$('#recovery-error').textContent=error.message;enterEffect($('#recovery-error'),null,{duration:160});}else if(form.id==='auth-form'){$('#auth-error').textContent=error.message;enterEffect(form,[{transform:'translateX(0)'},{transform:'translateX(-4px)'},{transform:'translateX(4px)'},{transform:'translateX(0)'}],{duration:180});}else toast(error.message,true);}
 finally{button.disabled=false;}
});
async function boot(){try{bootstrap=await api('/api/bootstrap');renderAppMetadata(bootstrap);renderClientIp(bootstrap);$('#setup-tab').hidden=!bootstrap.setup_required;$$('[data-auth=register]').forEach(el=>el.hidden=!bootstrap.registration_open);try{const session=await api('/api/session');csrf=session.csrf;await refresh(true);showWorkspace();}catch{showAuth();}maybeFirstUseNotice();}catch{ $('#loading').textContent='服务暂时不可用，请稍后刷新。';}}
setInterval(()=>{if(data&&!document.hidden)refresh().catch(()=>{});},4000);
boot();

document.addEventListener('keydown',event=>{if(!event.target.matches('[data-subscription-tab]')||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const next=event.key==='Home'?'ics':event.key==='End'?'caldav':event.target.dataset.subscriptionTab==='ics'?'caldav':'ics';$('[data-subscription-tab="'+next+'"]').click();});
