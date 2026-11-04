const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const entry={anime_source:'shikimori',anime_external_id:'21',anime_title:'Ван-Пис',poster_url:'https://images.example/one-piece.jpg',anime_slug:null,episode:1000,player:'kodik',translation_id:'7',translation_name:'AniMedia',updated_at:'2026-10-22T12:00:00Z'};
const anime={source:'shikimori',id:'21',title:'Ван-Пис',poster_url:entry.poster_url,slug:null};
const choice=episode=>({episode,player:'kodik',translation_id:'7',translation_name:'AniMedia'});
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
function setup({home=false,guest=false,respond}={}){
 const elements=new Map(),requests=[];
 function node(tag='div') {return {tag,children:[],events:{},attributes:{},hidden:false,disabled:false,textContent:'',
  append(...children){this.children.push(...children);},replaceChildren(...children){this.children=children;},
  setAttribute(name,value){this.attributes[name]=value;},addEventListener(name,handler){this.events[name]=handler;},remove(){this.removed=true;}};}
 for(const id of ['continue-section','continue-track','continue-history-status','retry-continue-history','playback-history-status','retry-playback-history']){const el=node();el.id=id;elements.set(id,el);}
 elements.get('continue-section').hidden=true;
 let responder=respond||((path,options)=>options.method==='PUT'?{...entry,...JSON.parse(options.body)}:path.includes('?')?[entry]:entry);
 const context=vm.createContext({window:{},location:{pathname:home?'/':'/anime/shikimori/21'},URL,URLSearchParams,
  dsUser:guest?null:{id:'owner'},dsToken:guest?null:'owner-token',$:id=>elements.get(id),
  text(tag,value,className){const el=node(tag);el.textContent=value;el.className=className;return el;},
  document:{createElement:node},
  safeUrl(value){try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)?url.href:null;}catch{return null;}},
  dsApi(path,options={}){requests.push({path,options,token:context.dsToken});return Promise.resolve().then(()=>responder(path,options));},
 });
 const appSource=fs.readFileSync('backend/static/app.js','utf8');
 vm.runInContext(appSource.slice(appSource.indexOf('const POSTER_FALLBACK_URL'),appSource.indexOf('function normalize(')),context);
 vm.runInContext(fs.readFileSync('backend/static/playback-history.js','utf8'),context);
 return {context,window:context.window,requests,element:id=>elements.get(id),setResponder(fn){responder=fn;},
  auth(user,token){context.dsUser=user?{id:user}:null;context.dsToken=token;return context.window.playbackHistoryAuthChanged();}};
}
async function main(){
 // Guests never read or write a private account history.
 const guest=setup({home:true,guest:true});await tick();
 assert.equal(await guest.window.playbackHistoryGet('shikimori','21'),null);
 assert.equal(await guest.window.playbackHistorySave(anime,choice(1)),null);
 assert.equal(guest.requests.length,0);assert.equal(guest.element('continue-section').hidden,true);

 // Cards show the stored episode and studio, use a normal detail URL and safe DOM text/images.
 const home=setup({home:true,respond:()=>[{...entry,anime_title:'<script>title</script>',anime_slug:'one-piece & <title>',poster_url:'javascript:alert(1)'},{...entry,anime_source:'file'}]});await tick();
 assert.equal(home.element('continue-section').hidden,false);
 const cards=home.element('continue-track').children;assert.equal(cards.length,1);
 assert.equal(cards[0].children[1].textContent,'<script>title</script>');
 assert.equal(cards[0].children[0].children.find(child=>child.tag==='img').src,'/static/images/poster-unavailable.svg');
 assert.equal(cards[0].children[0].children[2].textContent,'Серия 1000');
 assert.equal(cards[0].children[2].textContent,'Kodik · AniMedia');
 assert.equal(cards[0].href,'/anime/script-title-script-21#player-section');
 assert.ok(!cards[0].href.includes('episode='));

 // A stale response may not reveal one account's history after a logout/login.
 const listGate=deferred();let listNumber=0;
 const stale=setup({home:true,respond:()=>++listNumber===1?listGate.promise:[]});await tick();
 await stale.auth('other','other-token');assert.equal(stale.element('continue-section').hidden,true);
 listGate.resolve([entry]);await tick();assert.equal(stale.element('continue-track').children.length,0);
 assert.equal(stale.element('continue-section').hidden,true);
 await home.auth(null,null);assert.equal(home.element('continue-track').children.length,0);assert.equal(home.element('continue-section').hidden,true);

 // Empty history stays hidden; a real load failure is visible and can be retried.
 let failList=true;
 const retryList=setup({home:true,respond:()=>{if(failList)throw Error('offline');return [entry];}});await tick();
 assert.equal(retryList.element('retry-continue-history').hidden,false);assert.equal(retryList.element('continue-section').hidden,false);
 failList=false;await retryList.element('retry-continue-history').events.click();
 assert.equal(retryList.element('retry-continue-history').hidden,true);assert.equal(retryList.element('continue-track').children.length,1);

 // Only a 404 means "no saved selection". Provider/account failures propagate to restoration UI.
 const get=setup();get.setResponder(()=>{const error=Error('not found');error.status=404;throw error;});
 assert.equal(await get.window.playbackHistoryGet('shikimori','21'),null);
 get.setResponder(()=>{throw Error('offline');});await assert.rejects(get.window.playbackHistoryGet('shikimori','21'),/offline/);
 const getGate=deferred();get.setResponder(()=>getGate.promise);const pendingGet=get.window.playbackHistoryGet('shikimori','21');await tick();
 await get.auth('other','other-token');getGate.resolve(entry);assert.equal(await pendingGet,null);

 // Serialize saves: a late write for an older series cannot overwrite the latest choice.
 const writeGate=deferred();let writes=0;
 const save=setup({respond:(path,options)=>++writes===1?writeGate.promise:{...entry,...JSON.parse(options.body)}});
 const first=save.window.playbackHistorySave(anime,choice(1));const second=save.window.playbackHistorySave(anime,choice(2));await tick();
 assert.equal(save.requests.length,1);assert.equal(JSON.parse(save.requests[0].options.body).episode,1);
 writeGate.resolve({...entry,episode:1});await Promise.all([first,second]);
 assert.equal(save.requests.length,2);const last=JSON.parse(save.requests[1].options.body);
 assert.equal(last.episode,2);assert.equal(last.translation_id,'7');
 assert.ok(!('episodes_watched' in last));assert.ok(!('status' in last));assert.ok(!('embed_url' in last));
 assert.equal(save.requests[1].options.keepalive,true);

 // Save errors leave the player intact and retry the most recent failed choice only.
 save.setResponder(()=>{throw Error('offline');});assert.equal(await save.window.playbackHistorySave(anime,choice(7)),null);
 assert.equal(save.element('retry-playback-history').hidden,false);assert.match(save.element('playback-history-status').textContent,/Не удалось сохранить/);
 save.setResponder((path,options)=>({...entry,...JSON.parse(options.body)}));await save.element('retry-playback-history').events.click();
 assert.equal(JSON.parse(save.requests.at(-1).options.body).episode,7);assert.equal(save.element('retry-playback-history').hidden,true);
 assert.equal(save.element('playback-history-status').textContent,'');

 // Queued choices from the old login are dropped, while a new login saves independently.
 const oldGate=deferred();let oldWrites=0;
 const account=setup({respond:(path,options)=>++oldWrites===1?oldGate.promise:{...entry,...JSON.parse(options.body)}});
 const oldFirst=account.window.playbackHistorySave(anime,choice(1));const oldSecond=account.window.playbackHistorySave(anime,choice(2));await tick();
 await account.auth(null,null);await account.auth('other','other-token');
 await account.window.playbackHistorySave(anime,choice(4));
 assert.equal(account.requests.length,2);assert.equal(account.requests[1].token,'other-token');
 oldGate.reject(Error('old account offline'));await Promise.all([oldFirst,oldSecond]);
 assert.equal(account.requests.length,2);assert.equal(account.element('playback-history-status').textContent,'');
 assert.equal(account.element('retry-playback-history').hidden,true);
 console.log('Playback history UI: private cards, safe links, logout isolation, ordered writes, honest load failures and save retries OK');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
