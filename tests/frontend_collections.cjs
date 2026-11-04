const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('backend/static/app.js','utf8'),html=fs.readFileSync('backend/static/index.html','utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const metadata=[['shounen','Сёнен'],['shoujo','Сёдзё'],['seinen','Сэйнэн'],['josei','Дзёсэй'],['fantasy','Фэнтези'],['comedy','Комедии'],['drama','Драмы'],['isekai','Исекай'],['romance','Романтика']].map(([slug,title])=>({slug,title,order:'ranked'}));
const card=number=>({source:'shikimori',external_id:String(number),title:'Аниме '+number,poster_url:'https://images.example/'+number+'.jpg',score:9.9-number/100,year:2026,kind:'TV'});
const collection=(slug,count=12)=>({slug,title:metadata.find(item=>item.slug===slug)?.title||slug,order:slug==='ongoing'?'popularity':'ranked',items:Array.from({length:count},(_,i)=>card(i+1))});
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
function setup({route='/',respond,observer=true}={}){
 const elements=new Map(),requests=[],observers=[],windowEvents={};let nextNode=0;
 function node(tag='div'){
  const classes=new Set();
  return {tag,children:[],events:{},attributes:{},dataset:{},textContent:'',hidden:false,disabled:false,clientWidth:1000,
   set id(value){this.nodeId=value;elements.set(value,this);},get id(){return this.nodeId;},
   classList:{add(value){classes.add(value);},remove(value){classes.delete(value);},contains(value){return classes.has(value);}},
   append(...children){this.children.push(...children);},replaceChildren(...children){this.children=children;},
   setAttribute(name,value){this.attributes[name]=value;},removeAttribute(name){delete this.attributes[name];},
   addEventListener(name,handler){this.events[name]=handler;},scrollBy(options){this.scrolled=options;},
   getBoundingClientRect(){return this.id==='shelf-shounen'?{top:300,bottom:700}:{top:10000,bottom:10400};},
  };
 }
 function element(id){if(!elements.has(id)){const item=node();item.id=id;}return elements.get(id);}
 for(const id of ['collection-page','profile-page','my-list-page','anime-page'])element(id).hidden=true;
 let responder=respond||((url)=>url.pathname.endsWith('/home')?{ongoing:[card(1)],popular:[card(2)],warnings:[],collections:metadata}:collection(url.pathname.split('/').at(-1),Number(url.searchParams.get('limit'))));
 const context=vm.createContext({window:{innerHeight:800,addEventListener(name,handler){windowEvents[name]=handler;}},location:{pathname:route,search:''},URL,URLSearchParams,AbortController,
  sessionStorage:{getItem(){return null;},setItem(){}},setTimeout,clearTimeout,matchMedia(){return {matches:true};},
  document:{title:'Amergination',documentElement:{clientHeight:800},getElementById:element,createElement:node,
   querySelectorAll(selector){return selector==='.site-header>nav a'?[element('nav-home'),element('nav-collections')]:[];}},
  async fetch(path,options){const url=new URL(path,'http://127.0.0.1:8080');requests.push({url,options});const result=await responder(url,options);const status=result?.httpStatus||200;return {ok:status<400,status,json:async()=>result?.httpStatus?result.body:result};},
 });
 if(observer)context.IntersectionObserver=class{
  constructor(callback,options){this.callback=callback;this.options=options;this.targets=new Set();observers.push(this);}
  observe(target){this.targets.add(target);}unobserve(target){this.targets.delete(target);}disconnect(){this.targets.clear();}
 };
 vm.runInContext(source,context);
 return {context,requests,element,observers,windowEvents,setResponder(fn){responder=fn;},run(code){return vm.runInContext(code,context);},
  visible(slugs,visible=true){const active=observers.at(-1);active.callback(slugs.map(slug=>({target:element('shelf-'+slug),isIntersecting:visible})));}};
}
const genreRequests=app=>app.requests.filter(request=>request.url.pathname.includes('/collections/'));
async function main(){
 // Existing shelf headings lead to full collections; a normal URL supports refresh.
 assert.match(html, /href="\/collections\/ongoing">Сейчас в эфире<\/a>/);
 assert.match(html, /href="\/collections\/popular">Стоит посмотреть<\/a>/);
 assert.match(html, /href="\/#thematic-collections" class="subtle">← На главную<\/a>/);

 const home=setup();await tick();
 const shelves=home.element('thematic-collections').children;
 assert.deepEqual(shelves.map(section=>section.id),metadata.map(item=>'shelf-'+item.slug));
 assert.deepEqual(shelves.map(section=>section.children[0].children[0].children[0].textContent),metadata.map(item=>item.title));
 assert.deepEqual(shelves.map(section=>section.children[0].children[0].children[0].href),metadata.map(item=>'/collections/'+item.slug));
 assert.equal(genreRequests(home).length,0); // Metadata does not eagerly fetch nine upstream lists.
 assert.equal(home.element('ongoing-track').children.length,1);
 assert.equal(home.element('collection-track').children.length,1);

 // Only two visible shelves load at once. An offscreen queued shelf waits for its next intersection.
 const first=deferred(),second=deferred();let active=0,maxActive=0;
 home.setResponder(async url=>{
  const slug=url.pathname.split('/').at(-1);++active;maxActive=Math.max(maxActive,active);
  try {if(slug==='shounen')await first.promise;if(slug==='shoujo')await second.promise;return collection(slug);}
  finally {--active;}
 });
 home.visible(['shounen','shoujo','seinen']);await tick();
 assert.equal(genreRequests(home).length,2);assert.equal(maxActive,2);
 assert.ok(genreRequests(home).every(request=>request.url.searchParams.get('limit')==='12'));
 home.visible(['seinen'],false);first.resolve();await tick();
 assert.equal(genreRequests(home).length,2);
 home.visible(['seinen']);await tick();assert.equal(genreRequests(home).length,3);assert.ok(maxActive<=2);
 second.resolve();await tick();
 assert.equal(home.element('track-shounen').children.length,12);
 assert.equal(home.element('track-shounen').children[0].href,'/anime/anime-1-1');
 assert.equal(home.element('shelf-shounen').children[1].textContent,'');

 // Re-observing/re-rendering a successful shelf uses the bounded client cache.
 const previous=genreRequests(home).length;
 home.run('renderThematicCollections('+JSON.stringify(metadata)+')');home.visible(['shounen']);await tick();
 assert.equal(genreRequests(home).length,previous);assert.equal(home.element('track-shounen').children.length,12);

 // A single genre error leaves its neighbours usable and retries only that genre.
 let failComedy=true;
 home.setResponder(url=>{const slug=url.pathname.split('/').at(-1);if(slug==='comedy'&&failComedy)throw Error('provider offline');return collection(slug,slug==='josei'?0:12);});
 home.visible(['comedy','drama','josei']);await tick();await tick();
 const comedy=home.element('shelf-comedy');assert.equal(comedy.children[2].hidden,false);assert.match(comedy.children[1].textContent,/Не удалось/);
 assert.equal(home.element('track-drama').children.length,12);assert.equal(home.element('ongoing-track').children.length,1);
 assert.equal(home.element('track-josei').hidden,true);assert.match(home.element('shelf-josei').children[1].textContent,/пока нет/);
 failComedy=false;comedy.children[2].events.click();await tick();
 assert.equal(comedy.children[2].hidden,true);assert.equal(home.element('track-comedy').children.length,12);
 assert.equal(genreRequests(home).filter(request=>request.url.pathname.endsWith('/comedy')).length,2);
 assert.ok(home.requests.every(request=>request.url.pathname.endsWith('/home')||request.url.pathname.includes('/collections/'))); // No requests per anime.

 // A standalone collection renders loading, then at most fifty cards with the correct ordering label.
 const pageGate=deferred();
 const page=setup({route:'/collections/fantasy',respond:()=>pageGate.promise});
 assert.equal(page.element('home').hidden,true);assert.equal(page.element('collection-page').hidden,false);
 assert.equal(page.element('collection-page-status').textContent,'Загружаем подборку…');
 assert.equal(page.element('collection-grid').attributes['aria-busy'],'true');
 assert.equal(page.requests.length,1);assert.equal(page.requests[0].url.searchParams.get('limit'),'50');
 pageGate.resolve(collection('fantasy',53));await tick();
 assert.equal(page.element('collection-grid').children.length,50);
 assert.equal(page.element('collection-page-title').textContent,'Фэнтези');
 assert.equal(page.element('collection-page-order').textContent,'По рейтингу Shikimori');
 assert.equal(page.element('collection-page-count').textContent,'Аниме: 50');assert.equal(page.context.document.title,'Фэнтези — Amergination');
 assert.equal(page.element('collection-grid').attributes['aria-busy'],'false');
 const ongoing=setup({route:'/collections/ongoing'});await tick();
 assert.equal(ongoing.element('collection-page-order').textContent,'По популярности');

 // Error/empty/unknown states are explicit; retry does not trigger a home-catalog load.
 let failPage=true;
 const retry=setup({route:'/collections/romance',respond:()=>{if(failPage)return {httpStatus:502,body:{detail:'unavailable'}};return collection('romance',4);}});await tick();
 assert.equal(retry.element('retry-collection-page').hidden,false);assert.equal(retry.element('collection-grid').children.length,0);
 failPage=false;await retry.element('retry-collection-page').events.click();
 assert.equal(retry.element('collection-grid').children.length,4);assert.equal(retry.element('retry-collection-page').hidden,true);
 assert.equal(retry.requests.length,2);assert.ok(retry.requests.every(request=>request.url.pathname.endsWith('/romance')));
 const empty=setup({route:'/collections/josei',respond:()=>collection('josei',0)});await tick();
 assert.match(empty.element('collection-page-status').textContent,/пока нет/);assert.equal(empty.element('retry-collection-page').hidden,true);
 const missing=setup({route:'/collections/no-such-genre',respond:()=>({httpStatus:404,body:{detail:'unknown'}})});await tick();
 assert.equal(missing.element('collection-page-title').textContent,'Подборка не найдена');
 assert.equal(missing.element('retry-collection-page').hidden,true);assert.equal(missing.element('collection-grid').children.length,0);

 // Browsers without IntersectionObserver still load only shelves near the viewport.
 const fallback=setup({observer:false});await tick();
 assert.equal(genreRequests(fallback).length,1);assert.ok(genreRequests(fallback)[0].url.pathname.endsWith('/shounen'));
 assert.equal(typeof fallback.windowEvents.scroll,'function');
 console.log('Collections UI: nine ordered lazy shelves, two concurrent lists, cache, isolated retry, direct pages with 50 cards and empty/404/loading states OK');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
