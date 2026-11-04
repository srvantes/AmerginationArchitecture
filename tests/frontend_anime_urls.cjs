const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('backend/static/app.js','utf8');
const helpers=source.slice(source.indexOf('const ANIME_LETTERS'),source.indexOf('function normalize('));
const changed=[];
const context=vm.createContext({window:{history:{state:{test:true},replaceState(state,title,path){changed.push({state,path});}}},location:{pathname:'/anime/shikimori/877',search:'',hash:'#comments-panel'}});
vm.runInContext(helpers,context);
const run=code=>vm.runInContext(code,context);
assert.equal(run('animePath({source:"shikimori",external_id:"877",title:"Нана",original_title:"Nana"})'),'/anime/nana-877');
assert.equal(run('animePath({source:"animego",external_id:"877",title:"Нана",slug:"nana"})'),'/anime/nana-a877');
assert.equal(run('animePath({id:"saved-row-uuid",anime_source:"shikimori",anime_external_id:"20",anime_title:"Наруто"})'),'/anime/naruto-20');
assert.equal(run('animePath({source:"shikimori",id:"1",title:"Été / ?#<script>"})'),'/anime/ete-script-1');
assert.equal(run('animePath({source:"shikimori",id:"1",title:"日本語"})'),'/anime/anime-1');
for(const path of ['/anime/nana-877','/anime/wrong-title-877']){
 context.testPath=path;assert.equal(run('parseAnimeRoute(testPath).source'),'shikimori');assert.equal(run('parseAnimeRoute(testPath).id'),'877');
}
assert.equal(run('parseAnimeRoute("/anime/nana-a308").source'),'animego');
assert.equal(run('parseAnimeRoute("/anime/nana-a308").slug'),'nana');
assert.equal(run('parseAnimeRoute("/anime/308").source'),'animego');
assert.equal(run('parseAnimeRoute("/anime/shikimori/877").id'),'877');
for(const bad of ['/anime/nana-0','/anime/nana-01','javascript:alert(1)','/anime/nana-877?source=other']){
 context.testPath=bad;assert.equal(run('parseAnimeRoute(testPath)'),null);
}
assert.equal(run('animePath({source:"shikimori",id:"877",title:"Нана",public_path:"https://evil.example/anime/nana-877"})'),'/anime/nana-877');
assert.equal(run('animePath({source:"shikimori",id:"877",title:"Нана",public_path:"/anime/other-308"})'),'/anime/nana-877');
assert.equal(run('animePath({source:"animego",id:"877",title:"Нана",public_path:"/anime/nana-877"})'),'/anime/nana-a877');
assert.equal(run('animePath({source:"file",id:"877",title:"Нана"})'),null);
run('syncAnimeAddress({source:"shikimori",external_id:"877",title:"Нана",original_title:"Nana"})');
assert.equal(changed[0].path,'/anime/nana-877#comments-panel');assert.deepEqual(changed[0].state,{test:true});

async function testInit(path,expectedSource,expectedId,expectedSlug){
 const requests=[],rendered=[],elements=new Map();
 const ctx=vm.createContext({window:{},location:{pathname:path,search:''},URLSearchParams,sessionStorage:{getItem(){return null;}},
  $(id){if(!elements.has(id))elements.set(id,{});return elements.get(id);},
  async catalogApi(route,params){requests.push({route,params});return {identity:route};},renderDetail(page){rendered.push(page);}});
 vm.runInContext(helpers+';const pageRoute=parseAnimeRoute(location.pathname),pageId=pageRoute?.id,pageSource=pageRoute?.source;const collectionSlug=null,profilePage=false,listPage=false;'+source.slice(source.indexOf('async function init()'),source.indexOf("document.querySelectorAll('[data-scroll]')")),ctx);
 await vm.runInContext('init()',ctx);
 assert.equal(requests[0].route,expectedSource+'/'+expectedId);
 assert.equal(requests[0].params.slug,expectedSlug);
 assert.equal(rendered.length,1);
}
Promise.all([testInit('/anime/nana-877','shikimori','877',undefined),testInit('/anime/nana-a308','animego','308','nana')])
 .then(()=>console.log('Anime URLs: readable paths, provider collision isolation, legacy parsing, safe links, refresh and preserved anchors OK'))
 .catch(error=>{console.error(error);process.exitCode=1;});
