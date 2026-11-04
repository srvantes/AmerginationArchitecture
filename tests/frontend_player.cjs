const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('backend/static/app.js','utf8');
function setup(){
 const elements=new Map(),requests=[],saved=[];
 function element(id){
  if(!elements.has(id))elements.set(id,{value:'',textContent:'',hidden:false,disabled:false,options:[],events:{},
   addEventListener(name,handler){this.events[name]=handler;},removeAttribute(name){delete this[name];}});
  return elements.get(id);
 }
 element('episode-select').value='1';
 let response=async(path)=>path==='voices'?{translations:[]}:{embed_url:'https://player.example/video'};
 const context=vm.createContext({$:element,URL,AbortController,window:{watchlistAnime:{source:'shikimori',id:'21',title:'Ван-Пис'},playbackHistorySave(anime,choice){saved.push({...choice});}},dsUser:null,dsToken:null,
  setTimeout(handler){queueMicrotask(handler);return 0;},clearTimeout(){},
  selectOptions(select,values){select.options=Array.from(values, pair=>Object.assign(Array.from(pair),{value:String(pair[0])}));select.value=String(values[0]?.[0]??'');},
  safeUrl(value){try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)?url.href:null;}catch{return null;}},
  api(path,params){requests.push({path,params});return response(path,params);},
 });
 vm.runInContext('let translations=[],playerVersion=1,playbackId="one-piece",playerEpisodes=[1,2,4,7].map(number=>({number})),voiceReferenceEpisode=null,voiceEpisodesVersion=0,voiceEpisodesController;const voiceEpisodesCache=new Map();let playerMetadataReady=false,playbackInteractionVersion=0,playbackRestoreVersion=0,playbackRestoreUser=null,playbackAuthKey=null,playbackRestoreBusy=false;'+
  source.slice(source.indexOf('function stopPlayer()'),source.indexOf('async function catalogApi('))+
  source.slice(source.indexOf("$('episode-select').addEventListener('change'"),source.indexOf('function activateTab(')),context);
 return {element,requests,saved,context,setResponse(fn){response=fn;},run(code){return vm.runInContext(code,context);}};
}
const voice=(player,id,name)=>({player,id,name,embed_url:'https://player.example/'+player});
const voices=[voice('kodik','same','Студия Kodik'),voice('aniboom','same','Студия Aniboom'),voice('kodik','other','Другая студия')];
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function main(){
 const app=setup();
 const normal=async(path,params)=>path==='voices'?{translations:voices}:path==='voice-episodes'?{status:'ready',episodes:params.player==='kodik'?[1,4]:[1,2,7,99]}:{embed_url:'https://player.example/video'};
 app.setResponse(normal);await app.run('loadVoices(playerVersion)');
 assert.deepEqual(app.element('player-select').options.map(o=>o[0]),['kodik','aniboom']);
 assert.deepEqual(app.element('voice-select').options.map(o=>o[1]),['Выберите озвучку','Студия Kodik','Другая студия']);
 assert.equal(app.requests.filter(r=>r.path==='player').length,0);
 app.element('player-select').value='aniboom';app.element('player-select').events.change();
 assert.deepEqual(app.element('voice-select').options.map(o=>o[1]),['Выберите озвучку','Студия Aniboom']);
 app.element('voice-select').value='1';await app.element('voice-select').events.change();
 assert.deepEqual(app.element('episode-select').options.map(o=>o[0]),[1,2,7]);
 assert.equal(app.element('voice-episodes-status').textContent,'Доступно серий: 3');
 const opened=app.requests.find(r=>r.path==='player');assert.equal(opened.params.player,'aniboom');assert.equal(opened.params.translation_id,'same');
 const catalogs=app.requests.filter(r=>r.path==='voice-episodes');assert.equal(catalogs.length,1);assert.equal(catalogs[0].params.episode,1);assert.equal(catalogs[0].params.offset,undefined);
 assert.equal(app.element('embedded-video').hidden,false);
 app.element('episode-select').value='2';await app.element('episode-select').events.change();
 assert.equal(app.requests.at(-1).params.episode,'2');
 await app.element('voice-select').events.change();assert.equal(app.requests.filter(r=>r.path==='voice-episodes').length,1);
 assert.equal(app.element('episode-select').value,'2'); // Preserve a valid current episode on a cached voice selection.
 app.element('player-select').value='kodik';app.element('player-select').events.change();
 assert.deepEqual(app.element('episode-select').options.map(o=>o[0]),[1,2,4,7]);
 app.element('voice-select').value='0';await app.element('voice-select').events.change();
 assert.deepEqual(app.element('episode-select').options.map(o=>o[0]),[1,4]);
 assert.equal(app.element('episode-select').value,'1');

 // Switching provider cancels a pending catalogue. Its late result cannot start an old iframe.
 let finishCatalog;app.element('voice-select').value='2';
 app.setResponse((path)=>path==='voice-episodes'?new Promise(resolve=>finishCatalog=resolve):normal(path,{}));
 const old=app.element('voice-select').events.change();await tick();
 assert.equal(app.element('embedded-video').hidden,false); // Known reference opens before the catalogue resolves.
 assert.equal(app.element('episode-select').disabled,true);
 app.element('player-select').value='aniboom';app.element('player-select').events.change();
 app.setResponse(normal);app.element('voice-select').value='1';await app.element('voice-select').events.change();
 const requestsBefore=app.requests.length;finishCatalog({status:'ready',episodes:[1,4]});await old;
 assert.equal(app.requests.length,requestsBefore);
 assert.deepEqual(app.element('episode-select').options.map(o=>o[0]),[1,2,7]);

 // A failed request leaves only the known reference episode; retry is a single catalogue call.
 app.element('player-select').value='kodik';app.element('player-select').events.change();app.element('voice-select').value='2';
 app.setResponse(async(path,params)=>{if(path==='voice-episodes')throw Error('Источник недоступен');return normal(path,params);});
 await app.element('voice-select').events.change();
 assert.equal(app.element('retry-voice-episodes').hidden,false);
 assert.equal(app.element('episode-select').disabled,true);
 assert.equal(app.element('embedded-video').hidden,false);
 app.setResponse(normal);await app.element('retry-voice-episodes').events.click();
 assert.equal(app.element('retry-voice-episodes').hidden,true);
 assert.deepEqual(app.element('episode-select').options.map(o=>o[0]),[1,4]);

 const unsupported=setup();unsupported.setResponse(async(path)=>path==='voices'?{translations:voices}:path==='voice-episodes'?{status:'unsupported',episodes:[],message:'Полный список недоступен'}:{embed_url:'https://player.example/one'});
 await unsupported.run('loadVoices(playerVersion)');unsupported.element('voice-select').value='0';await unsupported.element('voice-select').events.change();
 assert.equal(unsupported.element('voice-episodes-status').textContent,'Полный список недоступен');
 assert.deepEqual(unsupported.element('episode-select').options.map(o=>o[0]),[1]);assert.equal(unsupported.element('episode-select').disabled,true);
 assert.equal(unsupported.element('embedded-video').hidden,false);
 assert.equal(unsupported.requests.filter(r=>r.path==='voice-episodes').length,1); // No paginated fallback.

 const empty=setup();empty.setResponse(async path=>path==='voices'?{translations:voices}:path==='voice-episodes'?{status:'ready',episodes:[]}:{embed_url:'https://player.example/one'});
 await empty.run('loadVoices(playerVersion)');empty.element('voice-select').value='0';await empty.element('voice-select').events.change();
 assert.equal(empty.requests.filter(r=>r.path==='player').length,1);assert.equal(empty.element('episode-select').disabled,true);
 assert.equal(empty.element('embedded-video').hidden,true); // A definitive empty catalogue closes the provisional player.

 // A slow old embed cannot reopen after a definitive empty catalogue or a provider switch.
 const pending=setup();let finishPlayer,finishEmpty;
 pending.setResponse((path)=>path==='voices'?Promise.resolve({translations:voices}):path==='player'?
  new Promise(resolve=>finishPlayer=resolve):new Promise(resolve=>finishEmpty=resolve));
 await pending.run('loadVoices(playerVersion)');pending.element('voice-select').value='0';
 const selecting=pending.element('voice-select').events.change();await tick();
 finishEmpty({status:'ready',episodes:[]});await selecting;
 finishPlayer({embed_url:'https://player.example/late'});await tick();
 assert.equal(pending.element('embedded-video').hidden,true);

 const discovery=setup();discovery.setResponse(async()=>({translations:[voice('kodik','later','Поздняя студия')]}));
 discovery.element('episode-select').value='7';await discovery.element('episode-select').events.change();
 assert.equal(discovery.requests[0].params.episode,'7');assert.equal(discovery.element('voice-select').options[1][1],'Поздняя студия');

 // Restore the stable provider/studio ID on its saved episode, then obtain the exact catalogue.
 const resume=setup();resume.setResponse(normal);
 resume.run('dsUser={id:"owner"};dsToken="owner-token";playerMetadataReady=true;playbackAuthKey="owner:owner-token";');
 resume.context.window.playbackHistoryGet=async()=>({episode:4,player:'kodik',translation_id:'same'});
 await resume.run('loadVoices(playerVersion)');await resume.run('restorePlayback()');
 assert.equal(resume.element('episode-select').value,'4');assert.equal(resume.element('voice-select').value,'0');
 assert.equal(resume.element('voice-episodes-status').textContent,'Доступно серий: 2');
 assert.match(resume.element('playback-restore-status').textContent,/серия 4/);
 assert.deepEqual(resume.saved.map(s=>s.episode),[4]);
 const catalogRequest=resume.requests.find(r=>r.path==='voice-episodes');assert.equal(catalogRequest.params.episode,4);
 assert.equal(resume.element('next-episode').disabled,true);assert.equal(resume.element('previous-episode').disabled,false);
 await resume.element('previous-episode').events.click();assert.equal(resume.element('episode-select').value,'1');
 assert.equal(resume.element('previous-episode').disabled,true);assert.equal(resume.element('next-episode').disabled,false);
 await resume.element('next-episode').events.click();assert.equal(resume.element('episode-select').value,'4'); // Skip gaps 2–3.
 assert.equal(resume.requests.filter(r=>r.path==='voice-episodes').length,1);
 const beforeEnd=resume.requests.length;await resume.element('next-episode').events.click();assert.equal(resume.requests.length,beforeEnd);

 async function restoreFixture(saved,respond=normal){
  const fixture=setup();fixture.setResponse(respond);
  fixture.run('dsUser={id:"owner"};dsToken="owner-token";playerMetadataReady=true;playbackAuthKey="owner:owner-token";');
  fixture.context.window.playbackHistoryGet=async()=>saved;
  await fixture.run('loadVoices(playerVersion)');await fixture.run('restorePlayback()');return fixture;
 }
 const gone=await restoreFixture({episode:99,player:'kodik',translation_id:'same'});
 assert.equal(gone.requests.filter(r=>r.path==='player').length,0);assert.match(gone.element('playback-restore-status').textContent,/больше недоступна/);
 const studioGone=await restoreFixture({episode:4,player:'kodik',translation_id:'removed'});
 assert.equal(studioGone.requests.filter(r=>r.path==='player').length,0);assert.equal(studioGone.element('voice-select').value,'');
 assert.match(studioGone.element('playback-restore-status').textContent,/озвучка или плеер недоступны/);
 const episodeGone=await restoreFixture({episode:4,player:'kodik',translation_id:'same'},async(path,params)=>path==='voice-episodes'?{status:'ready',episodes:[1,2]}:normal(path,params));
 assert.equal(episodeGone.requests.filter(r=>r.path==='player').length,0);assert.equal(episodeGone.element('episode-select').value,'');
 assert.match(episodeGone.element('playback-restore-status').textContent,/недоступна в этой озвучке/);
 episodeGone.element('episode-select').value='1';await episodeGone.element('episode-select').events.change();
 assert.equal(episodeGone.element('embedded-video').hidden,false);
 const noEpisodes=await restoreFixture({episode:4,player:'kodik',translation_id:'same'},async(path,params)=>path==='voice-episodes'?{status:'ready',episodes:[]}:normal(path,params));
 assert.equal(noEpisodes.requests.filter(r=>r.path==='player').length,0);assert.doesNotMatch(noEpisodes.element('playback-restore-status').textContent,/Восстанавливаем/);

 // A manual choice or logout while the private GET is pending must win over its response.
 for(const logout of [false,true]){
  const late=setup();late.setResponse(normal);let finishHistory;
  late.run('dsUser={id:"owner"};dsToken="owner-token";playerMetadataReady=true;playbackAuthKey="owner:owner-token";');
  late.context.window.playbackHistoryGet=()=>new Promise(resolve=>finishHistory=resolve);
  await late.run('loadVoices(playerVersion)');const restoring=late.run('restorePlayback()');await tick();
  if(logout){late.run('dsUser=null;dsToken=null;window.playerHistoryAuthChanged();');await tick();}
  else{late.element('player-select').value='aniboom';late.element('player-select').events.change();}
  finishHistory({episode:4,player:'kodik',translation_id:'same'});await restoring;
  assert.equal(late.requests.filter(r=>r.path==='player').length,0);assert.equal(late.element('playback-restore-status').textContent,'');
  if(!logout)assert.equal(late.element('player-select').value,'aniboom');
 }

 // Only the latest successful embed is saved; failure/old responses and another account are excluded.
 const race=await restoreFixture({episode:4,player:'kodik',translation_id:'same'});race.saved.length=0;let finishOld;
 race.setResponse(async(path,params)=>path==='player'&&params.episode==='1'?new Promise(resolve=>finishOld=resolve):normal(path,params));
 race.element('episode-select').value='1';const first=race.element('episode-select').events.change();await tick();
 race.element('episode-select').value='4';await race.element('episode-select').events.change();
 finishOld({embed_url:'https://player.example/old'});await first;assert.deepEqual(race.saved.map(s=>s.episode),[4]);
 race.setResponse(async()=>{throw Error('Player failed');});race.element('episode-select').value='1';await race.element('episode-select').events.change();
 assert.deepEqual(race.saved.map(s=>s.episode),[4]);
 race.setResponse(()=>new Promise(resolve=>finishOld=resolve));const switched=race.run('openPlayer()');await tick();
 race.run('dsUser={id:"other"};dsToken="other-token";');finishOld({embed_url:'https://player.example/ready'});await switched;
 assert.deepEqual(race.saved.map(s=>s.episode),[4]);

 // A late auth restoration starts history only after metadata is ready, without a second login.
 const lateLogin=setup();lateLogin.setResponse(async(path,params)=>path==='episodes'?{episodes:[1,2,4,7].map(number=>({number}))}:normal(path,params));
 lateLogin.context.window.playbackHistoryGet=async()=>({episode:4,player:'kodik',translation_id:'same'});
 await lateLogin.run('initPlayer()');assert.equal(lateLogin.requests.filter(r=>r.path==='player').length,0);
 lateLogin.run('dsUser={id:"owner"};dsToken="owner-token";window.playerHistoryAuthChanged();');
 await tick();await tick();assert.equal(lateLogin.element('episode-select').value,'4');
 console.log('Player UI: one catalogue request, exact gaps/counts, cache, preserved episode, stale responses, empty/unsupported catalogues and retry OK');
 console.log('Playback resume/navigation: account restoration, stable studio IDs, exact gaps, unavailable choices, manual/logout races and successful latest saves OK');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
