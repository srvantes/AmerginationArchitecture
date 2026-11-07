const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function setup({coarse=false,delayA=false}={}){
 const elements=new Map(),events={},windowEvents={},timers=new Map(),requests=[];let timerId=0,resolveA;
 const pendingA=new Promise(resolve=>resolveA=resolve);
 const document={activeElement:null,addEventListener(name,handler){events[name]=handler;}};
 function element(id){
  if(!elements.has(id))elements.set(id,{id,hidden:false,style:{},dataset:{},attributes:{},children:[],events:{},isConnected:true,
   append(...children){this.children.push(...children);for(const child of children)child.parent=this;},
   replaceChildren(...children){this.children=children;for(const child of children)child.parent=this;},
   contains(node){for(let current=node;current;current=current.parent)if(current===this)return true;return false;},
   closest(){return this.dataset.miniUser?this:this.parent?.closest()||null;},querySelector(){return {textContent:this.id};},
   setAttribute(name,value){this.attributes[name]=value;},removeAttribute(name){delete this.attributes[name];},
   addEventListener(name,handler){this.events[name]=handler;},
   getBoundingClientRect(){return this.id==='mini-profile-card'?{width:330,height:350}:{left:950,top:720,bottom:748};},
   scrollIntoView(){},
   focus(){document.activeElement=this;events.focusin?.({target:this});},
  });return elements.get(id);
 }
 const card=element('mini-profile-card');card.hidden=true;
 for(const id of ['mini-profile-title','mini-profile-username','mini-profile-bio','mini-profile-country','mini-profile-achievements','mini-profile-avatar','mini-profile-status','mini-profile-background'])card.append(element(id));
 const a=element('author-a'),b=element('author-b');a.dataset.miniUser='a';b.dataset.miniUser='b';
 const context=vm.createContext({$:element,document,AbortController,
  window:{innerWidth:1024,innerHeight:768,addEventListener(name,handler){windowEvents[name]=handler;}},
  setTimeout(handler,ms){timers.set(++timerId,{handler,ms});return timerId;},clearTimeout(id){timers.delete(id);},
  matchMedia(){return {matches:coarse};},
  text(tag,value,className){const node=element('node-'+elements.size);node.textContent=value;node.className=className;return node;},
  safeUrl(value){try{const u=new URL(value);return ['http:','https:'].includes(u.protocol)?u.href:null;}catch{return null;}},
  accountAvatar(target,user){target.textContent=user.username;},
  async dsApi(path,options){requests.push({path,options});if(delayA&&path.includes('/a/'))await pendingA;const id=path.includes('/a/')?'a':'b';return {profile:{username:'user-'+id,nickname:'Демо '+id,bio:'Привет',country:'Россия',mini_profile_background:id==='a'?'javascript:bad':'/media/avatars/shop-stars.gif',profile_theme:id==='b'?'aurora':null},achievements:[{title:'На связи',description:'Подтвердить почту.'}]};},
 });
 const account=fs.readFileSync('backend/static/account.js','utf8');
 vm.runInContext(account.slice(account.indexOf('function profileMediaSource('),account.indexOf('function accountRender(')),context);
 vm.runInContext(fs.readFileSync('backend/static/mini-profile.js','utf8'),context);
 function flush(ms){for(const [id,timer] of [...timers])if(timer.ms<=ms){timers.delete(id);timer.handler();}}
 return {element,events,windowEvents,requests,a,b,flush,resolveA,context};
}
function event(target,extra={}){return {target,relatedTarget:null,pointerType:'mouse',preventDefault(){this.prevented=true;},...extra};}
async function main(){
 const app=setup();app.events.pointerover(event(app.a));
 assert.equal(app.requests.length,0);app.flush(220);await tick();
 assert.equal(app.element('mini-profile-card').hidden,false);
 assert.equal(app.element('mini-profile-title').textContent,'Демо a');
 assert.equal(app.element('mini-profile-title').href,'/profile/a');
 assert.equal(app.element('mini-profile-background').hidden,true);
 assert.equal(app.element('mini-profile-card').style.left,'682px');
 assert.equal(app.element('mini-profile-card').style.top,'360px');
 app.events.pointerout(event(app.a));app.element('mini-profile-card').events.pointerenter();app.flush(220);
 assert.equal(app.element('mini-profile-card').hidden,false);
 app.element('mini-profile-card').events.pointerleave(event(app.element('mini-profile-card')));app.flush(180);
 assert.equal(app.element('mini-profile-card').hidden,true);
 const keyboard=event(app.a,{key:'ArrowDown'});app.events.keydown(keyboard);await tick();
 assert.equal(keyboard.prevented,true);
 assert.equal(app.element('mini-profile-title'),app.context.document.activeElement);
 const before=app.requests.length;app.events.keydown(event(app.element('mini-profile-title'),{key:'Escape'}));await tick();
 assert.equal(app.element('mini-profile-card').hidden,true);
 assert.equal(app.requests.length,before);
 assert.equal(app.context.document.activeElement,app.a);

 const phone=setup({coarse:true});phone.events.pointerover(event(phone.a,{pointerType:'touch'}));phone.flush(220);
 assert.equal(phone.requests.length,0);
 const tap=event(phone.a,{pointerType:'touch'});phone.events.click(tap);await tick();
 assert.equal(tap.prevented,true);assert.equal(phone.element('mini-profile-card').hidden,false);
 phone.events.click(event(phone.element('outside')));assert.equal(phone.element('mini-profile-card').hidden,true);
 const desktopClick=event(app.a);app.events.click(desktopClick);assert.notEqual(desktopClick.prevented,true);

 const stale=setup({delayA:true});stale.a.focus();stale.b.focus();await tick();stale.resolveA();await tick();
 assert.equal(stale.element('mini-profile-title').textContent,'Демо b');
 assert.equal(stale.element('mini-profile-background').src,'/media/avatars/shop-stars.gif');
 assert.equal(stale.element('mini-profile-background').hidden,false);
 assert.equal(stale.element('mini-profile-card').attributes['data-profile-theme'],'aurora');
 assert.equal(stale.requests[0].options.signal.aborted,true);
 stale.b.isConnected=false;stale.windowEvents.resize();assert.equal(stale.element('mini-profile-card').hidden,true);
 console.log('Mini profile UI: hover delay, pointer bridge, keyboard/Escape, touch, placement and stale responses OK');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
