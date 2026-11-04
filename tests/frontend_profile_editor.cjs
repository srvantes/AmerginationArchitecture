const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function setup({failSettings=false}={}) {
 const elements=new Map(),requests=[],toasts=[];
 function element(id){
  if(!elements.has(id)) elements.set(id,{value:'',files:[],open:false,events:{},children:[],
   addEventListener(name,handler){this.events[name]=handler;},
   replaceChildren(...children){this.children=children;},focus(){},showModal(){this.open=true;},close(){this.open=false;this.events.close?.();},reset(){for(const [id,node] of elements) if(id.startsWith('profile-edit-')){node.value='';node.files=[];}},
  });return elements.get(id);
 }
 const user={id:'owner',username:'srvnts',profile:{nickname:'Имя',bio:'Текст',country:'Россия'}};
 const context=vm.createContext({$:element,dsUser:user,profileUserId:null,window:{},URL:{createObjectURL(){return 'blob:preview';},revokeObjectURL(){}},
  document:{createElement(){return element('node-'+elements.size);}},
  accountAvatar(target){target.replaceChildren('avatar');},accountRender(){context.window.profileEditorAuthChanged();},toast(value){toasts.push(value);},
  async dsApi(path,options){requests.push({path,options});if(path==='profile/avatar')return {...user.profile,avatar_url:'/media/avatars/new.png'};if(failSettings)throw Error('Не удалось сохранить текст');return {...user.profile,...JSON.parse(options.body)};},
 });
 vm.runInContext(fs.readFileSync('backend/static/profile-editor.js','utf8'),context);
 return {element,requests,toasts,user,context};
}
const event={preventDefault(){}};
async function main(){
 const app=setup();app.element('profile-edit').events.click();
 assert.equal(app.element('profile-edit-name').value,'Имя');
 app.element('profile-edit-name').value=' Новый ник ';app.element('profile-edit-bio').value='';
 app.element('profile-edit-visibility').checked=true;
 app.element('profile-edit-avatar').files=[{type:'image/png',size:100}];
 app.element('profile-edit-avatar').events.change();
 assert.equal(app.element('profile-editor-preview').children[0].src,'blob:preview');
 await app.element('profile-editor-form').events.submit(event);
 assert.equal(app.requests[0].options.headers['Content-Type'],'image/png');
 assert.equal(app.requests[1].path,'profile/settings');
 assert.equal(app.user.profile.nickname,'Новый ник');assert.equal(app.user.profile.bio,null);
 assert.equal(app.user.profile.show_watchlist,true);
 assert.equal(app.element('profile-editor-dialog').open,false);
 assert.equal(app.toasts.at(-1),'Профиль сохранён');
 const failed=setup({failSettings:true});failed.element('profile-edit').events.click();
 failed.element('profile-edit-name').value='Новый ник';
 await failed.element('profile-editor-form').events.submit(event);
 assert.equal(failed.element('profile-editor-dialog').open,true);
 assert.equal(failed.element('profile-edit-name').value,'Новый ник');
 assert.match(failed.element('profile-editor-status').textContent,/Не удалось/);
 const partial=setup({failSettings:true});partial.element('profile-edit').events.click();
 partial.element('profile-edit-avatar').files=[{type:'image/png',size:100}];
 await partial.element('profile-editor-form').events.submit(event);
 assert.match(partial.element('profile-editor-status').textContent,/Аватар сохранён/);
 assert.equal(partial.user.profile.avatar_url,'/media/avatars/new.png');
 const large=setup();large.element('profile-edit').events.click();
 large.element('profile-edit-avatar').files=[{type:'image/png',size:3*1024*1024}];large.element('profile-edit-avatar').events.change();
 assert.match(large.element('profile-editor-status').textContent,/до 2 МБ/);
 const logout=setup();logout.element('profile-edit').events.click();
 vm.runInContext('dsUser=null;window.profileEditorAuthChanged();',logout.context);
 assert.equal(logout.element('profile-editor-dialog').open,false);
 assert.equal(logout.element('profile-edit-name').value,'');
 const foreign=setup();vm.runInContext("profileUserId='someone-else';",foreign.context);
 foreign.element('profile-edit').events.click();
 assert.equal(foreign.element('profile-editor-dialog').open,false);
 console.log('Profile editor UI: preview, save, empty fields, failed save, partial save, size limit and logout OK');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
