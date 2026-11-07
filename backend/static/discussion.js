'use strict';
let dsToken = sessionStorage.getItem('amergination-token'), dsUser = null, dsRegister = false;
let dsAccess = null, dsVersion = 0, dsEditing = {comments: null, reviews: null};
let dsData = {comments: {items: [], total: 0}, reviews: {items: [], total: 0}};
let dsCodeDeadline = 0, dsResendDeadline = 0, dsCodeTimer, dsVerifyBusy = false, dsCodeAttempts = 5;
let dsDrafts = {comments: null, reviews: null};
let dsSessionVersion = 0, dsHeartbeatTimer, dsHeartbeatRequest, dsRestoreRequest;
let dsReply = null;
const dsThreads = new Map();
const dsWords = value => (value.match(/\S+/gu) || []).filter(word => /[\p{L}\p{N}]/u.test(word)).length;

async function dsApi(path, options = {}) {
 const requestToken = dsToken;
 const headers = {'Content-Type': 'application/json', ...options.headers};
 if (requestToken?.startsWith('cookie:') || path === 'auth/me' || path === 'auth/login') headers['X-Amergination-Client'] = 'web';
 if (requestToken && !requestToken.startsWith('cookie:')) headers.Authorization = 'Bearer ' + requestToken;
 else if (dsUser) headers['X-Amergination-Account'] = dsUser.id;
 const response = await fetch('/api/v1/' + path, {...options, headers});
 if (response.status === 204) return null;
 const data = await response.json();
 if (!response.ok) {
  if (response.status === 401 && requestToken && requestToken === dsToken) {
   dsClearSession();
   dsAuthView();
   if (window.discussionAnime) dsReload();
  }
  const error = Error(typeof data.detail === 'string' ? data.detail : data.detail?.[0]?.msg?.replace(/^Value error, /, '') || 'Не удалось выполнить действие. Попробуйте ещё раз.');
  error.status = response.status; error.retryAfter = Number(response.headers.get('Retry-After')) || 0; throw error;
 }
 return data;
}
function dsClearSession() {
 dsToken = null;
 dsUser = null;
 dsAccess = null;
 dsReply = null;
 dsThreads.clear();
 dsDrafts = {comments: null, reviews: null};
 dsEditing = {comments: null, reviews: null};
 dsSessionVersion++;
 clearInterval(dsHeartbeatTimer);
 sessionStorage.removeItem('amergination-token');
}
async function dsKeepSessionAlive() {
 if (!dsToken?.startsWith('cookie:') || !dsUser || dsHeartbeatRequest === dsToken) return;
 const token = dsToken;
 dsHeartbeatRequest = token;
 try { await dsApi('auth/session', {method: 'POST'}); }
 catch { /* A network failure can be retried on the next tick or focus. */ }
 finally { if (dsHeartbeatRequest === token) dsHeartbeatRequest = null; }
}
function dsAuthView() {
 window.watchlistAuthChanged?.();
 window.playbackHistoryAuthChanged?.();
 window.playerHistoryAuthChanged?.();
 $('open-auth').querySelector('.account-name').textContent = dsUser ? (dsUser.email_verified ? dsUser.username : 'Подтвердить почту') : 'Войти';
 const resetting = !!window.passwordResetActive;
 $('auth-form').hidden = !!dsUser || resetting; $('auth-switch').hidden = !!dsUser || resetting; $('auth-logout').hidden = !dsUser || resetting;
 $('auth-forgot').hidden = !!dsUser || resetting;
 $('email-verification').hidden = !dsUser || dsUser.email_verified || resetting;
 $('verification-email').textContent = dsUser?.email || '';
 if (dsUser && !dsUser.email_verified && !$('auth-dialog').open) $('auth-dialog').showModal();
 if (!dsUser || dsUser.email_verified) clearInterval(dsCodeTimer);
 $('auth-status').textContent = dsUser ? (dsUser.email_verified ? 'Вы вошли как ' + dsUser.username : 'До подтверждения почты комментарии, лайки и рецензии недоступны.') : '';
 window.accountAuthChanged?.();
}
async function dsRestore() {
 const version = dsSessionVersion;
 if (dsRestoreRequest === version) return;
 dsRestoreRequest = version;
 try {
  const user = await dsApi('auth/me');
  if (version !== dsSessionVersion) return;
  dsToken ||= 'cookie:' + version;
  dsUser = user;
  dsAuthView();
  clearInterval(dsHeartbeatTimer);
  if (dsToken.startsWith('cookie:')) {
   dsKeepSessionAlive();
   dsHeartbeatTimer = setInterval(dsKeepSessionAlive, 60000);
  }
  if (!dsUser.email_verified) await dsVerificationStatus();
  if (version !== dsSessionVersion) return;
  const access = await dsApi('comments/eligibility');
  if (version !== dsSessionVersion) return;
  dsAccess = access;
  if (window.discussionAnime) await dsReload();
 }
 catch (error) { if (error.status !== 401 && version === dsSessionVersion) $('auth-status').textContent = error.message; }
 finally { if (dsRestoreRequest === version) dsRestoreRequest = null; }
}
window.addEventListener('focus', () => dsToken ? dsKeepSessionAlive() : dsRestore());
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
  await dsApi('auth/login', {method: 'POST', body: JSON.stringify(credentials)});
  dsClearSession();
  dsToken = 'cookie:' + dsSessionVersion;
  $('auth-password').value = ''; await dsRestore(); if (dsUser?.email_verified) $('auth-dialog').close();
 } catch (error) { $('auth-status').textContent = error.message; }
 finally { $('auth-submit').disabled = false; }
});
async function dsLogout() {
 try { await dsApi('auth/logout', {method: 'POST'}); dsClearSession(); dsAuthView(); $('auth-dialog').close(); if (window.discussionAnime) await dsReload(); return true; }
 catch (error) { $('auth-status').textContent = error.message; toast(error.message); return false; }
}
$('auth-logout').addEventListener('click', dsLogout);
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
  if (!dsUser.email_verified) { area.append(text('p', 'Подтвердите почту, чтобы участвовать в обсуждении.', 'subtle'), dsButton('Подтвердить почту', dsShowAuth)); continue; }
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
  else { spoiler = document.createElement('input'); spoiler.type = 'checkbox'; spoiler.checked = editing?.has_spoilers || false; const label = text('label', '', 'spoiler-checkbox'); label.append(text('span', 'Есть спойлеры — скрыть текст до раскрытия'), spoiler); form.append(label); }
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
async function dsLoadReplies(item, append = false) {
 const version = dsVersion;
 const previous = dsThreads.get(item.id);
 const offset = append ? previous.items.length : 0;
 const data = await dsApi('comments/' + item.id + '/replies?offset=' + offset);
 if (version !== dsVersion) return;
 item.reply_count = data.total;
 dsThreads.set(item.id, {open: true, items: append ? [...previous.items, ...data.items] : data.items});
 dsRenderList('comments');
}
function dsReplyForm(item) {
 const draft = dsReply;
 const form = text('form', '', 'discussion-form discussion-reply-form');
 const body = document.createElement('textarea');
 body.id = 'reply-text';
 body.rows = 3;
 body.required = true;
 body.maxLength = 20000;
 body.value = draft.text;
 dsField(form, 'Ответ пользователю ' + item.author_name, body);
 const counter = text('p', dsWords(body.value) + ' / 250 слов', 'subtle');
 body.addEventListener('input', () => {
  draft.text = body.value;
  counter.textContent = dsWords(body.value) + ' / 250 слов';
 });
 const spoiler = document.createElement('input');
 spoiler.type = 'checkbox';
 spoiler.checked = draft.hasSpoilers;
 spoiler.addEventListener('change', () => { draft.hasSpoilers = spoiler.checked; });
 const label = text('label', '', 'spoiler-checkbox');
 label.append(text('span', 'Есть спойлеры'), spoiler);
 const submit = text('button', 'Опубликовать ответ', 'gold-button');
 submit.type = 'submit';
 const status = text('p', '', 'subtle');
 status.setAttribute('role', 'status');
 form.append(counter, label, submit, dsButton('Отменить', () => { dsReply = null; dsRenderList('comments'); }), status);
 form.addEventListener('submit', async event => {
  event.preventDefault();
  if (draft.busy) return;
  const words = dsWords(draft.text);
  if (words < 1 || words > 250) { status.textContent = 'Нужно от 1 до 250 слов.'; return; }
  const version = dsVersion;
  draft.busy = submit.disabled = true;
  try {
   const reply = await dsApi('comments/', {method: 'POST', body: JSON.stringify({
    anime_source: item.anime_source, anime_external_id: item.anime_external_id,
    parent_id: item.id, text: draft.text, has_spoilers: draft.hasSpoilers,
   })});
   if (version !== dsVersion) return;
   if (dsReply === draft) dsReply = null;
   const thread = dsThreads.get(item.id);
   item.reply_count = (item.reply_count || 0) + 1;
   dsThreads.set(item.id, {open: true, items: [reply, ...(thread?.items || [])]});
   dsRenderList('comments');
   toast('Ответ опубликован');
  } catch (error) { status.textContent = error.message; }
  finally { draft.busy = submit.disabled = false; }
 });
 submit.disabled = !!draft.busy;
 return form;
}
function dsReactionButton(kind, item, reaction) {
 const isLike = reaction === 'like';
 const active = isLike ? item.liked_by_me : item.disliked_by_me;
 const count = (isLike ? item.likes_count : item.dislikes_count) || 0;
 const name = isLike ? 'лайк' : 'дизлайк';
 const button = dsButton((isLike ? (active ? '♥ ' : '♡ ') : '👎 ') + count, async () => {
  if (!dsUser || !dsUser.email_verified) { dsShowAuth(); return; }
  if (item.voting) return;
  const version = dsVersion;
  item.voting = true;
  try {
   const updated = await dsApi(kind + '/' + item.id + '/' + reaction, {method: active ? 'DELETE' : 'PUT'});
   if (version !== dsVersion) return;
   Object.assign(item, updated);
   dsRenderList(kind);
  } finally { item.voting = false; }
 });
 button.setAttribute('aria-label', (active ? 'Убрать ' : 'Поставить ') + name + ' · ' + count);
 button.setAttribute('aria-pressed', String(!!active));
 button.disabled = dsUser?.id === item.user_id;
 return button;
}
function dsRenderItem(kind, item) {
  const article = text('article', '', 'discussion-item');
  const authorLine = text('p', '', 'discussion-author');
  const author = text('a', '', 'discussion-profile-link'); author.href = '/profile/' + encodeURIComponent(item.user_id);
  author.dataset.miniUser = item.user_id;
  const authorAvatar = text('span', item.author_name.slice(0,1).toLocaleUpperCase('ru-RU'), 'discussion-avatar'); authorAvatar.setAttribute('aria-hidden','true');
  author.append(authorAvatar,text('span',item.author_name,'discussion-author-name'));
  author.setAttribute('aria-haspopup','dialog'); author.setAttribute('aria-controls','mini-profile-card'); author.setAttribute('aria-expanded','false');
  authorLine.append(author, text('span', ' · ' + new Date(item.created_at || item.date).toLocaleDateString('ru-RU')));
  article.append(authorLine);
  if (kind === 'reviews') article.append(text('h3', item.title));
  const body = text('p', item.text, 'discussion-text');
  if (item.has_spoilers) { const details = document.createElement('details'); details.className = 'spoiler-block'; details.append(text('summary', 'Есть спойлеры · раскрыть текст'), body); article.append(details); }
  else article.append(body);
  const actions = text('div', '', 'discussion-actions'); article.append(actions);
  actions.append(dsReactionButton(kind, item, 'like'), dsReactionButton(kind, item, 'dislike'));
  if (kind === 'comments') {
   actions.append(dsButton('Ответить', () => {
    if (!dsUser?.email_verified) { dsShowAuth(); return; }
    if (dsReply?.parentId !== item.id) dsReply = {parentId: item.id, text: '', hasSpoilers: false};
    dsRenderList('comments');
    $('reply-text').focus();
   }));
   const thread = dsThreads.get(item.id);
   if (item.reply_count) actions.append(dsButton(thread?.open ? 'Скрыть ответы' : 'Ответы · ' + item.reply_count, async () => {
    if (thread) { thread.open = !thread.open; dsRenderList('comments'); }
    else await dsLoadReplies(item);
   }));
   if (dsReply?.parentId === item.id) article.append(dsReplyForm(item));
   if (thread?.open) {
    const replies = text('div', '', 'discussion-replies');
    for (const reply of thread.items) replies.append(dsRenderItem(kind, reply));
    if (thread.items.length < item.reply_count) replies.append(dsButton('Ещё ответы', () => dsLoadReplies(item, true)));
    article.append(replies);
   }
  }
  if (dsUser?.id === item.user_id) {
   actions.append(dsButton('Редактировать', () => { dsEditing[kind] = item; dsRenderForms(); $(kind + '-text').focus(); }));
   actions.append(dsButton('Удалить', async () => { if (!confirm('Удалить ' + (kind === 'comments' ? 'комментарий?' : 'рецензию?'))) return; await dsApi(kind + '/' + item.id, {method: 'DELETE'}); dsEditing[kind] = null; await dsReload(); }));
  }
  return article;
}
function dsRenderList(kind) {
 const area = $(kind + '-list'); area.replaceChildren();
 if (!dsData[kind].items.length) area.append(text('p', kind === 'comments' ? 'Комментариев пока нет.' : 'Рецензий пока нет.', 'subtle'));
 for (const item of dsData[kind].items) area.append(dsRenderItem(kind, item));
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
 dsThreads.clear();
 dsReply = null;
 const results = await Promise.allSettled([dsLoad('comments', false, version), dsLoad('reviews', false, version), dsUser ? dsApi('comments/eligibility').then(data => { if (version === dsVersion) dsAccess = data; }) : Promise.resolve()]);
 if (version !== dsVersion) return;
 $('discussion-status').textContent = results.filter(result => result.status === 'rejected').map(result => result.reason.message).join('. ');
 dsRenderForms();
}
for (const kind of ['comments', 'reviews']) $(kind + '-more').addEventListener('click', async () => { $(kind + '-more').disabled = true; try { await dsLoad(kind, true, dsVersion); dsRenderForms(); } catch (error) { toast(error.message); } finally { $(kind + '-more').disabled = false; } });
window.addEventListener('anime-detail', dsReload);
if (window.discussionAnime) dsReload();
dsRestore();


