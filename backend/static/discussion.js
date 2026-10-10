'use strict';
let dsToken = sessionStorage.getItem('amergination-token'), dsUser = null, dsRegister = false;
let dsAccess = null, dsVersion = 0, dsEditing = {comments: null, reviews: null};
let dsData = {comments: {items: [], total: 0}, reviews: {items: [], total: 0}};
let dsDrafts = {comments: null, reviews: null};
const dsWords = value => (value.match(/\S+/gu) || []).filter(word => /[\p{L}\p{N}]/u.test(word)).length;

async function dsApi(path, options = {}) {
 const headers = {'Content-Type': 'application/json', ...(dsToken ? {Authorization: 'Bearer ' + dsToken} : {})};
 const response = await fetch('/api/v1/' + path, {...options, headers});
 if (response.status === 204) return null;
 const data = await response.json();
 if (!response.ok) {
  if (response.status === 401) { dsToken = null; dsUser = null; dsAccess = null; dsDrafts = {comments: null, reviews: null}; sessionStorage.removeItem('amergination-token'); dsAuthView(); dsRenderForms(); }
  throw Error(typeof data.detail === 'string' ? data.detail : data.detail?.[0]?.msg?.replace(/^Value error, /, '') || 'Не удалось выполнить действие. Попробуйте ещё раз.');
 }
 return data;
}
function dsAuthView() {
 $('open-auth').querySelector('span').textContent = dsUser ? dsUser.username : 'Войти';
 $('auth-form').hidden = !!dsUser; $('auth-switch').hidden = !!dsUser; $('auth-logout').hidden = !dsUser;
 $('auth-status').textContent = dsUser ? 'Вы вошли как ' + dsUser.username : '';
}
async function dsRestore() {
 if (!dsToken) return;
 try { dsUser = await dsApi('auth/me'); dsAccess = await dsApi('comments/eligibility'); dsAuthView(); if (window.discussionAnime) await dsReload(); }
 catch (error) { $('auth-status').textContent = error.message; }
}
$('auth-switch').addEventListener('click', () => {
 dsRegister = !dsRegister; $('auth-email-label').hidden = !dsRegister; $('auth-email').required = dsRegister;
 $('auth-password').autocomplete = dsRegister ? 'new-password' : 'current-password';
 $('auth-submit').textContent = dsRegister ? 'Создать аккаунт' : 'Войти';
 $('auth-switch').textContent = dsRegister ? 'Уже есть аккаунт' : 'Создать аккаунт'; $('auth-status').textContent = '';
});
$('auth-form').addEventListener('submit', async event => {
 event.preventDefault(); $('auth-submit').disabled = true; $('auth-status').textContent = 'Подождите…';
 try {
  const credentials = {username: $('auth-username').value.trim(), password: $('auth-password').value};
  if (dsRegister) await dsApi('auth/register', {method: 'POST', body: JSON.stringify({...credentials, email: $('auth-email').value.trim()})});
  const token = await dsApi('auth/login', {method: 'POST', body: JSON.stringify(credentials)});
  dsToken = token.access_token; sessionStorage.setItem('amergination-token', dsToken);
  $('auth-password').value = ''; await dsRestore(); if (dsUser) $('auth-dialog').close();
 } catch (error) { $('auth-status').textContent = error.message; }
 finally { $('auth-submit').disabled = false; }
});
$('auth-logout').addEventListener('click', async () => {
 try { await dsApi('auth/logout', {method: 'POST'}); dsToken = null; dsUser = null; dsAccess = null; dsDrafts = {comments: null, reviews: null}; sessionStorage.removeItem('amergination-token'); dsEditing = {comments: null, reviews: null}; dsAuthView(); $('auth-dialog').close(); if (window.discussionAnime) await dsReload(); }
 catch (error) { $('auth-status').textContent = error.message; }
});
function dsButton(label, action, className = 'secondary-button') {
 const button = text('button', label, className); button.type = 'button';
 button.addEventListener('click', async () => { button.disabled = true; try { await action(); } catch (error) { toast(error.message); } finally { button.disabled = false; } });
 return button;
}
function dsShowAuth() { $('auth-dialog').showModal(); }
function dsField(form, label, field) { const wrapper = text('label', label); wrapper.append(field); form.append(wrapper); return field; }
function dsRenderForms() {
 if (!window.discussionAnime) return;
 for (const kind of ['comments', 'reviews']) {
  const area = $(kind + '-form-area'); area.replaceChildren();
  if (!dsUser) { area.append(text('p', kind === 'comments' ? 'Войдите, чтобы оставлять комментарии и лайки.' : 'Право на рецензии открывается после 11 лайков под вашими комментариями.', 'subtle'), dsButton('Войти', dsShowAuth)); continue; }
  if (kind === 'reviews' && !dsAccess?.can_write_reviews && !dsEditing.reviews) { area.append(text('p', `Для рецензий нужно получить 11 лайков под комментариями. Сейчас: ${dsAccess?.likes_received ?? 0}. Достигнутый доступ сохраняется.`, 'subtle')); continue; }
  const editing = dsEditing[kind], own = dsData[kind].items.find(item => item.user_id === dsUser.id);
  const draft = dsDrafts[kind]?.editingId === (editing?.id || 'new') ? dsDrafts[kind] : null;
  if (kind === 'reviews' && own && !editing) { area.append(text('p', 'Ваша рецензия уже опубликована. Её можно редактировать ниже.', 'subtle')); continue; }
  const form = document.createElement('form'); form.className = 'discussion-form'; area.append(form);
  let title, spoiler;
  if (kind === 'reviews') { title = document.createElement('input'); title.required = true; title.maxLength = 200; title.value = draft?.title ?? editing?.title ?? ''; dsField(form, 'Заголовок рецензии', title); }
  const body = document.createElement('textarea'); body.id = kind + '-text'; body.required = true; body.rows = kind === 'comments' ? 4 : 10; body.maxLength = kind === 'comments' ? 20000 : 100000; body.value = draft?.text ?? editing?.text ?? '';
  dsField(form, kind === 'comments' ? 'Комментарий' : 'Рецензия', body);
  const counter = text('p', '', 'subtle'); form.append(counter);
  const updateCounter = () => { const words = dsWords(body.value); counter.textContent = kind === 'comments' ? `${words} / 250 слов` : `${words} слов · от 250 до 1500`; counter.classList.toggle('word-limit', words > (kind === 'comments' ? 250 : 1500)); };
  body.addEventListener('input', updateCounter); updateCounter();
  if (kind === 'reviews') { spoiler = document.createElement('select'); spoiler.required = true; selectOptions(spoiler, [['', 'Укажите наличие спойлеров'], ['false', 'Без спойлеров'], ['true', 'Есть спойлеры']]); spoiler.value = editing ? String(editing.has_spoilers) : ''; dsField(form, 'Спойлеры', spoiler); }
  else { spoiler = document.createElement('input'); spoiler.type = 'checkbox'; spoiler.checked = editing?.has_spoilers || false; const label = text('label', '', 'spoiler-checkbox'); label.append(spoiler, text('span', 'Есть спойлеры — скрыть текст до раскрытия')); form.append(label); }
  if (draft) { if (kind === 'reviews') spoiler.value = draft.spoiler; else spoiler.checked = draft.spoiler; }
  const saveDraft = () => { dsDrafts[kind] = {editingId: editing?.id || 'new', title: title?.value, text: body.value, spoiler: kind === 'reviews' ? spoiler.value : spoiler.checked}; };
  body.addEventListener('input', saveDraft); title?.addEventListener('input', saveDraft); spoiler.addEventListener('change', saveDraft);
  const submit = text('button', editing ? 'Сохранить изменения' : 'Опубликовать', 'gold-button'); submit.type = 'submit'; form.append(submit);
  if (editing) form.append(dsButton('Отменить', () => { dsEditing[kind] = null; dsDrafts[kind] = null; dsRenderForms(); }));
  const status = text('p', '', 'subtle'); status.setAttribute('role', 'status'); form.append(status);
  form.addEventListener('submit', async event => {
   event.preventDefault(); const words = dsWords(body.value), min = kind === 'comments' ? 1 : 250, max = kind === 'comments' ? 250 : 1500;
   if (words < min || words > max) { status.textContent = `Нужно от ${min} до ${max} слов.`; return; }
   submit.disabled = true;
   try {
    const anime = window.discussionAnime, payload = {text: body.value, has_spoilers: kind === 'reviews' ? spoiler.value === 'true' : spoiler.checked};
    if (kind === 'reviews') payload.title = title.value;
    if (!editing) { payload.anime_source = anime.source; payload.anime_external_id = anime.id; if (kind === 'reviews') payload.anime_title = anime.title; }
    await dsApi(kind + '/' + (editing?.id || ''), {method: editing ? 'PATCH' : 'POST', body: JSON.stringify(payload)});
    dsEditing[kind] = null; dsDrafts[kind] = null; await dsReload(); toast(editing ? 'Изменения сохранены' : 'Опубликовано');
   } catch (error) { status.textContent = error.message; }
   finally { submit.disabled = false; }
  });
 }
}
function dsRenderList(kind) {
 const area = $(kind + '-list'); area.replaceChildren();
 if (!dsData[kind].items.length) area.append(text('p', kind === 'comments' ? 'Комментариев пока нет.' : 'Рецензий пока нет.', 'subtle'));
 for (const item of dsData[kind].items) {
  const article = text('article', '', 'discussion-item');
  article.append(text('p', item.author_name + ' · ' + new Date(item.created_at || item.date).toLocaleDateString('ru-RU'), 'discussion-author'));
  if (kind === 'reviews') article.append(text('h3', item.title));
  const body = text('p', item.text, 'discussion-text');
  if (item.has_spoilers) { const details = document.createElement('details'); details.className = 'spoiler-block'; details.append(text('summary', 'Есть спойлеры · раскрыть текст'), body); article.append(details); }
  else article.append(body);
  const actions = text('div', '', 'discussion-actions'); article.append(actions);
  if (kind === 'comments') {
   const like = dsButton((item.liked_by_me ? '♥ ' : '♡ ') + item.likes_count, async () => {
    if (!dsUser) { dsShowAuth(); return; }
    const updated = await dsApi('comments/' + item.id + '/like', {method: item.liked_by_me ? 'DELETE' : 'PUT'});
    Object.assign(item, updated); dsRenderList(kind);
   }); like.setAttribute('aria-label', (item.liked_by_me ? 'Убрать лайк' : 'Поставить лайк') + ': ' + item.likes_count);
   like.setAttribute('aria-pressed', String(item.liked_by_me)); like.disabled = dsUser?.id === item.user_id; actions.append(like);
  }
  if (dsUser?.id === item.user_id) {
   actions.append(dsButton('Редактировать', () => { dsEditing[kind] = item; dsRenderForms(); $(kind + '-text').focus(); }));
   actions.append(dsButton('Удалить', async () => { if (!confirm('Удалить ' + (kind === 'comments' ? 'комментарий?' : 'рецензию?'))) return; await dsApi(kind + '/' + item.id, {method: 'DELETE'}); dsEditing[kind] = null; await dsReload(); }));
  }
  area.append(article);
 }
 $(kind + '-tab').querySelector('span').textContent = dsData[kind].total;
 $(kind + '-more').hidden = dsData[kind].items.length >= dsData[kind].total;
}
async function dsLoad(kind, append, version) {
 const anime = window.discussionAnime;
 const params = new URLSearchParams({anime_source: anime.source, anime_external_id: anime.id, limit: 20, offset: append ? dsData[kind].items.length : 0});
 const result = await dsApi(kind + '/?' + params);
 if (version !== dsVersion) return;
 dsData[kind] = {total: result.total, items: append ? [...dsData[kind].items, ...result.items] : result.items}; dsRenderList(kind);
}
async function dsReload() {
 const version = ++dsVersion; $('discussion-status').textContent = 'Загружаем обсуждение…';
 const results = await Promise.allSettled([dsLoad('comments', false, version), dsLoad('reviews', false, version), dsUser ? dsApi('comments/eligibility').then(data => { dsAccess = data; }) : Promise.resolve()]);
 if (version !== dsVersion) return;
 $('discussion-status').textContent = results.filter(result => result.status === 'rejected').map(result => result.reason.message).join('. ');
 dsRenderForms();
}
for (const kind of ['comments', 'reviews']) $(kind + '-more').addEventListener('click', async () => { $(kind + '-more').disabled = true; try { await dsLoad(kind, true, dsVersion); dsRenderForms(); } catch (error) { toast(error.message); } finally { $(kind + '-more').disabled = false; } });
window.addEventListener('anime-detail', dsReload);
if (window.discussionAnime) dsReload();
dsRestore();
