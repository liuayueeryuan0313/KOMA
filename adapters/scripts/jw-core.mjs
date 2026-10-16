export const ORIGIN='https://jw.sdut.edu.cn';
export const PATH='/jwglxt/kbcx/xskbcx_cxXsgrkb.html';
export const PERIOD_PATH='/jwglxt/kbcx/xskbcx_cxRjc.html';
const COURSE_FIELDS=['kch','kch_id','kcmc','xqj','xqjmc','jcs','zcd','cdmc','xqmc','xm','jxbmc','xnm','xqm'];
export function sanitizeSchedule(payload){
 if(!payload||!Array.isArray(payload.kbList))throw Error('Expected kbList; login HTML, error or unknown schema must not replace old data');
 const pick=(row,keys)=>Object.fromEntries(keys.filter(k=>row[k]!==undefined).map(k=>[k,row[k]]));
 return {kbList:payload.kbList.map(r=>pick(r,COURSE_FIELDS)),sjkList:(payload.sjkList??[]).map(r=>pick(r,['kcmc','qsjsz','jsxm','xqmc']))};
}
export function sanitizePeriods(payload){
 if(!Array.isArray(payload))throw Error('Expected periods array');
 return payload.map(r=>({jcmc:r.jcmc,qssj:r.qssj,jssj:r.jssj}));
}
export function validateProfile(p){
 let origin;try{origin=new URL(p.origin);}catch{throw Error('SCHOOL_CONFIG_INVALID');}
 const prefix=p.contextPath??'/jwglxt';
 if(origin.protocol!=='https:'||origin.origin!==p.origin||(prefix!==''&&!/^\/(?:[A-Za-z0-9_-]+\/?)*$/.test(prefix))||p.path!==prefix+'/kbcx/xskbcx_cxXsgrkb.html'||p.periodsPath!==prefix+'/kbcx/xskbcx_cxRjc.html'||p.query?.gnmkdm!=='N2151')throw Error('SCHOOL_CONFIG_INVALID');
 for(const name of ['xnm','xqm','kzlx','xsdm','kclbdm','kclxdm'])if(typeof p.form?.[name]!=='string')throw Error('Invalid form profile');
 if(!p.calendarTerm||!Number.isInteger(p.maxWeekNumber)||p.maxWeekNumber<1||p.maxWeekNumber>53)throw Error('Invalid term profile');
 if(p.periodsForm?.xnm!==p.form.xnm||p.periodsForm?.xqm!==p.form.xqm)throw Error('Periods profile term mismatch');
}
