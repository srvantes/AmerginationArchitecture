const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function setup(user = null, {target = null, visible = false, summaryDenied = false} = {}) {
 const elements = new Map(), events = {}, toasts = [], requests = [];
 function element(id) {
  if (!elements.has(id)) elements.set(id, {children:[], attributes:{}, events:{}, hidden:true, open:false,
   append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children=nodes;},
   querySelector(){return element('account-name');},
   setAttribute(name,value){this.attributes[name]=value;},
   removeAttribute(name){delete this.attributes[name];},
   addEventListener(name,handler){this.events[name]=handler;},
   contains(node){return node === this || node === element('open-auth');},
   showModal(){this.open=true;}, close(){this.open=false;}, focus(){this.focused=true;}, remove(){this.removed=true;},
  });
  return elements.get(id);
 }
 const context=vm.createContext({
  $:element, dsUser:user, dsToken:user ? 'token' : null, profilePage:true, profileUserId:target, window:{}, Date,
  async dsApi(path){requests.push(path);if(path.startsWith('profile/')) return {id:target,username:'public-user',show_watchlist:visible};if(summaryDenied){const error=Error('Private');error.status=403;throw error;}return {completed:2,episodes_watched:24,reviews_written:1,watching:[{anime_source:'shikimori',anime_external_id:'20',anime_title:'Наруто',episodes_watched:3}]};},
  text(tag,value){const node=element('node-'+elements.size);node.textContent=value;return node;},
  safeUrl(value){try{const url=new URL(value);return ['http:','https:'].includes(url.protocol) ? url.href : null;}catch{return null;}},
  document:{createElement(){return element('node-'+elements.size);},createElementNS(ns){const node=element('node-'+elements.size);node.namespaceURI=ns;return node;},addEventListener(name,handler){events[name]=handler;}},
  toast(message){toasts.push(message);},
 });
 vm.runInContext('async function dsLogout(){dsUser=null;dsToken=null;window.accountAuthChanged();return true;}',context);
 const appSource=fs.readFileSync('backend/static/app.js','utf8');
 vm.runInContext(appSource.slice(appSource.indexOf('const ANIME_LETTERS'),appSource.indexOf('function normalize(')),context);
 vm.runInContext(fs.readFileSync('backend/static/account.js','utf8'),context);
 return {element,events,context,toasts,requests};
}
async function main() {
 const guest=setup(); vm.runInContext('window.openAccount()',guest.context);
 assert.equal(guest.element('auth-dialog').open,true);
 assert.equal(guest.element('account-menu').hidden,true);

 const app=setup({username:'srvnts',email:'test@example.com',email_verified:true,profile:{avatar_url:'https://example.com/avatar.png',bio:'Привет',nickname:'Ник'}});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(app.element('profile-anime-count').textContent,2);
 assert.equal(app.element('profile-episode-count').textContent,24);
 assert.equal(app.element('profile-watching').children[0].href,'/anime/naruto-20');
 assert.equal(app.element('account-name').textContent,'srvnts');
 assert.equal(app.element('account-avatar').children[1].src,'https://example.com/avatar.png');
 app.element('account-avatar').children[1].events.error();
 assert.equal(app.element('account-avatar').children[0].textContent,'S');
 assert.equal(app.element('profile-name').textContent,'Ник');
 vm.runInContext('window.openAccount()',app.context);
 assert.equal(app.element('account-menu').hidden,false);
 assert.equal(app.element('open-auth').attributes['aria-expanded'],'true');
 assert.equal(app.element('auth-dialog').open,false);
 app.events.click({target:app.element('outside')});
 assert.equal(app.element('account-menu').hidden,true);
 vm.runInContext('window.openAccount()',app.context);
 app.events.keydown({key:'Escape',preventDefault(){}});
 assert.equal(app.element('account-menu').hidden,true);
 assert.equal(app.element('open-auth').focused,true);
 vm.runInContext('window.openAccount()',app.context);
 await app.element('account-logout').events.click();
 assert.equal(app.element('account-menu').hidden,true);
 assert.equal(app.element('account-name').textContent,'Войти');
 assert.equal(app.element('profile-content').hidden,true);
 assert.equal(app.element('profile-login').hidden,false);

 const unsafe=setup({username:'user',email_verified:false,profile:{avatar_url:'javascript:alert(1)'}});
 assert.equal(unsafe.element('account-avatar').children.length,1);
 assert.equal(unsafe.element('account-verify').hidden,false);
 const uploaded=setup({username:'user',email_verified:true,profile:{avatar_url:'/media/avatars/123-abc.png'}});
 assert.equal(uploaded.element('account-avatar').children[1].src,'/media/avatars/123-abc.png');
 const publicClosed=setup(null,{target:'someone'}); await new Promise(resolve=>setImmediate(resolve));
 assert.equal(publicClosed.element('profile-name').textContent,'public-user');
 assert.equal(publicClosed.element('profile-edit').hidden,true);
 assert.equal(publicClosed.element('profile-account-panel').hidden,true);
 assert.equal(publicClosed.element('profile-email').textContent,'');
 assert.equal(publicClosed.element('profile-list-link').hidden,true);
 assert.equal(publicClosed.requests.length,1);
 assert.match(publicClosed.element('profile-library-status').textContent,/скрыты/);
 const publicOpen=setup(null,{target:'someone',visible:true});await new Promise(resolve=>setImmediate(resolve));
 assert.equal(publicOpen.element('profile-watching').children.length,1);
 assert.equal(publicOpen.element('profile-list-link').href,'/profile/someone/list');
 assert.equal(publicOpen.element('profile-edit').hidden,true);
 const closedAfterLoad=setup(null,{target:'someone',visible:true,summaryDenied:true});await new Promise(resolve=>setImmediate(resolve));
 assert.match(closedAfterLoad.element('profile-library-status').textContent,/скрыты/);
 assert.equal(closedAfterLoad.element('profile-watching').children.length,0);
 console.log('Account UI: guest login, dropdown, avatar fallback, profile, outside click, Escape and logout OK');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
