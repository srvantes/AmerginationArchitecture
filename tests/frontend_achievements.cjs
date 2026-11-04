const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function setup({allEarned=false,failSave=false,holdOwn=false}={}){
 const elements=new Map(),requests=[],toasts=[];let resolveOwn;
 const pending=new Promise(resolve=>resolveOwn=resolve);
 function node(){return {children:[],events:{},attributes:{},hidden:false,disabled:false,open:false,
  set id(value){this.nodeId=value;elements.set(value,this);},get id(){return this.nodeId;},
  append(...children){this.children.push(...children);},replaceChildren(...children){this.children=children;},
  setAttribute(name,value){this.attributes[name]=value;},addEventListener(name,handler){this.events[name]=handler;},
  showModal(){this.open=true;},close(){this.open=false;},
 };}
 for(const id of ['profile-achievement-count','profile-achievement-cards','profile-achievement-status','achievement-dialog','achievement-catalog','achievement-settings','achievement-selection-count','achievement-save','achievement-save-status','achievement-form']){const item=node();item.id=id;}
 const codes=['email_verified','first_anime','ten_anime','eleven_likes','first_review'];
 const items=codes.map((code,i)=>({code,title:code,description:'Условие',target:i===2?10:i===3?11:1,progress:i<2||allEarned?1:0,
  awarded_at:i<2||allEarned?'2026-10-22T12:00:00Z':null,showcase_slot:i===0?1:null}));
 const context=vm.createContext({$:id=>elements.get(id)||null,window:{profileAchievementTarget:{userId:'owner',owner:true}},Date,
  document:{createElement:node},text(tag,value,className){const item=node();item.tag=tag;item.textContent=value;item.className=className;return item;},
  toast(value){toasts.push(value);},
  async dsApi(path,options={}){
   requests.push({path,options});
   if(options.method==='PUT'){
    if(failSave)throw Error('Не удалось сохранить');
    const codes=JSON.parse(options.body).codes;
    return codes.map((code,i)=>({...items.find(item=>item.code===code),showcase_slot:i+1}));
   }
   if(path==='profile/me/achievements'){if(holdOwn)await pending;return items.map(item=>({...item}));}
   return [{...items[0],showcase_slot:1}];
  },
 });
 vm.runInContext(fs.readFileSync('backend/static/achievements.js','utf8'),context);
 return {element:id=>elements.get(id),requests,toasts,context,resolveOwn};
}
const event={preventDefault(){}};
async function main(){
 const app=setup();await tick();
 assert.equal(app.element('profile-achievement-count').textContent,'2 / 5');
 app.element('achievement-settings').events.click();
 assert.equal(app.element('achievement-select-ten_anime').disabled,true);
 const first=app.element('achievement-select-first_anime');first.checked=true;first.events.change();
 await app.element('achievement-form').events.submit(event);
 assert.equal(app.element('achievement-dialog').open,false);
 assert.deepEqual(JSON.parse(app.requests.at(-1).options.body).codes,['email_verified','first_anime']);
 assert.equal(app.element('profile-achievement-cards').children.length,2);
 app.element('achievement-settings').events.click();first.checked=false;first.events.change();app.element('achievement-dialog').close();
 app.element('achievement-settings').events.click();
 assert.equal(app.element('achievement-select-first_anime').checked,true);
 for(const code of ['email_verified','first_anime']){const input=app.element('achievement-select-'+code);input.checked=false;input.events.change();}
 await app.element('achievement-form').events.submit(event);
 assert.equal(app.element('profile-achievement-cards').children.length,0);

 const full=setup({allEarned:true});await tick();full.element('achievement-settings').events.click();
 for(const code of ['first_anime','ten_anime','eleven_likes']){const input=full.element('achievement-select-'+code);input.checked=true;input.events.change();}
 assert.equal(full.element('achievement-select-first_review').disabled,true);
 assert.equal(full.element('achievement-selection-count').textContent,'Выбрано: 4 / 4');

 const failed=setup({failSave:true});await tick();failed.element('achievement-settings').events.click();
 await failed.element('achievement-form').events.submit(event);
 assert.equal(failed.element('achievement-dialog').open,true);
 assert.match(failed.element('achievement-save-status').textContent,/Не удалось/);

 const stale=setup({holdOwn:true});
 await stale.context.window.profileAchievementsChanged({userId:'other',owner:false});
 stale.resolveOwn();await tick();
 assert.equal(stale.element('achievement-settings').hidden,true);
 assert.equal(stale.element('profile-achievement-count').textContent,'');
 assert.equal(stale.element('profile-achievement-cards').children.length,1);
 stale.element('achievement-settings').events.click();
 assert.equal(stale.element('achievement-dialog').open,false);
 console.log('Achievements UI: earned-only selection, four slots, cancel, save failure, clear and stale private responses OK');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
