'use strict';
const $ = id => document.getElementById(id);
let catalog = [], translations = [], playerVersion = 0, searchVersion = 0, toastTimer;
const pageRoute = parseAnimeRoute(location.pathname);
const pageId = pageRoute?.id, pageSource = pageRoute?.source;
let playbackId = null;
let playerEpisodes = [], voiceReferenceEpisode = null, voiceEpisodesVersion = 0, voiceEpisodesController;
const voiceEpisodesCache = new Map();
let playerMetadataReady = false, playbackInteractionVersion = 0, playbackRestoreVersion = 0;
let playbackRestoreUser = null, playbackAuthKey = null, playbackRestoreBusy = false;
const publicListUserId = location.pathname.match(/^\/profile\/([0-9a-f-]{36})\/list$/i)?.[1]?.toLowerCase() || null;
const profileUserId = location.pathname.match(/^\/profile\/([0-9a-f-]{36})$/i)?.[1]?.toLowerCase() || null;
const listPage = location.pathname === '/my-list' || !!publicListUserId;
const profilePage = location.pathname === '/profile' || !!profileUserId;
const collectionSlug = location.pathname.match(/^\/collections\/([^/]+)\/?$/)?.[1] || null;
const collectionCache = new Map(), collectionRequests = new Map();
let collectionPageVersion = 0, thematicGeneration = 0, thematicActive = 0, thematicObserver;
let thematicQueue = [], thematicJobs = [], thematicFallbackBound = false;
function text(tag, value, className) { const el = document.createElement(tag); el.textContent = value; if (className) el.className = className; return el; }
function safeUrl(value) { try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : null; } catch { return null; } }
const POSTER_FALLBACK_URL = '/static/images/poster-unavailable.svg';
function posterSource(value) {
 const safe = safeUrl(value); if (!safe) return null;
 const url = new URL(safe);
 if (url.username || url.password) return null;
 if (['shikimori.io','shikimori.one','www.shikimori.io','www.shikimori.one'].includes(url.hostname)
     && url.pathname.toLowerCase().startsWith('/assets/globals/missing')) return null;
 return safe;
}
function setPosterImage(image, value, title, lazy = true) {
 const source = posterSource(value); let fallback = !source;
 image.hidden = false; image.alt = source ? title : 'Постер недоступен';
 image.loading = lazy ? 'lazy' : 'eager'; image.referrerPolicy = 'no-referrer';
 // Replacing the handler also resets reused detail images without retry loops.
 image.onerror = () => {
  if (fallback) { image.hidden = true; return; }
  fallback = true; image.alt = 'Постер недоступен'; image.src = POSTER_FALLBACK_URL;
 };
 image.src = source || POSTER_FALLBACK_URL; return image;
}
function posterImage(value, title, lazy = true) { return setPosterImage(document.createElement('img'), value, title, lazy); }
const ANIME_LETTERS = Object.fromEntries(Array.from('абвгдеёжзийклмнопрстуфхцчшщъыьэюя').map((letter,index)=>[letter,['a','b','v','g','d','e','yo','zh','z','i','y','k','l','m','n','o','p','r','s','t','u','f','kh','ts','ch','sh','shch','','y','','e','yu','ya'][index]]));
function animeTitleSlug(title) {
 return String(title||'').toLowerCase().replace(/[а-яё]/g,letter=>ANIME_LETTERS[letter]).normalize('NFKD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'').slice(0,160).replace(/-+$/g,'')||'anime';
}
function parseAnimeRoute(path) {
 if(typeof path!=='string'||path.length>331)return null;
 const pretty=path.match(/^\/anime\/([a-z0-9]+(?:-[a-z0-9]+)*)-(a?)([1-9][0-9]{0,19})\/?$/);
 if(pretty)return {source:pretty[2]?'animego':'shikimori',id:pretty[3],slug:pretty[2]?pretty[1]:null,pretty:true};
 const legacy=path.match(/^\/anime\/(?:(shikimori|animego)\/)?([1-9][0-9]{0,19})\/?$/);
 return legacy?{source:legacy[1]||'animego',id:legacy[2],slug:null,pretty:false}:null;
}
function animePath(card) {
 const source=card.source??card.anime_source,id=String(card.external_id??card.anime_external_id??card.id??'');
 if(!['shikimori','animego'].includes(source)||!(/^[1-9][0-9]{0,19}$/).test(id))return null;
 const supplied=card.public_path??card.path,route=parseAnimeRoute(supplied);
 if(route?.pretty&&route.id===id&&route.source===source)return supplied.replace(/\/$/,'');
 const upstream=card.slug??card.anime_slug;
 const slug=source==='animego'&&typeof upstream==='string'&&upstream.length<=300&&/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(upstream)?upstream:animeTitleSlug(card.original_title||card.original||card.title||card.anime_title);
 return '/anime/'+slug+'-'+(source==='animego'?'a':'')+id;
}
function syncAnimeAddress(card) {
 const path=animePath(card);
 if(path&&window.history?.replaceState&&(location.pathname!==path||location.search))window.history.replaceState(window.history.state,'',path+(location.hash||''));
}
function normalize(card) { return { id: String(card.id ?? card.external_id), title: card.title, original: card.original_title, image: safeUrl(card.image ?? card.poster_url), year: card.year, kind: card.type ?? card.kind, score: card.rating ?? card.score, source: card.source ?? 'animego', slug: card.slug, public_path: card.public_path, genres: card.genres ?? [], relation: card.relation }; }
function saveCard(card) { try { sessionStorage.setItem('anime:' + card.source + ':' + card.id, JSON.stringify(card)); } catch {} }
function cardElement(card, ongoing = false) {
 const link = document.createElement('a'); link.className = 'anime-card'; link.href = animePath(card)||'#'; link.addEventListener('click', () => saveCard(card));
 const poster = text('div', '', 'poster'); poster.append(text('span', 'Нет постера', 'poster-fallback'));
 poster.append(posterImage(card.image, card.title));
 if (card.score) poster.append(text('span', card.score, 'score'));
 if (ongoing) poster.append(text('span', 'Онгоинг', 'poster-label'));
 link.append(poster, text('h3', card.title), text('p', [card.relation, card.year, card.kind].filter(Boolean).join(' · '))); return link;
}
function renderCards(target, cards, ongoing = false) { $(target).replaceChildren(...cards.map(card => cardElement(card, ongoing))); }
function toast(message) { clearTimeout(toastTimer); $('toast').textContent = message; $('toast').hidden = false; toastTimer = setTimeout(() => $('toast').hidden = true, 4000); }
async function api(path, params, options = {}) { const response = await fetch('/api/v1/anime/animego/' + path + '?' + new URLSearchParams(params), options); const data = await response.json(); if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Не удалось загрузить данные. Попробуй ещё раз.'); return data; }
function selectOptions(select, values) { select.replaceChildren(...values.map(([value, label]) => { const option = text('option', label); option.value = value; return option; })); }
function stopPlayer() { $('embedded-video').hidden = true; $('embedded-video').removeAttribute('src'); $('player-placeholder').hidden = false; }
const playerNames = {kodik:'Kodik',sibnet:'Sibnet',aniboom:'Aniboom',cvh:'CVH'};
function selectedVoice() {
 const value=$('voice-select').value;
 if(value==='')return null;
 const voice=translations[Number(value)];
 return voice?.player===$('player-select').value ? voice : null;
}
function renderVoices(preferredId=null) {
 const player=$('player-select').value;
 const voices=translations.map((voice,index)=>({voice,index})).filter(item=>item.voice.player===player);
 selectOptions($('voice-select'), [['',voices.length ? 'Выберите озвучку' : 'Нет озвучок'],...voices.map(({voice,index})=>[index,voice.name])]);
 $('voice-select').disabled=!voices.length;
 const preferred=voices.find(({voice})=>voice.id===preferredId);
 if(preferred)$('voice-select').value=String(preferred.index);
 updateEpisodeNavigation();
}
function playbackAuth() {
 return typeof dsUser !== 'undefined' && dsUser && typeof dsToken !== 'undefined' && dsToken ? {id:dsUser.id,token:dsToken} : null;
}
function episodeNavigationNumbers() {
 return Array.from($('episode-select').options, option=>Number(option.value)).filter(number=>Number.isSafeInteger(number)&&number>0);
}
function updateEpisodeNavigation() {
 const numbers=episodeNavigationNumbers(),index=numbers.indexOf(Number($('episode-select').value));
 const ready=!!selectedVoice()&&!$('episode-select').disabled&&!playbackRestoreBusy&&index>=0;
 $('previous-episode').disabled=!ready||index===0;
 $('next-episode').disabled=!ready||index===numbers.length-1;
}
function playerInteracted() {
 ++playbackInteractionVersion;++playbackRestoreVersion;playbackRestoreBusy=false;
 $('playback-restore-status').textContent='';updateEpisodeNavigation();
}
async function episodeChanged() {
 playerInteracted();
 if(selectedVoice())return openPlayer();
 const version=++playerVersion,player=$('player-select').value;cancelVoiceEpisodes();stopPlayer();
 try{await loadVoices(version,{player});}catch(error){if(version===playerVersion)$('player-status').textContent=error.message;}
}
async function navigateEpisode(direction) {
 const numbers=episodeNavigationNumbers(),index=numbers.indexOf(Number($('episode-select').value));
 if(!selectedVoice()||$('episode-select').disabled||playbackRestoreBusy||index<0||numbers[index+direction]===undefined)return;
 $('episode-select').value=String(numbers[index+direction]);await episodeChanged();
}
async function restorePlayback() {
 const auth=playbackAuth(),key=auth ? auth.id+':'+auth.token : null;
 if(!playerMetadataReady||!auth||playbackInteractionVersion||playbackRestoreUser===key||!window.playbackHistoryGet)return;
 playbackRestoreUser=key;const run=++playbackRestoreVersion;playbackRestoreBusy=true;updateEpisodeNavigation();
 const current=()=>run===playbackRestoreVersion&&playbackAuth()?.id===auth.id&&playbackAuth()?.token===auth.token;
 $('playback-restore-status').textContent='Восстанавливаем последний выбор…';
 try {
  const saved=await window.playbackHistoryGet(window.watchlistAnime.source,window.watchlistAnime.id);
  if(!current())return;
  if(!saved){$('playback-restore-status').textContent='';return;}
  if(!playerEpisodes.some(episode=>episode.number===saved.episode)){
   $('playback-restore-status').textContent='Сохранённая серия '+saved.episode+' больше недоступна. Выберите доступную серию и озвучку.';return;
  }
  const version=++playerVersion;cancelVoiceEpisodes();stopPlayer();$('episode-select').value=String(saved.episode);
  await loadVoices(version,{player:saved.player,id:saved.translation_id,deferOpen:true});
  if(!current()||version!==playerVersion)return;
  if(!selectedVoice()){
   $('playback-restore-status').textContent='Сохранённая озвучка или плеер недоступны для серии '+saved.episode+'. Выберите доступные.';return;
  }
  const opened=await chooseVoice({strictEpisode:true});
  if(current()){
   if(opened)$('playback-restore-status').textContent='Восстановлен последний выбор: серия '+saved.episode+'.';
   else if($('playback-restore-status').textContent==='Восстанавливаем последний выбор…')
    $('playback-restore-status').textContent='Не удалось открыть сохранённую серию. Выберите доступную серию и озвучку или повторите загрузку.';
  }
 } catch(error) {
  if(current())$('playback-restore-status').textContent='Не удалось восстановить последний выбор. Выберите серию и озвучку вручную.';
 } finally {
  if(current()){playbackRestoreBusy=false;updateEpisodeNavigation();}
 }
}
window.playerHistoryAuthChanged=()=>{
 const auth=playbackAuth(),key=auth ? auth.id+':'+auth.token : null;
 if(key!==playbackAuthKey){
  playbackAuthKey=key;playbackRestoreUser=null;++playbackRestoreVersion;
  const wasBusy=playbackRestoreBusy;playbackRestoreBusy=false;$('playback-restore-status').textContent='';
  if(wasBusy&&playerMetadataReady){
   const version=++playerVersion;cancelVoiceEpisodes();stopPlayer();resetEpisodeChoices();
   loadVoices(version).catch(error=>{if(version===playerVersion)$('player-status').textContent=error.message;});
  }
 }
 restorePlayback();
};
async function openPlayer(version=++playerVersion) {
 const voice=selectedVoice(),episode=Number($('episode-select').value),auth=playbackAuth();stopPlayer();
 if(!voice){$('player-status').textContent='Выберите озвучку.';return;}
 $('player-status').textContent='Открываем плеер…';
 try {
  const data=await api('player',{anime_id:playbackId,episode:String(episode),translation_id:voice.id,player:voice.player});
  if(version!==playerVersion)return;
  const embed=safeUrl(data.embed_url);if(!embed)throw Error('Плеер вернул некорректную ссылку');
  $('embedded-video').src=embed;$('embedded-video').hidden=false;$('player-placeholder').hidden=true;
  $('player-status').textContent='Плеер готов. Нажми воспроизведение внутри видео.';
  if(auth&&playbackAuth()?.id===auth.id&&playbackAuth()?.token===auth.token)
   window.playbackHistorySave?.(window.watchlistAnime,{episode,player:voice.player,translation_id:voice.id,translation_name:voice.name});
  return true;
 }catch(error){if(version===playerVersion)$('player-status').textContent=error.message;}
 finally{updateEpisodeNavigation();}
}
function voiceEpisodesKey(voice){return playbackId+':'+voice.player+':'+voice.id+':'+voiceReferenceEpisode;}
function cancelVoiceEpisodes(){++voiceEpisodesVersion;voiceEpisodesController?.abort();$('retry-voice-episodes').hidden=true;}
function resetEpisodeChoices(){
 const previous=$('episode-select').value;
 selectOptions($('episode-select'),playerEpisodes.map(episode=>[episode.number,'Серия '+episode.number]));
 if(playerEpisodes.some(episode=>String(episode.number)===previous))$('episode-select').value=previous;
 $('episode-select').disabled=!playerEpisodes.length;
 updateEpisodeNavigation();
}
function renderVoiceEpisodes(data,previous=$('episode-select').value){
 const playable=new Set(playerEpisodes.map(episode=>episode.number));
 const available=data.episodes.filter(number=>playable.has(number));
 selectOptions($('episode-select'),available.length ? available.map(number=>[number,'Серия '+number]) : [['','Нет доступных серий']]);
 $('episode-select').disabled=!available.length;
 if(available.some(number=>String(number)===previous))$('episode-select').value=previous;
 $('voice-episodes-status').textContent='Доступно серий: '+available.length;
 updateEpisodeNavigation();
 return available;
}
async function loadVoiceEpisodes(voice,run,preferredEpisode=$('episode-select').value){
 const key=voiceEpisodesKey(voice),cached=voiceEpisodesCache.get(key);
 voiceEpisodesController=new AbortController();const signal=voiceEpisodesController.signal;
 $('voice-episodes-status').textContent='Загружаем список серий выбранной озвучки…';
 $('episode-select').disabled=true;
 updateEpisodeNavigation();
 try{
  const data=cached && cached.expires>Date.now() ? cached.data : await api('voice-episodes',{
   anime_id:playbackId,translation_id:voice.id,player:voice.player,episode:voiceReferenceEpisode
  },{signal});
  if(run!==voiceEpisodesVersion)return;
  if(data.status==='unsupported'){
   $('voice-episodes-status').textContent=data.message;
   return;
  }
  voiceEpisodesCache.set(key,{data,expires:Date.now()+300000});
  const available=renderVoiceEpisodes(data,preferredEpisode);
  if(!available.length){++playerVersion;stopPlayer();$('player-status').textContent='У выбранной озвучки нет доступных серий.';}
  return available;
 }catch(error){
  if(run===voiceEpisodesVersion){$('voice-episodes-status').textContent='Не удалось загрузить список серий: '+error.message;$('retry-voice-episodes').hidden=false;}
 }
}
async function chooseVoice({strictEpisode=false}={}){
 cancelVoiceEpisodes();++playerVersion;const voice=selectedVoice();stopPlayer();
 if(!voice){resetEpisodeChoices();$('voice-episodes-status').textContent='';$('player-status').textContent='Выберите озвучку.';return;}
 const run=voiceEpisodesVersion;
 const preferred=$('episode-select').value;
 // This reference episode is already confirmed by the upstream voices response.
 selectOptions($('episode-select'),[[voiceReferenceEpisode,'Серия '+voiceReferenceEpisode]]);
 $('player-status').textContent='Загружаем список серий…';
 // Open an explicitly chosen, known episode while the full catalogue loads.
 // Restoring history still waits for availability so an unavailable saved
 // episode never starts a different one. Other episodes stay disabled.
 const initialPlayer=!strictEpisode&&Number(preferred)===voiceReferenceEpisode ? openPlayer() : null;
 const available=await loadVoiceEpisodes(voice,run,preferred);
 if(run!==voiceEpisodesVersion)return;
 if(strictEpisode&&Array.isArray(available)&&available.length&&!available.includes(Number(preferred))){
  selectOptions($('episode-select'),[['','Выберите серию'],...available.map(number=>[number,'Серия '+number])]);
  $('playback-restore-status').textContent='Сохранённая серия '+preferred+' недоступна в этой озвучке. Выберите другую серию или озвучку.';
  $('player-status').textContent='Выберите доступную серию.';updateEpisodeNavigation();return false;
 }
 if(initialPlayer&&Number($('episode-select').value)===voiceReferenceEpisode)return await initialPlayer;
 if($('episode-select').value)return await openPlayer();
}
async function loadVoices(version, preference={}) {
 translations=[];$('voice-select').disabled=true;$('player-select').disabled=true;
 selectOptions($('voice-select'),[['','Загружаем…']]);selectOptions($('player-select'),[['','Загружаем…']]);
 const data=await api('voices',{anime_id:playbackId,episode:$('episode-select').value});
 if(version!==playerVersion)return;
 voiceReferenceEpisode=Number($('episode-select').value);
 translations=data.translations.filter(voice=>Object.hasOwn(playerNames,voice.player)&&safeUrl(voice.embed_url));
 const players=[...new Set(translations.map(voice=>voice.player))];
 selectOptions($('player-select'),players.length ? players.map(player=>[player,playerNames[player]]) : [['','Нет плееров']]);
 $('player-select').disabled=!players.length;
 if(players.includes(preference.player))$('player-select').value=preference.player;
 renderVoices(preference.player===$('player-select').value ? preference.id : null);
 if(selectedVoice()&&!preference.deferOpen)await openPlayer(version);
 else $('player-status').textContent=!players.length ? 'Для этой серии пока нет доступных плееров.' : preference.id ? 'Для этой серии выберите доступную озвучку.' : 'Выберите озвучку — серия загрузится автоматически.';
}
async function initPlayer() {
 const version = ++playerVersion;
 try {
  const data = await api('episodes', { anime_id: playbackId });
  if (version !== playerVersion) return;
  selectOptions($('episode-select'), data.episodes.length ? data.episodes.map(ep => [ep.number, 'Серия ' + ep.number]) : [[1, 'Эпизод 1']]);
  playerEpisodes=data.episodes; $('episode-select').disabled = false; await loadVoices(version);
  if(version===playerVersion){playerMetadataReady=true;await restorePlayback();}
 } catch (error) { if (version === playerVersion) { selectOptions($('episode-select'), [['', 'Недоступно']]); selectOptions($('player-select'), [['', 'Недоступно']]); selectOptions($('voice-select'), [['', 'Недоступно']]); $('player-status').textContent = error.message; } }
}
async function catalogApi(path, params = {}) {
 const response = await fetch('/api/v1/anime/catalog/' + path + '?' + new URLSearchParams(params));
 const data = await response.json();
 if (!response.ok) { const error = Error(typeof data.detail === 'string' ? data.detail : 'Каталог временно недоступен'); error.status = response.status; throw error; }
 return data;
}
function collectionHref(slug) { return '/collections/' + encodeURIComponent(slug); }
function scrollShelf(track, direction) {
 track.scrollBy({left:direction * track.clientWidth * .75,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
}
function collectionPlaceholders(count = 6) {
 return Array.from({length:count}, () => { const item = text('div','','collection-placeholder'); item.setAttribute('aria-hidden','true'); return item; });
}
async function collectionData(slug, limit) {
 const key = slug + ':' + limit, cached = collectionCache.get(key);
 if (cached && cached.expires > Date.now()) return cached.data;
 if (collectionRequests.has(key)) return collectionRequests.get(key);
 const request = catalogApi('collections/' + encodeURIComponent(slug), {limit}).then(data => {
  if (!data || data.slug !== slug || typeof data.title !== 'string' || !Array.isArray(data.items)) throw Error('Некорректный ответ подборки');
  const result = {...data,items:data.items.slice(0,limit)};
  collectionCache.set(key,{data:result,expires:Date.now() + 300000}); return result;
 }).finally(() => collectionRequests.delete(key));
 collectionRequests.set(key,request); return request;
}
async function loadCollectionPage(slug = collectionSlug) {
 const version = ++collectionPageVersion;
 $('collection-page-title').textContent = 'Подборка'; $('collection-page-crumb').textContent = 'Подборка';
 $('collection-page-order').textContent = ''; $('collection-page-count').textContent = '';
 $('collection-page-status').textContent = 'Загружаем подборку…'; $('retry-collection-page').hidden = true;
 $('collection-grid').setAttribute('aria-busy','true'); $('collection-grid').replaceChildren(...collectionPlaceholders());
 try {
  const data = await collectionData(slug,50);
  if (version !== collectionPageVersion) return;
  $('collection-page-title').textContent = data.title; $('collection-page-crumb').textContent = data.title;
  document.title = data.title + ' — Amergination';
  $('collection-page-order').textContent = data.order === 'popularity' ? 'По популярности' : 'По рейтингу Shikimori';
  $('collection-page-count').textContent = data.items.length ? 'Аниме: ' + data.items.length : '';
  $('collection-grid').replaceChildren(...data.items.map(item => cardElement(normalize(item),slug === 'ongoing')));
  $('collection-page-status').textContent = data.items.length ? '' : 'В этой подборке пока нет аниме.';
 } catch (error) {
  if (version !== collectionPageVersion) return;
  $('collection-grid').replaceChildren();
  const missing = error.status === 404;
  $('collection-page-title').textContent = missing ? 'Подборка не найдена' : 'Подборка';
  document.title = $('collection-page-title').textContent + ' — Amergination';
  $('collection-page-status').textContent = missing ? 'Такой подборки нет. Вернитесь на главную и выберите другую.' : 'Не удалось загрузить подборку. Попробуйте ещё раз.';
  $('retry-collection-page').hidden = missing;
 } finally { if (version === collectionPageVersion) $('collection-grid').setAttribute('aria-busy','false'); }
}
function queueThematicShelf(job) {
 if (job.generation !== thematicGeneration || !['idle','error'].includes(job.state)) return;
 job.state = 'queued'; job.retry.disabled = true; job.status.textContent = 'Загружаем подборку…';
 thematicQueue.push(job); pumpThematicQueue();
}
function pumpThematicQueue() {
 while (thematicActive < 2 && thematicQueue.length) {
  const job = thematicQueue.shift();
  if (job.generation !== thematicGeneration || !job.visible) { if (job.state === 'queued') job.state = 'idle'; continue; }
  ++thematicActive; job.state = 'loading';
  loadThematicShelf(job).finally(() => { --thematicActive; pumpThematicQueue(); });
 }
}
async function loadThematicShelf(job) {
 job.retry.hidden = true; job.track.hidden = false; job.track.setAttribute('aria-busy','true');
 try {
  const data = await collectionData(job.slug,12);
  if (job.generation !== thematicGeneration) return;
  job.track.replaceChildren(...data.items.map(item => cardElement(normalize(item))));
  job.track.hidden = !data.items.length; job.state = 'ready';
  job.status.textContent = data.items.length ? '' : 'В этой подборке пока нет аниме.';
  thematicObserver?.unobserve(job.section);
 } catch (error) {
  if (job.generation !== thematicGeneration) return;
  job.track.replaceChildren(); job.track.hidden = true; job.state = 'error';
  job.status.textContent = 'Не удалось загрузить подборку. Попробуйте ещё раз.';
  job.retry.hidden = false; job.retry.disabled = false; thematicObserver?.unobserve(job.section);
 } finally { if (job.generation === thematicGeneration) job.track.setAttribute('aria-busy','false'); }
}
function checkThematicVisibility() {
 const height = window.innerHeight || document.documentElement.clientHeight;
 for (const job of thematicJobs) {
  const bounds = job.section.getBoundingClientRect(); job.visible = bounds.top < height + 160 && bounds.bottom > -160;
  if (job.visible && job.state === 'idle') queueThematicShelf(job);
 }
}
function renderThematicCollections(metadata = []) {
 ++thematicGeneration; thematicObserver?.disconnect(); thematicObserver = null; thematicQueue = []; thematicJobs = [];
 const container = $('thematic-collections'); container.replaceChildren();
 if (!Array.isArray(metadata)) return;
 const seen = new Set();
 for (const item of metadata) {
  if (!item || typeof item.slug !== 'string' || !/^[a-z][a-z0-9-]{0,39}$/.test(item.slug) || typeof item.title !== 'string' || seen.has(item.slug)) continue;
  seen.add(item.slug);
  const section = text('section','','shelf thematic-shelf'); section.id = 'shelf-' + item.slug;
  const heading = text('div','','section-heading'), title = text('h2',''), link = text('a',item.title,'collection-heading-link');
  link.href = collectionHref(item.slug); title.id = 'heading-' + item.slug; title.append(link); heading.append(title);
  section.setAttribute('aria-labelledby',title.id);
  const controls = text('div','','shelf-controls'), track = text('div','','horizontal poster-track'); track.id = 'track-' + item.slug;
  for (const direction of [-1,1]) {
   const button = text('button',direction < 0 ? '←' : '→','arrow'); button.type = 'button';
   button.setAttribute('aria-label',(direction < 0 ? 'Предыдущие аниме: ' : 'Следующие аниме: ') + item.title);
   button.addEventListener('click',() => scrollShelf(track,direction)); controls.append(button);
  }
  heading.append(controls);
  const status = text('p','Загружаем подборку…','subtle thematic-status'); status.setAttribute('role','status');
  const retry = text('button','Повторить загрузку','secondary-button'); retry.type = 'button'; retry.hidden = true;
  track.setAttribute('aria-busy','true'); track.append(...collectionPlaceholders()); section.append(heading,status,retry,track); container.append(section);
  const job = {slug:item.slug,section,track,status,retry,generation:thematicGeneration,state:'idle',visible:false};
  retry.addEventListener('click',() => { job.visible = true; queueThematicShelf(job); }); thematicJobs.push(job);
 }
 if (typeof IntersectionObserver === 'function') {
  const jobs = new Map(thematicJobs.map(job => [job.section,job]));
  thematicObserver = new IntersectionObserver(entries => {
   for (const entry of entries) { const job = jobs.get(entry.target); if (!job) continue; job.visible = entry.isIntersecting; if (job.visible && job.state === 'idle') queueThematicShelf(job); }
  },{rootMargin:'160px 0px'});
  for (const job of thematicJobs) thematicObserver.observe(job.section);
 } else {
  if (!thematicFallbackBound) { window.addEventListener('scroll',checkThematicVisibility,{passive:true}); window.addEventListener('resize',checkThematicVisibility); thematicFallbackBound = true; }
  checkThematicVisibility();
 }
}
function renderDetail(page) {
 syncAnimeAddress(page.details);
 window.watchlistAnime = {source: page.details.source, id: String(page.details.external_id), title: page.details.title, episodes_total:page.details.episodes_total || null, poster_url:page.details.poster_url, slug:page.details.slug};
 window.dispatchEvent(new Event('watchlist-anime'));
 window.discussionAnime = {source: page.details.source, id: page.details.external_id, title: page.details.title};
 window.dispatchEvent(new Event('anime-detail'));
 const card = normalize(page.details);
 document.title = card.title + ' — Amergination';
 $('breadcrumb-title').textContent = card.title; $('detail-title').textContent = card.title; $('detail-original').textContent = card.original ?? '';
 $('detail-type').textContent = [card.year, card.kind, page.details.episode_duration].filter(Boolean).join(' / ');
 setPosterImage($('detail-poster'), card.image, card.title, false);
 $('detail-score').textContent = card.score ?? ''; $('detail-score').hidden = !card.score;
 $('detail-tags').replaceChildren(...card.genres.map(value => text('span', value)));
 $('detail-description').textContent = page.details.description || 'У источника пока нет описания этого аниме.';
 $('detail-source').textContent = 'Данные: ' + (page.details.source === 'shikimori' ? 'Shikimori' : 'AnimeGo') + (page.warnings.length ? ' · ' + page.warnings.join('. ') : '');
 renderCards('related-track', page.related.map(normalize));
 if (!page.related.length) $('related-track').append(text('p', 'Связанные аниме не найдены.', 'subtle'));
 playbackId = page.playback.animego_id;
 if (page.playback.status === 'matched' && playbackId) initPlayer();
 else {
  selectOptions($('episode-select'), [['', 'Недоступно']]);
  $('player-status').textContent = page.playback.status === 'ambiguous' ? 'Найдено несколько вариантов в AnimeGo. Автоматический выбор плеера недоступен.' : page.playback.status === 'unavailable' ? 'Источник плеера временно недоступен. Обновите страницу позже.' : 'Для этого тайтла пока не найден плеер AnimeGo.';
 }
}
async function init() {
 if (collectionSlug) {
  $('home').hidden = true; $('collection-page').hidden = false;
  document.querySelectorAll('.site-header>nav a').forEach(link => link.classList.remove('nav-active'));
  $('nav-collections').classList.add('nav-active'); await loadCollectionPage(collectionSlug); return;
 }
 if (profilePage) { $('home').hidden = true; $('profile-page').hidden = false; document.title = 'Профиль — Amergination'; return; }
 if (listPage) { $('home').hidden = true; $('my-list-page').hidden = false; document.title = 'Мой список — Amergination'; return; }
 if (pageId) {
  $('home').hidden = true; $('anime-page').hidden = false; $('detail-title').textContent = 'Загружаем аниме…';
  try {
   let slug = pageRoute.slug || new URLSearchParams(location.search).get('slug');
   if (!slug && pageSource === 'animego') { try { slug = JSON.parse(sessionStorage.getItem('anime:animego:' + pageId))?.slug; } catch {} }
   renderDetail(await catalogApi(pageSource + '/' + pageId, slug ? {slug} : {}));
  } catch (error) { $('detail-title').textContent = 'Не удалось загрузить аниме'; $('detail-description').textContent = error.message; $('player-status').textContent = 'Данные недоступны. Обновите страницу или выберите тайтл через поиск.'; }
  return;
 }
 try {
  const data = await catalogApi('home');
  renderCards('ongoing-track', data.ongoing.map(normalize), true);
  renderCards('collection-track', data.popular.map(normalize));
  renderThematicCollections(data.collections);
  if (!data.ongoing.length) $('ongoing-track').append(text('p', 'Онгоинги временно недоступны.', 'subtle'));
  if (!data.popular.length) $('collection-track').append(text('p', 'Подборка временно недоступна.', 'subtle'));
  $('catalog-status').textContent = data.warnings.join('. ');
 } catch (error) {
  for (const target of ['ongoing-track', 'collection-track']) $(target).replaceChildren(text('p', error.message, 'subtle'));
 }
}
document.querySelectorAll('[data-scroll]').forEach(button => button.addEventListener('click', () => scrollShelf($(button.dataset.scroll),Number(button.dataset.direction))));
$('retry-collection-page').addEventListener('click',() => loadCollectionPage(collectionSlug));
$('open-search').addEventListener('click', () => { $('search-dialog').showModal(); $('search-input').focus(); });
$('open-auth').addEventListener('click', () => window.openAccount ? window.openAccount() : $('auth-dialog').showModal());
document.querySelectorAll('.discussion-auth').forEach(button => button.addEventListener('click', () => $('auth-dialog').showModal()));
document.querySelectorAll('.close-dialog').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('click', event => { const rect = dialog.getBoundingClientRect(); if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close(); }));
$('search-form').addEventListener('submit', async event => {
 event.preventDefault(); const query = $('search-input').value.trim(); const version = ++searchVersion; $('search-status').textContent = 'Поиск…'; $('search-results').replaceChildren();
 try { const rows = await api('search', { q: query }); if (version !== searchVersion) return; renderCards('search-results', rows.map(normalize)); $('search-status').textContent = rows.length ? 'Найдено: ' + rows.length : 'Ничего не нашлось. Попробуй другое название.'; }
 catch (error) { if (version === searchVersion) $('search-status').textContent = error.message; }
});

$('episode-select').addEventListener('change',async()=>{
 await episodeChanged();
});
$('player-select').addEventListener('change',()=>{
 playerInteracted();
 ++playerVersion;cancelVoiceEpisodes();stopPlayer();renderVoices();
 resetEpisodeChoices();$('voice-episodes-status').textContent='';
 $('player-status').textContent='Выберите озвучку — серия загрузится автоматически.';
});
$('voice-select').addEventListener('change',()=>{playerInteracted();return chooseVoice();});
$('previous-episode').addEventListener('click',()=>navigateEpisode(-1));
$('next-episode').addEventListener('click',()=>navigateEpisode(1));
$('retry-voice-episodes').addEventListener('click',async()=>{
 playerInteracted();
 const voice=selectedVoice();if(!voice)return;
 const previous=$('episode-select').value;cancelVoiceEpisodes();const run=voiceEpisodesVersion;
 await loadVoiceEpisodes(voice,run);
 if(run===voiceEpisodesVersion && $('episode-select').value && ($('episode-select').value!==previous || $('embedded-video').hidden))await openPlayer();
});
function activateTab(name) { for (const id of ['comments', 'reviews']) { const active = id === name; $(id + '-tab').setAttribute('aria-selected', String(active)); $(id + '-tab').tabIndex = active ? 0 : -1; $(id + '-panel').hidden = !active; } }
for (const name of ['comments', 'reviews']) { $(name + '-tab').addEventListener('click', () => activateTab(name)); $(name + '-tab').addEventListener('keydown', event => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); const next = event.key === 'Home' ? 'comments' : event.key === 'End' ? 'reviews' : name === 'comments' ? 'reviews' : 'comments'; activateTab(next); $(next + '-tab').focus(); } }); }
const news = [ ['Подборка приключенческого аниме', 'Иногда главное в аниме — само путешествие. Тихие встречи, маленькие открытия и герои, к которым незаметно привязываешься. Здесь будет редакционная подборка таких историй.'], ['Аниме нового сезона', 'Смена сезона — хороший повод найти новое любимое аниме. Здесь появятся анонсы, премьеры и короткие заметки редакции.'], ['Наруто: порядок просмотра', 'Коноха, команда семь и мечта стать Хокаге. Здесь будет материал о мире Наруто и порядке просмотра связанных историй.'] ];
document.querySelectorAll('[data-news]').forEach(button => button.addEventListener('click', () => { const item = news[Number(button.dataset.news)]; $('news-title').textContent = item[0]; $('news-text').textContent = item[1]; $('news-dialog').showModal(); }));
init();
