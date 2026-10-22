'use strict';
const $ = id => document.getElementById(id);
let catalog = [], translations = [], playerVersion = 0, searchVersion = 0, toastTimer;
const pageRoute = location.pathname.match(/^\/anime\/(?:(shikimori|animego)\/)?([0-9]+)$/);
const pageId = pageRoute?.[2], pageSource = pageRoute?.[1] ?? 'animego';
let playbackId = null;
const listPage = location.pathname === '/my-list';
const profilePage = location.pathname === '/profile';
function text(tag, value, className) { const el = document.createElement(tag); el.textContent = value; if (className) el.className = className; return el; }
function safeUrl(value) { try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : null; } catch { return null; } }
function normalize(card) { return { id: String(card.id ?? card.external_id), title: card.title, original: card.original_title, image: safeUrl(card.image ?? card.poster_url), year: card.year, kind: card.type ?? card.kind, score: card.rating ?? card.score, source: card.source ?? 'animego', slug: card.slug, genres: card.genres ?? [], relation: card.relation }; }
function saveCard(card) { try { sessionStorage.setItem('anime:' + card.source + ':' + card.id, JSON.stringify(card)); } catch {} }
function cardElement(card, ongoing = false) {
 const link = document.createElement('a'); link.className = 'anime-card'; link.href = '/anime/' + card.source + '/' + encodeURIComponent(card.id) + (card.slug ? '?slug=' + encodeURIComponent(card.slug) : ''); link.addEventListener('click', () => saveCard(card));
 const poster = text('div', '', 'poster'); poster.append(text('span', 'Нет постера', 'poster-fallback'));
 if (card.image) { const img = document.createElement('img'); img.src = card.image; img.alt = card.title; img.loading = 'lazy'; img.referrerPolicy = 'no-referrer'; img.addEventListener('error', () => img.remove()); poster.append(img); }
 if (card.score) poster.append(text('span', card.score, 'score'));
 if (ongoing) poster.append(text('span', 'Онгоинг', 'poster-label'));
 link.append(poster, text('h3', card.title), text('p', [card.relation, card.year, card.kind].filter(Boolean).join(' · '))); return link;
}
function renderCards(target, cards, ongoing = false) { $(target).replaceChildren(...cards.map(card => cardElement(card, ongoing))); }
function toast(message) { clearTimeout(toastTimer); $('toast').textContent = message; $('toast').hidden = false; toastTimer = setTimeout(() => $('toast').hidden = true, 4000); }
async function api(path, params) { const response = await fetch('/api/v1/anime/animego/' + path + '?' + new URLSearchParams(params)); const data = await response.json(); if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Не удалось загрузить данные. Попробуй ещё раз.'); return data; }
function selectOptions(select, values) { select.replaceChildren(...values.map(([value, label]) => { const option = text('option', label); option.value = value; return option; })); }
function stopPlayer() { $('embedded-video').hidden = true; $('embedded-video').removeAttribute('src'); $('player-placeholder').hidden = false; }
async function loadVoices(version) {
 translations = []; $('voice-select').disabled = true; $('start-player').disabled = true; selectOptions($('voice-select'), [['', 'Загружаем…']]);
 const data = await api('voices', { anime_id: playbackId, episode: $('episode-select').value });
 if (version !== playerVersion) return;
 translations = data.translations.filter(voice => ['kodik', 'sibnet', 'aniboom', 'cvh'].includes(voice.player) && voice.embed_url);
 selectOptions($('voice-select'), translations.length ? translations.map((voice, i) => [i, voice.name + ' · ' + voice.player]) : [['', 'Нет озвучок']]);
 $('voice-select').disabled = !translations.length; $('start-player').disabled = !translations.length;
 $('player-status').textContent = translations.length ? 'Выбери озвучку и начни просмотр.' : 'Для этой серии пока нет доступных озвучек.';
}
async function initPlayer() {
 const version = ++playerVersion;
 try {
  const data = await api('episodes', { anime_id: playbackId });
  if (version !== playerVersion) return;
  selectOptions($('episode-select'), data.episodes.length ? data.episodes.map(ep => [ep.number, 'Серия ' + ep.number]) : [[1, 'Эпизод 1']]);
  $('episode-select').disabled = false; await loadVoices(version);
 } catch (error) { if (version === playerVersion) { selectOptions($('episode-select'), [['', 'Недоступно']]); $('player-status').textContent = error.message; } }
}
async function catalogApi(path, params = {}) {
 const response = await fetch('/api/v1/anime/catalog/' + path + '?' + new URLSearchParams(params));
 const data = await response.json();
 if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Каталог временно недоступен');
 return data;
}
function renderDetail(page) {
 window.watchlistAnime = {source: page.details.source, id: String(page.details.external_id), title: page.details.title, episodes_total:page.details.episodes_total || null, poster_url:page.details.poster_url, slug:page.details.slug};
 window.dispatchEvent(new Event('watchlist-anime'));
 window.discussionAnime = {source: page.details.source, id: page.details.external_id, title: page.details.title};
 window.dispatchEvent(new Event('anime-detail'));
 const card = normalize(page.details);
 document.title = card.title + ' — Amergination';
 $('breadcrumb-title').textContent = card.title; $('detail-title').textContent = card.title; $('detail-original').textContent = card.original ?? '';
 $('detail-type').textContent = [card.year, card.kind, page.details.episode_duration].filter(Boolean).join(' / ');
 if (card.image) { $('detail-poster').src = card.image; $('detail-poster').alt = card.title; } else { $('detail-poster').hidden = true; }
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
 if (profilePage) { $('home').hidden = true; $('profile-page').hidden = false; document.title = 'Профиль — Amergination'; return; }
 if (listPage) { $('home').hidden = true; $('my-list-page').hidden = false; document.title = 'Мой список — Amergination'; return; }
 if (pageId) {
  $('home').hidden = true; $('anime-page').hidden = false; $('detail-title').textContent = 'Загружаем аниме…';
  try {
   let slug = new URLSearchParams(location.search).get('slug');
   if (!slug && pageSource === 'animego') { try { slug = JSON.parse(sessionStorage.getItem('anime:animego:' + pageId))?.slug; } catch {} }
   renderDetail(await catalogApi(pageSource + '/' + pageId, slug ? {slug} : {}));
  } catch (error) { $('detail-title').textContent = 'Не удалось загрузить аниме'; $('detail-description').textContent = error.message; $('player-status').textContent = 'Данные недоступны. Обновите страницу или выберите тайтл через поиск.'; }
  return;
 }
 try {
  const data = await catalogApi('home');
  renderCards('ongoing-track', data.ongoing.map(normalize), true);
  renderCards('collection-track', data.popular.map(normalize));
  if (!data.ongoing.length) $('ongoing-track').append(text('p', 'Онгоинги временно недоступны.', 'subtle'));
  if (!data.popular.length) $('collection-track').append(text('p', 'Подборка временно недоступна.', 'subtle'));
  $('catalog-status').textContent = data.warnings.join('. ');
 } catch (error) {
  for (const target of ['ongoing-track', 'collection-track']) $(target).replaceChildren(text('p', error.message, 'subtle'));
 }
}
document.querySelectorAll('[data-scroll]').forEach(button => button.addEventListener('click', () => $(button.dataset.scroll).scrollBy({ left: Number(button.dataset.direction) * $(button.dataset.scroll).clientWidth * .75, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' })));
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

$('episode-select').addEventListener('change', async () => { const version = ++playerVersion; stopPlayer(); $('player-status').textContent = 'Загружаем озвучки…'; try { await loadVoices(version); } catch (error) { if (version === playerVersion) $('player-status').textContent = error.message; } });
$('voice-select').addEventListener('change', () => { ++playerVersion; stopPlayer(); $('start-player').disabled = !translations.length; });
$('start-player').addEventListener('click', async () => {
 const voice = translations[Number($('voice-select').value)]; if (!voice) return;
 const version = ++playerVersion; $('start-player').disabled = true; stopPlayer(); $('player-status').textContent = 'Открываем плеер…';
 try { const data = await api('player', { anime_id: playbackId, episode: $('episode-select').value, translation_id: voice.id, player: voice.player }); if (version !== playerVersion) return; const embed = safeUrl(data.embed_url); if (!embed) throw Error('Плеер вернул некорректную ссылку'); $('embedded-video').src = embed; $('embedded-video').hidden = false; $('player-placeholder').hidden = true; $('player-status').textContent = 'Плеер готов. Нажми воспроизведение внутри видео.'; }
 catch (error) { if (version === playerVersion) $('player-status').textContent = error.message; }
 finally { if (version === playerVersion) $('start-player').disabled = !translations.length; }
});
function activateTab(name) { for (const id of ['comments', 'reviews']) { const active = id === name; $(id + '-tab').setAttribute('aria-selected', String(active)); $(id + '-tab').tabIndex = active ? 0 : -1; $(id + '-panel').hidden = !active; } }
for (const name of ['comments', 'reviews']) { $(name + '-tab').addEventListener('click', () => activateTab(name)); $(name + '-tab').addEventListener('keydown', event => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); const next = event.key === 'Home' ? 'comments' : event.key === 'End' ? 'reviews' : name === 'comments' ? 'reviews' : 'comments'; activateTab(next); $(next + '-tab').focus(); } }); }
const news = [ ['Подборка приключенческого аниме', 'Иногда главное в аниме — само путешествие. Тихие встречи, маленькие открытия и герои, к которым незаметно привязываешься. Здесь будет редакционная подборка таких историй.'], ['Аниме нового сезона', 'Смена сезона — хороший повод найти новое любимое аниме. Здесь появятся анонсы, премьеры и короткие заметки редакции.'], ['Наруто: порядок просмотра', 'Коноха, команда семь и мечта стать Хокаге. Здесь будет материал о мире Наруто и порядке просмотра связанных историй.'] ];
document.querySelectorAll('[data-news]').forEach(button => button.addEventListener('click', () => { const item = news[Number(button.dataset.news)]; $('news-title').textContent = item[0]; $('news-text').textContent = item[1]; $('news-dialog').showModal(); }));
init();
