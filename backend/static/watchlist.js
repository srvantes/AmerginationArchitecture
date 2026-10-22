'use strict';
const wlStatuses = [['planned', 'Запланировано'], ['watching', 'Смотрю'], ['completed', 'Просмотрено'], ['on_hold', 'На паузе'], ['dropped', 'Брошено']];
let wlFilter = '', wlRows = [], wlVersion = 0, wlDetailVersion = 0, wlEntry = null, wlBusy = false, wlDetailReady = false;
const wlPath = 'users/me/watchlist';
function wlProgress(value, total = null) {
 if (!/^\d+$/.test(String(value))) throw Error('Введите целое число просмотренных серий от 0.');
 const count = Number(value);
 if (!Number.isSafeInteger(count) || count > 2147483647 || (total && count > total)) throw Error(total ? `Укажите число от 0 до ${total}.` : 'Слишком большое число серий.');
 return count;
}
function wlDetailButton() {
 $('add-list').disabled = !!window.watchlistAnime && !!dsUser && !wlDetailReady;
 $('add-list').textContent = wlEntry ? wlStatuses.find(([value]) => value === wlEntry.status)[1] + ' ▾' : '＋ В мой список';
}
async function wlLoadDetail() {
 const version = ++wlDetailVersion; wlEntry = null; wlDetailReady = false; wlDetailButton();
 const anime = window.watchlistAnime;
 if (!anime || !dsUser) return;
 try {
  const entries = await dsApi(wlPath + '?' + new URLSearchParams({anime_source: anime.source, anime_external_id: anime.id, limit: 1}));
  if (version !== wlDetailVersion) return;
  wlEntry = entries[0] || null; wlDetailReady = true; wlDetailButton();
 } catch (error) {
  if (version === wlDetailVersion) { $('add-list').disabled = false; toast(error.message); }
 }
}
function wlFilters() {
 $('watchlist-filters').replaceChildren(...[['', 'Все'], ...wlStatuses].map(([value, label]) => {
  const button = text('button', label, 'secondary-button'); button.type = 'button';
  button.setAttribute('aria-pressed', String(value === wlFilter));
  button.addEventListener('click', () => { wlFilter = value; wlFilters(); wlLoad(); }); return button;
 }));
}
function wlRender() {
 $('watchlist-entries').replaceChildren(...wlRows.map(entry => {
  const row = text('article', '', 'watchlist-entry'), copy = text('div', '', 'watchlist-copy');
  const title = text('a', entry.anime_title, 'watchlist-title');
  // Kodik entries have no catalog detail route yet.
  let cachedCard;
  try { cachedCard = JSON.parse(sessionStorage.getItem('anime:' + entry.anime_source + ':' + entry.anime_external_id)); } catch {}
  const slug = entry.anime_slug || cachedCard?.slug;
  if (['animego', 'shikimori'].includes(entry.anime_source)) title.href = '/anime/' + entry.anime_source + '/' + encodeURIComponent(entry.anime_external_id) + (slug ? '?slug=' + encodeURIComponent(slug) : '');
  const poster = text('a', '', 'watchlist-poster');
  poster.setAttribute('aria-label', 'Открыть аниме: ' + entry.anime_title);
  if (title.href) poster.href = title.href;
  poster.append(text('span', 'Нет постера', 'watchlist-poster-fallback'));
  const posterUrl = safeUrl(entry.poster_url || cachedCard?.image);
  if (posterUrl) {
   const image = document.createElement('img'); image.src = posterUrl; image.alt = ''; image.loading = 'lazy'; image.referrerPolicy = 'no-referrer';
   image.addEventListener('error', () => image.remove()); poster.append(image);
  }
  const description = text('div', '', 'watchlist-description');
  description.append(title, text('p', 'Просмотрено серий: ' + entry.episodes_watched + (entry.episodes_total ? ' / ' + entry.episodes_total : ''), 'subtle'));
  copy.append(poster, description);
  const controls = text('div', '', 'watchlist-controls'), select = document.createElement('select');
  selectOptions(select, wlStatuses); select.value = entry.status;
  select.setAttribute('aria-label', 'Статус: ' + entry.anime_title);
  select.addEventListener('change', async () => {
   const version = wlVersion; select.disabled = true;
   try {
    const updated = await dsApi(wlPath + '/' + entry.id, {method: 'PATCH', body: JSON.stringify({status: select.value})});
    if (version !== wlVersion) return;
    Object.assign(entry, updated); await wlLoad(); toast('Статус сохранён');
   } catch (error) { if (version === wlVersion) { select.value = entry.status; toast(error.message); } }
   finally { select.disabled = false; }
  });
  const remove = text('button', 'Убрать', 'secondary-button'); remove.type = 'button';
  remove.setAttribute('aria-label', 'Убрать из списка: ' + entry.anime_title);
  remove.addEventListener('click', async () => {
   const version = wlVersion; remove.disabled = true;
   try { await dsApi(wlPath + '/' + entry.id, {method:'DELETE'}); if (version !== wlVersion) return; await wlLoad(); toast('Аниме убрано из списка'); }
   catch (error) { if (version === wlVersion) toast(error.message); }
   finally { remove.disabled = false; }
  });
  const progressForm = text('form', '', 'watchlist-progress-form');
  const count = document.createElement('input'); count.type = 'number'; count.min = '0'; count.step = '1'; count.required = true;
  count.max = entry.episodes_total || 2147483647; count.value = entry.episodes_watched;
  count.setAttribute('aria-label', 'Просмотрено серий: ' + entry.anime_title);
  const save = text('button', 'Сохранить серии', 'secondary-button'); save.type = 'submit';
  const progressStatus = text('p', '', 'subtle'); progressStatus.setAttribute('role','status');
  progressForm.append(count, save, progressStatus);
  progressForm.addEventListener('submit', async event => {
   event.preventDefault(); const version = wlVersion;
   try {
    const episodes = wlProgress(count.value, entry.episodes_total);
    count.disabled = true; save.disabled = true; select.disabled = true; remove.disabled = true; progressStatus.textContent = 'Сохраняем…';
    const updated = await dsApi(wlPath + '/' + entry.id, {method:'PATCH', body:JSON.stringify({episodes_watched:episodes})});
    if (version !== wlVersion) return;
    Object.assign(entry, updated); wlRender(); toast('Прогресс сохранён');
   } catch (error) { if (version === wlVersion) progressStatus.textContent = error.message; }
   finally { count.disabled = false; save.disabled = false; select.disabled = false; remove.disabled = false; }
  });
  controls.append(select, remove); row.append(copy, controls, progressForm); return row;
 }));
}
async function wlLoad(append = false) {
 if (!listPage) return;
 const version = ++wlVersion;
 $('watchlist-login').hidden = !!dsUser; $('watchlist-more').hidden = true;
 if (!append) { wlRows = []; wlRender(); }
 if (!dsUser) { $('watchlist-status').textContent = dsToken ? 'Проверяем вход…' : 'Войдите, чтобы открыть свой список аниме.'; return; }
 $('watchlist-status').textContent = 'Загружаем список…';
 try {
  const params = new URLSearchParams({limit:20, offset:append ? wlRows.length : 0}); if (wlFilter) params.set('status', wlFilter);
  const rows = await dsApi(wlPath + '?' + params);
  if (version !== wlVersion) return;
  wlRows = append ? [...wlRows, ...rows] : rows; wlRender();
  $('watchlist-more').hidden = rows.length < 20;
  $('watchlist-status').textContent = wlRows.length ? '' : wlFilter ? 'В этом статусе пока нет аниме.' : 'Список пока пуст. Добавьте аниме со страницы тайтла.';
 } catch (error) { if (version === wlVersion) $('watchlist-status').textContent = error.message; }
}
function wlDialogView() {
 const total = wlEntry?.episodes_total || window.watchlistAnime?.episodes_total;
 $('watchlist-progress').value = wlEntry?.episodes_watched || 0;
 $('watchlist-progress').max = total || 2147483647;
 $('watchlist-progress-hint').textContent = total ? 'Всего серий: ' + total : 'Общее число серий пока неизвестно.';
 $('watchlist-select').value = wlEntry?.status || 'planned';
 $('watchlist-save').textContent = wlEntry ? 'Сохранить' : 'Добавить';
 $('watchlist-remove').hidden = !wlEntry;
}
$('add-list').addEventListener('click', async () => {
 if (!dsUser) { $('auth-dialog').showModal(); return; }
 if (!window.watchlistAnime) { toast('Сначала дождитесь загрузки аниме.'); return; }
 if (!wlDetailReady) { await wlLoadDetail(); if (!wlDetailReady) return; }
 $('watchlist-anime-title').textContent = window.watchlistAnime.title;
 $('watchlist-dialog-status').textContent = ''; wlDialogView(); $('watchlist-dialog').showModal();
});
async function wlSave(remove = false) {
 if (wlBusy || !dsUser || !window.watchlistAnime) return;
 const version = wlDetailVersion, anime = window.watchlistAnime;
 let progress;
 if (!remove) { try { progress = wlProgress($('watchlist-progress').value, wlEntry?.episodes_total || anime.episodes_total); }
 catch (error) { $('watchlist-dialog-status').textContent = error.message; return; } }
 wlBusy = true; $('watchlist-save').disabled = true; $('watchlist-remove').disabled = true; $('watchlist-select').disabled = true;
 $('watchlist-progress').disabled = true;
 $('watchlist-dialog-status').textContent = 'Сохраняем…';
 try {
  const payload = wlEntry ? {status:$('watchlist-select').value} : {anime_source:anime.source, anime_external_id:anime.id, anime_title:anime.title, status:$('watchlist-select').value};
  if (!remove) payload.episodes_watched = progress;
  if (!remove && !wlEntry) { payload.poster_url = safeUrl(anime.poster_url); if (anime.slug) payload.anime_slug = anime.slug; }
  const entry = await dsApi(wlPath + (wlEntry ? '/' + wlEntry.id : ''), {method:remove ? 'DELETE' : wlEntry ? 'PATCH' : 'POST', ...(remove ? {} : {body:JSON.stringify(payload)})});
  if (version !== wlDetailVersion) return;
  wlEntry = entry; wlDetailButton(); $('watchlist-dialog').close(); toast(remove ? 'Аниме убрано из списка' : 'Список сохранён');
 } catch (error) {
  if (version !== wlDetailVersion) return;
  $('watchlist-dialog-status').textContent = error.status === 409 ? 'Аниме уже добавлено. Можно изменить его статус.' : error.message;
  if (error.status === 409) { await wlLoadDetail(); wlDialogView(); }
 } finally { wlBusy = false; $('watchlist-save').disabled = false; $('watchlist-remove').disabled = false; $('watchlist-select').disabled = false; $('watchlist-progress').disabled = false; }
}
$('watchlist-form').addEventListener('submit', event => { event.preventDefault(); return wlSave(); });
$('watchlist-remove').addEventListener('click', () => wlSave(true));
$('watchlist-more').addEventListener('click', () => wlLoad(true));
$('watchlist-login').addEventListener('click', () => $('auth-dialog').showModal());
window.watchlistAuthChanged = () => {
 $('watchlist-dialog').close(); wlLoadDetail(); wlLoad();
};
window.addEventListener('watchlist-anime', wlLoadDetail);
if (listPage) {
 document.querySelectorAll('.site-header nav a').forEach(link => link.classList.toggle('nav-active', link.pathname === '/my-list'));
}
selectOptions($('watchlist-select'), wlStatuses);
wlFilters(); wlLoadDetail(); wlLoad();
