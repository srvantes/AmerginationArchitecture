const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('backend/static/app.js','utf8');
function setup(){
 const elements=new Map(),requests=[],saved=[],windowEvents={};
 function element(id){
  if(!elements.has(id))elements.set(id,{value:'',textContent:'',hidden:false,disabled:false,options:[],events:{},
   addEventListener(name,handler){this.events[name]=handler;},removeAttribute(name){delete this[name];}});
  return elements.get(id);
 }
 element('episode-select').value='1';
 element('embedded-video').contentWindow={};
 let response=async(path)=>path==='voices'?{translations:[]}:{embed_url:'https://player.example/video'};
 const context=vm.createContext({$:element,URL,URLSearchParams,AbortController,window:{addEventListener(name,handler){windowEvents[name]=handler;},watchlistAnime:{source:'shikimori',id:'21',title:'Ван-Пис'},playbackHistorySave(anime,choice){saved.push({...choice});}},dsUser:null,dsToken:null,
  setTimeout(handler){queueMicrotask(handler);return 0;},clearTimeout(){},
  selectOptions(select,values){select.options=Array.from(values, pair=>Object.assign(Array.from(pair),{value:String(pair[0])}));select.value=String(values[0]?.[0]??'');},
  safeUrl(value){try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)?url.href:null;}catch{return null;}},
  api(path,params){requests.push({path,params});return response(path,params);},
  async fetch(value){const url=new URL(value,'http://localhost'),path='kodik/'+url.pathname.split('/').at(-1),params=Object.fromEntries(url.searchParams);requests.push({path,params});const data=await response(path,params);return {ok:true,json:async()=>data};},
  catalogApi(path){requests.push({path:'catalog',params:{path}});return response('catalog',{path});},
 });
 vm.runInContext('let translations=[],playerVersion=1,playbackId="one-piece",playerEpisodes=[1,2,4,7].map(number=>({number})),voiceReferenceEpisode=null,voiceEpisodesVersion=0,voiceEpisodesController;const voiceEpisodesCache=new Map();let playerMetadataReady=false,playbackInteractionVersion=0,playbackRestoreVersion=0,playbackRestoreUser=null,playbackAuthKey=null,playbackRestoreBusy=false;'+
  source.slice(source.indexOf('function stopPlayer()'),source.indexOf('async function catalogApi('))+
  source.slice(source.indexOf("$('episode-select').addEventListener('change'"),source.indexOf('function activateTab(')),context);
 return {element,requests,saved,context,windowEvents,setResponse(fn){response=fn;},run(code){return vm.runInContext(code,context);}};
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

 // Aniboom switches its media without navigating the host iframe. Mirror its
 // completed-switch event and save the same episode without opening it again.
 const aniboomEmbed='https://aniboom.one/embed/test-anime?episode=1&translation=26&episodes=1';
 const aniboomResponse=async(path,params)=>path==='player'?{embed_url:aniboomEmbed}:normal(path,params);
 async function aniboomFixture(auth=true){
  const fixture=setup();fixture.setResponse(aniboomResponse);
  if(auth)fixture.run('dsUser={id:"owner"};dsToken="owner-token";');
  await fixture.run('loadVoices(playerVersion)');
  fixture.element('player-select').value='aniboom';fixture.element('player-select').events.change();
  fixture.element('voice-select').value='1';await fixture.element('voice-select').events.change();
  return fixture;
 }
 function episodeEvent(fixture,episode,previousEpisode,overrides={}){
  return {source:fixture.element('embedded-video').contentWindow,origin:'https://aniboom.one',
   data:{source:'aniboom-player',type:'player.episodechange',payload:{animeId:'test-anime',episode,previousEpisode,translation:26}},...overrides};
 }
 const internal=await aniboomFixture();const firstSrc=internal.element('embedded-video').src;
 const requestCount=internal.requests.length;
 const switchedEvent=episodeEvent(internal,2,1);
 internal.windowEvents.message(switchedEvent);
 assert.equal(internal.element('episode-select').value,'2');
 assert.equal(internal.element('previous-episode').disabled,false);
 assert.equal(internal.element('next-episode').disabled,false);
 assert.equal(internal.element('embedded-video').src,firstSrc);
 assert.equal(internal.requests.length,requestCount);
 assert.deepEqual(internal.saved.map(s=>s.episode),[1,2]);
 internal.windowEvents.message(switchedEvent); // Duplicate postMessage must not write again.
 assert.deepEqual(internal.saved.map(s=>s.episode),[1,2]);
 for(const badEvent of [
  episodeEvent(internal,7,2,{source:{}}),
  episodeEvent(internal,7,2,{origin:'https://aniboom.one.attacker.example'}),
  episodeEvent(internal,7,2,{origin:'null'}),
  episodeEvent(internal,7,2,{data:'not-json'}),
  ...[{animeId:'other-anime'},{translation:66},{episode:'7'},{episode:4},{episode:0},{episode:1.5},
      {episode:100001},{previousEpisode:1}].map(payload=>{
   const event=episodeEvent(internal,7,2);Object.assign(event.data.payload,payload);return event;
  }),
  episodeEvent(internal,7,2,{data:{source:'other-player',type:'player.episodechange',payload:{}}}),
  episodeEvent(internal,7,2,{data:{source:'aniboom-player',type:'player.timeupdate',payload:{currentTime:7}}}),
 ]){
  internal.windowEvents.message(badEvent);
  assert.equal(internal.element('episode-select').value,'2');
  assert.deepEqual(internal.saved.map(s=>s.episode),[1,2]);
 }
 internal.windowEvents.message(episodeEvent(internal,7,2));
 assert.equal(internal.element('episode-select').value,'7');
 assert.equal(internal.element('next-episode').disabled,true);
 assert.deepEqual(internal.saved.map(s=>s.episode),[1,2,7]);
 internal.windowEvents.message(episodeEvent(internal,1,7));
 assert.equal(internal.element('previous-episode').disabled,true);
 assert.equal(internal.requests.length,requestCount);
 // The host's own navigation starts from the current episode, including gaps.
 await internal.element('next-episode').events.click();
 assert.equal(internal.requests.at(-1).params.episode,'2');
 assert.equal(internal.element('episode-select').value,'2');
 internal.element('player-select').value='kodik';internal.element('player-select').events.change();
 const savedBeforeStop=internal.saved.length;
 internal.windowEvents.message(episodeEvent(internal,7,2));
 assert.equal(internal.saved.length,savedBeforeStop);
 assert.equal(internal.element('embedded-video').hidden,true);

 const guestInternal=await aniboomFixture(false);
 guestInternal.windowEvents.message(episodeEvent(guestInternal,2,1));
 assert.equal(guestInternal.element('episode-select').value,'2');assert.equal(guestInternal.saved.length,0);
 const newAccount=await aniboomFixture();
 newAccount.run('dsUser={id:"other"};dsToken="other-token";');
 newAccount.windowEvents.message(episodeEvent(newAccount,2,1));
 assert.deepEqual(newAccount.saved.map(s=>s.episode),[1]);

 // A late catalogue must not restore episode 1 or reload a player that already
 // moved to episode 2 while the list was being fetched.
 const earlySwitch=setup();let finishEarlyCatalog;
 earlySwitch.setResponse((path,params)=>path==='voice-episodes'?new Promise(resolve=>finishEarlyCatalog=resolve):aniboomResponse(path,params));
 await earlySwitch.run('loadVoices(playerVersion)');
 earlySwitch.element('player-select').value='aniboom';earlySwitch.element('player-select').events.change();
 earlySwitch.element('voice-select').value='1';const openingEarly=earlySwitch.element('voice-select').events.change();
 await tick();earlySwitch.windowEvents.message(episodeEvent(earlySwitch,2,1));
 assert.equal(earlySwitch.element('episode-select').value,'2');
 finishEarlyCatalog({status:'ready',episodes:[1,2,7]});await openingEarly;
 assert.equal(earlySwitch.element('episode-select').value,'2');
 assert.equal(earlySwitch.element('previous-episode').disabled,false);
 assert.equal(earlySwitch.requests.filter(r=>r.path==='player').length,1);

 // A missing or stalled AnimeGo match cannot block the direct provider.
 const directVoice={id:'610',name:'AniLibria.TV',player:'kodik',source:'kodik',embed_url:aniboomEmbed.replace('aniboom.one','kodikplayer.com')};
 const independentResponse=async(path,params)=>path==='kodik/catalog'?{translations:[directVoice],episodes:[1,2]}:
  path==='kodik/voice-episodes'?{status:'ready',episodes:[1,2,7]}:
  path==='kodik/player'?{embed_url:'https://kodikplayer.com/seria/10/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/720p'}:
  path==='episodes'?{episodes:[1,2,4,7].map(number=>({number}))}:normal(path,params);
 function independentFixture(responder=independentResponse,match={status:'not_found'}){
  const fixture=setup();fixture.setResponse(responder);
  fixture.context.startMatch=match;
  fixture.run('playbackShikimoriId="38668";initialPlaybackMatch=startMatch;');
  return fixture;
 }
 const direct=independentFixture();await direct.run('initPlayer()');
 assert.deepEqual(direct.element('player-select').options.map(o=>o[0]),['kodik']);
 direct.element('voice-select').value='0';await direct.element('voice-select').events.change();
 assert.deepEqual(direct.element('episode-select').options.map(o=>o[0]),[1,2,7]);
 direct.element('episode-select').value='7';await direct.element('episode-select').events.change();
 assert.equal(direct.requests.at(-1).path,'kodik/player');assert.equal(direct.requests.at(-1).params.episode,'7');
 assert.equal(direct.requests.at(-1).params.shikimori_id,'38668');
 assert.equal(direct.requests.some(r=>r.path==='episodes'||r.path==='voices'),false);

 let finishMatch;
 const stalled=independentFixture((path,params)=>path==='catalog'?new Promise(resolve=>finishMatch=resolve):independentResponse(path,params),{status:'pending'});
 const loadingProviders=stalled.run('initPlayer()');await tick();await tick();
 stalled.element('voice-select').value='0';await stalled.element('voice-select').events.change();
 stalled.element('episode-select').value='7';await stalled.element('episode-select').events.change();
 const mountedSrc=stalled.element('embedded-video').src;
 finishMatch({playback:{status:'matched',animego_id:'1089'}});await loadingProviders;
 assert.equal(stalled.element('episode-select').value,'7');assert.equal(stalled.element('voice-select').value,'0');
 assert.equal(stalled.element('embedded-video').src,mountedSrc);
 assert.deepEqual(stalled.element('player-select').options.map(o=>o[0]),['kodik','aniboom']);
 assert.equal(stalled.element('voice-select').options.length,2); // One direct studio, no duplicate AnimeGo Kodik entries.
 stalled.element('player-select').value='aniboom';stalled.element('player-select').events.change();
 const aniboomIndex=stalled.run('translations.findIndex(v=>v.player==="aniboom")');
 stalled.element('voice-select').value=String(aniboomIndex);await stalled.element('voice-select').events.change();
 assert.equal(stalled.requests.at(-1).path,'player');assert.equal(stalled.requests.at(-1).params.anime_id,'1089');

 for(const failed of ['kodik','animego']){
  const isolated=independentFixture((path,params)=>{
   if(failed==='kodik'&&path==='kodik/catalog'||failed==='animego'&&path==='episodes')throw Error('Provider unavailable');
   return independentResponse(path,params);
  },{status:'matched',animego_id:'1089'});
  await isolated.run('initPlayer()');
  assert.equal(isolated.element('player-select').disabled,false);
  assert.ok(isolated.element('voice-select').options.length>1);
 }
 const directResume=independentFixture();directResume.run('dsUser={id:"owner"};dsToken="owner-token";');
 directResume.context.window.playbackHistoryGet=async()=>({episode:7,player:'kodik',translation_id:'610',translation_source:'kodik'});
 await directResume.run('initPlayer()');await tick();await tick();
 assert.equal(directResume.element('episode-select').value,'7');
 assert.deepEqual(directResume.saved.map(s=>[s.episode,s.translation_source]),[[7,'kodik']]);
 const legacyResume=independentFixture(independentResponse,{status:'matched',animego_id:'1089'});
 legacyResume.run('dsUser={id:"owner"};dsToken="owner-token";');
 legacyResume.context.window.playbackHistoryGet=async()=>({episode:4,player:'kodik',translation_id:'same'});
 await legacyResume.run('initPlayer()');await tick();await tick();
 assert.equal(legacyResume.element('episode-select').value,'4');
 assert.deepEqual(legacyResume.saved.map(s=>[s.episode,s.translation_source]),[[4,'animego']]);
 let finishDirect;
 const lateDirect=independentFixture((path,params)=>path==='kodik/catalog'?new Promise(resolve=>finishDirect=resolve):independentResponse(path,params),{status:'matched',animego_id:'1089'});
 const pendingDirect=lateDirect.run('initPlayer()');await tick();await tick();
 lateDirect.element('player-select').value='aniboom';lateDirect.element('player-select').events.change();
 lateDirect.element('voice-select').value=String(lateDirect.run('translations.findIndex(v=>v.player==="aniboom")'));
 await lateDirect.element('voice-select').events.change();
 lateDirect.element('episode-select').value='7';await lateDirect.element('episode-select').events.change();
 const beforeDirectSrc=lateDirect.element('embedded-video').src;
 finishDirect({translations:[directVoice],episodes:[1,2]});await pendingDirect;
 assert.equal(lateDirect.element('player-select').value,'aniboom');
 assert.equal(lateDirect.element('episode-select').value,'7');
 assert.equal(lateDirect.run('selectedVoice().player'),'aniboom');
 assert.equal(lateDirect.element('embedded-video').src,beforeDirectSrc);
 console.log('Player UI: one catalogue request, exact gaps/counts, cache, preserved episode, stale responses, empty/unsupported catalogues and retry OK');
 console.log('Playback resume/navigation: account restoration, stable studio IDs, exact gaps, unavailable choices, manual/logout races and successful latest saves OK');
 console.log('Aniboom events: internal switches, history, no iframe reload, origin/source/title/voice checks, deduplication and pending catalogue races OK');
 console.log('Independent players: direct Kodik, missing/stalled AnimeGo, isolated failures, late-source selection preservation and legacy/direct history OK');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