function dsVerificationClock() {
 const expires = Math.max(0, Math.ceil((dsCodeDeadline - Date.now()) / 1000));
 const resend = Math.max(0, Math.ceil((dsResendDeadline - Date.now()) / 1000));
 $('verification-timer').textContent = expires ? `Код действует ещё ${expires} сек. Осталось попыток: ${dsCodeAttempts}.` : 'Код истёк или не отправлен. Запросите новый код.';
 $('verification-resend').textContent = resend ? `Новый код через ${resend} сек.` : 'Отправить новый код';
 $('verification-resend').disabled = dsVerifyBusy || resend > 0;
 $('verification-submit').disabled = dsVerifyBusy || expires === 0 || dsCodeAttempts === 0;
}
function dsSetVerificationTime(data) {
 dsCodeDeadline = Date.now() + data.expires_in_seconds * 1000;
 dsResendDeadline = Date.now() + data.resend_after_seconds * 1000;
 dsCodeAttempts = data.attempts_remaining ?? 5;
 clearInterval(dsCodeTimer); dsCodeTimer = setInterval(dsVerificationClock, 1000); dsVerificationClock();
}
async function dsVerificationStatus() { dsSetVerificationTime(await dsApi('auth/email/status')); }
$('verification-form').addEventListener('submit', async event => {
 event.preventDefault(); dsVerifyBusy = true; dsVerificationClock(); $('auth-status').textContent = 'Проверяем код…';
 try { await dsApi('auth/email/verify', {method: 'POST', body: JSON.stringify({code: $('verification-code').value})}); $('verification-code').value = ''; await dsRestore(); $('auth-dialog').close(); toast('Почта подтверждена'); }
 catch (error) { $('auth-status').textContent = error.message; try { await dsVerificationStatus(); } catch {} }
 finally { dsVerifyBusy = false; dsVerificationClock(); }
});
$('verification-resend').addEventListener('click', async () => {
 dsVerifyBusy = true; dsVerificationClock(); $('auth-status').textContent = 'Отправляем письмо…';
 try { const data = await dsApi('auth/email/resend', {method: 'POST'}); $('verification-code').value = ''; dsSetVerificationTime(data); $('auth-status').textContent = 'Новый код отправлен. Проверьте также папку «Спам».'; }
 catch (error) { if (error.retryAfter) dsResendDeadline = Date.now() + error.retryAfter * 1000; $('auth-status').textContent = error.message; }
 finally { dsVerifyBusy = false; dsVerificationClock(); }
});
