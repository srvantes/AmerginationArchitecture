const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const tick = () => new Promise(resolve => setImmediate(resolve));
function setup({list = false, signedIn = true, delay = false, publicTarget = null} = {}) {
 const elements = new Map(), requests = [], toasts = [], listeners = {};
 const rows = Array.from({length: 21}, (_, i) => ({id: 'entry-' + i, anime_source:'shikimori', anime_external_id:String(i+1), anime_title:'Аниме ' + i, status:'planned', episodes_watched:0, poster_url:'https://example.com/poster.png'}));
 let resolve;
 const pending = new Promise(done => {resolve = done;});
 function element(id) {
  if (!elements.has(id)) elements.set(id, {hidden:false, disabled:false, open:false, value:'', children:[], events:{}, attributes:{},
   addEventListener(name, handler){this.events[name] = handler;},
   setAttribute(name, value){this.attributes[name] = value;},
   append(...children){this.children.push(...children);},
   replaceChildren(...children){this.children = children;},
   showModal(){this.open = true;}, close(){this.open = false;}, remove(){this.removed=true;},
  });
  return elements.get(id);
 }
 const context = vm.createContext({
  $:element, listPage:list, publicListUserId:publicTarget, dsToken:signedIn ? 'token' : null, dsUser:signedIn ? {id:'owner'} : null,
  window:{watchlistAnime:list ? null : {source:'animego', id:'500', title:'Наруто'}, addEventListener(name, handler){listeners[name] = handler;}},
  document:{createElement(){return element('node-' + elements.size);}, querySelectorAll(){return [];}},
  URL, URLSearchParams, toast(message){toasts.push(message);},
  sessionStorage:{getItem(){return null;}},
  safeUrl(value){try{const url=new URL(value);return ['https:','http:'].includes(url.protocol)?url.href:null;}catch{return null;}},
  text(tag, value, className){const node = element('node-' + elements.size); node.tag = tag; node.textContent = value; node.className = className; return node;},
  selectOptions(select, options){select.options = options; select.value = options[0][0];},
  async dsApi(path, options = {}) {
   requests.push({path, options});
   const [route, query] = path.split('?'), params = new URLSearchParams(query);
   if (!options.method) {
    if (delay) await pending;
    let found = rows.filter(row => (!params.has('status') || row.status === params.get('status')) && (!params.has('anime_source') || row.anime_source === params.get('anime_source')) && (!params.has('anime_external_id') || row.anime_external_id === params.get('anime_external_id')));
    const offset = Number(params.get('offset') || 0); return found.slice(offset, offset + Number(params.get('limit') || 20));
   }
   if (options.method === 'POST') { const entry = {id:'new-entry', ...JSON.parse(options.body)}; rows.push(entry); return entry; }
   const id = route.split('/').at(-1), entry = rows.find(row => row.id === id);
   assert.ok(entry);
   if (options.method === 'DELETE') { rows.splice(rows.indexOf(entry), 1); return null; }
   Object.assign(entry, JSON.parse(options.body)); return entry;
  },
 });
 const appSource = fs.readFileSync('backend/static/app.js','utf8');
 vm.runInContext(appSource.slice(appSource.indexOf('const POSTER_FALLBACK_URL'),appSource.indexOf('function normalize(')),context);
 vm.runInContext(fs.readFileSync('backend/static/watchlist.js', 'utf8'), context);
 return {context, element, requests, rows, resolve, toasts, listeners};
}
async function main() {
 const guest = setup({signedIn:false}); await tick();
 await guest.element('add-list').events.click();
 assert.equal(guest.element('auth-dialog').open,true);
 assert.equal(guest.requests.length,0);

 const detail = setup(); await tick();
 assert.equal(detail.element('watchlist-select').options.length,5);
 assert.match(detail.requests[0].path,/anime_source=animego&anime_external_id=500/);
 await detail.element('add-list').events.click();
 assert.equal(detail.element('watchlist-dialog').open,true);
 detail.element('watchlist-select').value = 'watching';
 await detail.element('watchlist-form').events.submit({preventDefault(){}});
 assert.equal(detail.rows.at(-1).status,'watching');
 detail.context.window.watchlistAnime.episodes_total = 12;
 await detail.element('add-list').events.click();
 detail.element('watchlist-progress').value = '13';
 await detail.element('watchlist-form').events.submit({preventDefault(){}});
 assert.equal(detail.element('watchlist-dialog').open,true);
 assert.match(detail.element('watchlist-dialog-status').textContent,/0 до 12/);
 detail.element('watchlist-progress').value = '4';
 await detail.element('watchlist-form').events.submit({preventDefault(){}});
 assert.equal(detail.rows.at(-1).episodes_watched,4);
 assert.equal(detail.rows.at(-1).anime_source,'animego');
 assert.equal(detail.element('watchlist-dialog').open,false);
 assert.match(detail.element('add-list').textContent,/Смотрю/);
 await detail.element('add-list').events.click();
 detail.element('watchlist-select').value = 'completed';
 await detail.element('watchlist-form').events.submit({preventDefault(){}});
 assert.equal(detail.rows.at(-1).status,'completed');
 assert.equal(detail.requests.filter(request => request.options.method === 'POST').length,1);
 await detail.element('watchlist-remove').events.click();
 assert.match(detail.element('add-list').textContent,/В мой список/);
 assert.equal(detail.rows.length,21);

 const list = setup({list:true}); await tick();
 const copy = list.element('watchlist-entries').children[0].children[0];
 assert.equal(copy.children[0].href,'/anime/anime-0-1');
 assert.equal(copy.children[0].href,copy.children[1].children[0].href);
 assert.equal(copy.children[0].children[1].src,'https://example.com/poster.png');
 copy.children[0].children[1].onerror();
 assert.equal(copy.children[0].children[1].src,'/static/images/poster-unavailable.svg');
 assert.equal(list.element('watchlist-entries').children.length,20);
 assert.equal(list.element('watchlist-more').hidden,false);
 await list.element('watchlist-more').events.click();
 assert.equal(list.element('watchlist-entries').children.length,21);
 assert.equal(list.element('watchlist-more').hidden,true);
 let progressForm = list.element('watchlist-entries').children[0].children[2];
 progressForm.children[0].value = '2.5';
 await progressForm.events.submit({preventDefault(){}});
 assert.match(progressForm.children[2].textContent,/целое число/);
 progressForm.children[0].value = '7';
 await progressForm.events.submit({preventDefault(){}});
 assert.equal(list.rows[0].episodes_watched,7);
 assert.equal(list.element('watchlist-entries').children.length,21);
 let row = list.element('watchlist-entries').children[0];
 let select = row.children[1].children[0]; select.value = 'watching';
 await select.events.change();
 list.element('watchlist-filters').children[2].events.click(); await tick();
 assert.equal(list.element('watchlist-entries').children.length,1);
 assert.equal(list.element('watchlist-filters').children[2].attributes['aria-pressed'],'true');
 row = list.element('watchlist-entries').children[0];
 await row.children[1].children[1].events.click();
 assert.equal(list.element('watchlist-entries').children.length,0);
 assert.match(list.element('watchlist-status').textContent,/пока нет/);

 const stale = setup({list:true, delay:true});
 vm.runInContext('dsUser = null; dsToken = null; window.watchlistAuthChanged();', stale.context);
 stale.resolve(); await tick();
 assert.equal(stale.element('watchlist-entries').children.length,0);
 assert.equal(stale.element('watchlist-login').hidden,false);
 const publicList=setup({list:true,signedIn:false,publicTarget:'someone'});await tick();
 assert.match(publicList.requests[0].path,/users\/someone\/watchlist/);
 assert.equal(publicList.element('watchlist-entries').children[0].children.length,1);
 assert.equal(publicList.element('watchlist-login').hidden,true);
 assert.equal(publicList.element('watchlist-owner').href,'/profile/someone');
 console.log('Watchlist UI: guest gate, add/update/remove, filters, pagination and stale session responses OK');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
