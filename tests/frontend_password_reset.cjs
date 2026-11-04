const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup({holdRequest = false} = {}) {
 const elements = new Map(), requests = [], storage = new Map(), toasts = [];
 let resolveRequest;
 const delayed = new Promise(resolve => {resolveRequest = resolve;});
 function element(id) {
  if (!elements.has(id)) elements.set(id, {
   value:'', hidden:false, disabled:false, open:true, textContent:'', events:{}, span:{textContent:''},
   addEventListener(name, handler) {this.events[name]=handler;}, querySelector(){return this.span;},
   showModal(){this.open=true;}, close(){this.open=false;}, focus(){},
  });
  return elements.get(id);
 }
 const context=vm.createContext({
  $:element, window:{addEventListener(){}}, Date, URLSearchParams,
  setInterval(){return 1;}, clearInterval(){}, toast(message){toasts.push(message);},
  sessionStorage:{getItem:k=>storage.get(k)||null, setItem:(k,v)=>storage.set(k,v), removeItem:k=>storage.delete(k)},
  fetch:async(url,options)=>{
   requests.push({url,options}); let status=200,data;
   if(url.endsWith('/password/request')) {
    if(holdRequest) await delayed;
    data={detail:'Если аккаунт существует, код отправлен.',expires_in_seconds:120,resend_after_seconds:120};
   } else if(url.endsWith('/password/verify')) {
    if(JSON.parse(options.body).code==='000123') data={reset_token:'one-time-reset-ticket',expires_in_seconds:300};
    else {status=400;data={detail:'Код неверен или истёк.'};}
   } else if(url.endsWith('/password/reset')) data={detail:'Пароль изменён. Войдите с новым паролем.'};
   else throw new Error('Unexpected endpoint '+url);
   return {status,ok:status===200,headers:{get(){return null;}},json:async()=>data};
  },
 });
 vm.runInContext(fs.readFileSync('backend/static/discussion.js','utf8'),context);
 vm.runInContext(fs.readFileSync('backend/static/password-reset.js','utf8'),context);
 return {element,requests,resolveRequest,context,toasts};
}
const event={preventDefault(){}};
async function requestCode(app) {
 app.element('auth-forgot').events.click();
 app.element('reset-email').value='owner@example.com';
 await app.element('reset-request-form').events.submit(event);
}
async function main() {
 const app=setup(); await requestCode(app);
 assert.equal(app.element('auth-form').hidden,true);
 assert.equal(app.element('reset-code-form').hidden,false);
 assert.equal(app.element('reset-resend').disabled,true);
 app.element('reset-code').value='000123'; await app.element('reset-code-form').events.submit(event);
 assert.equal(app.element('reset-password-form').hidden,false);
 app.element('reset-password').value='new-password-123'; app.element('reset-password-repeat').value='different';
 await app.element('reset-password-form').events.submit(event);
 assert.equal(app.requests.filter(r=>r.url.endsWith('/password/reset')).length,0);
 assert.equal(app.element('auth-dialog').open,true);
 app.element('reset-password-repeat').value='new-password-123';
 await app.element('reset-password-form').events.submit(event);
 assert.equal(app.element('password-reset-panel').hidden,true);
 assert.equal(app.element('auth-form').hidden,false);
 assert.equal(app.element('reset-password').value,'');
 assert.equal(app.element('reset-password-repeat').value,'');
 assert.equal(vm.runInContext('prToken',app.context),'');
 assert.equal(app.element('auth-dialog').open,false);
 assert.equal(app.element('auth-status').textContent,'');
 assert.match(app.toasts.at(-1),/Пароль изменён/);
 const payload=JSON.parse(app.requests.find(r=>r.url.endsWith('/password/reset')).options.body);
 assert.equal(payload.reset_token,'one-time-reset-ticket');

 const attempts=setup(); await requestCode(attempts);
 attempts.element('reset-code').value='999999';
 for(let i=0;i<5;i++) await attempts.element('reset-code-form').events.submit(event);
 assert.equal(attempts.element('reset-code-submit').disabled,true);

 const cancelled=setup({holdRequest:true});
 cancelled.element('auth-forgot').events.click(); cancelled.element('reset-email').value='owner@example.com';
 const pending=cancelled.element('reset-request-form').events.submit(event);
 cancelled.element('reset-back').events.click(); cancelled.resolveRequest(); await pending;
 assert.equal(cancelled.element('password-reset-panel').hidden,true);
 assert.equal(cancelled.element('auth-form').hidden,false);
 assert.equal(vm.runInContext('prStage',cancelled.context),'request');
 console.log('Password reset UI: three stages, confirmation mismatch, five attempts and cancellation OK');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
