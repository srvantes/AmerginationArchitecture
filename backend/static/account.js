'use strict';
let profileVersion = 0;
async function profileLoadLibrary() {
 const version = ++profileVersion;
 $('profile-watching').replaceChildren();
 for (const id of ['profile-anime-count','profile-episode-count','profile-review-count']) $(id).textContent = '—';
 if (!dsUser) return;
 $('profile-library-status').textContent = 'Загружаем список…';
 try {
  const data = await dsApi('users/me/watchlist/summary');
  if (version !== profileVersion) return;
  $('profile-anime-count').textContent = data.completed;
  $('profile-episode-count').textContent = data.episodes_watched;
  $('profile-review-count').textContent = data.reviews_written;
  $('profile-library-status').textContent = data.watching.length ? '' : 'Пока ничего не смотрите. Добавьте тайтл в список со статусом «Смотрю».';
  $('profile-watching').replaceChildren(...data.watching.map(entry => {
   const card = text('a', '', 'profile-watching-card');
   if (['shikimori','animego'].includes(entry.anime_source)) card.href = '/anime/' + entry.anime_source + '/' + encodeURIComponent(entry.anime_external_id);
   const mark = text('span', entry.anime_title.slice(0,1).toLocaleUpperCase('ru-RU'), 'profile-title-mark'); mark.setAttribute('aria-hidden','true');
   const copy = text('div', '', 'profile-watching-copy'); copy.append(text('h3', entry.anime_title), text('p', 'Просмотрено серий: ' + entry.episodes_watched, 'subtle'));
   card.append(mark, copy); return card;
  }));
 } catch (error) { if (version === profileVersion) $('profile-library-status').textContent = error.message; }
}
function accountClose(focus = false) {
 $('account-menu').hidden = true; $('open-auth').setAttribute('aria-expanded', 'false');
 if (focus) $('open-auth').focus();
}
function accountAvatar(target, user) {
 target.replaceChildren();
 const fallback = text('span', user ? user.username.slice(0, 1).toLocaleUpperCase('ru-RU') : '');
 if (!user) {
  const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  icon.setAttribute('viewBox', '0 0 24 24');
  const circle = document.createElementNS(icon.namespaceURI, 'circle'); circle.setAttribute('cx','12'); circle.setAttribute('cy','8'); circle.setAttribute('r','3.5');
  const path = document.createElementNS(icon.namespaceURI, 'path'); path.setAttribute('d','M5 21v-2a7 7 0 0 1 14 0v2');
  icon.append(circle,path); fallback.append(icon);
 }
 target.append(fallback);
 const avatar = user?.profile?.avatar_url;
 const url = typeof avatar === 'string' && /^\/media\/avatars\/[a-z0-9-]+\.png$/.test(avatar) ? avatar : safeUrl(avatar);
 if (url) {
  const image = document.createElement('img'); image.alt = ''; image.src = url; image.referrerPolicy = 'no-referrer';
  image.addEventListener('error', () => image.remove()); target.append(image);
 }
}
function accountRender() {
 window.profileEditorAuthChanged?.();
 accountClose();
 $('open-auth').querySelector('.account-name').textContent = dsUser?.username || 'Войти';
 $('open-auth').setAttribute('aria-label', dsUser ? 'Меню пользователя ' + dsUser.username : 'Войти');
 $('account-verify').hidden = !dsUser || dsUser.email_verified;
 accountAvatar($('account-avatar'), dsUser);
 if (!profilePage) return;
 profileLoadLibrary();
 $('profile-content').hidden = !dsUser; $('profile-login').hidden = !!dsUser;
 $('profile-status').textContent = dsUser ? '' : dsToken ? 'Проверяем вход…' : 'Войдите, чтобы открыть профиль.';
 if (!dsUser) { $('profile-name').textContent = ''; $('profile-email').textContent = ''; return; }
 const profile = dsUser.profile || {};
 accountAvatar($('profile-avatar'), dsUser);
 $('profile-name').textContent = profile.nickname || dsUser.username;
 $('profile-username').textContent = '@' + dsUser.username;
 $('profile-email').textContent = dsUser.email;
 $('profile-verified').textContent = dsUser.email_verified ? 'Почта подтверждена' : 'Почта не подтверждена';
 $('profile-bio').textContent = profile.bio || 'Описание пока не добавлено.';
 $('profile-country').textContent = profile.country || ''; $('profile-country').hidden = !profile.country;
 const background = safeUrl(profile.profile_background);
 $('profile-background-image').hidden = true;
 $('profile-background-image').removeAttribute('src');
 if (background) { $('profile-background-image').src = background; $('profile-background-image').hidden = false; }
 const joined = new Date(profile.created_at);
 $('profile-joined').textContent = Number.isNaN(joined.getTime()) ? '' : 'На сайте с ' + joined.toLocaleDateString('ru-RU', {month:'long',year:'numeric'});
}
window.openAccount = () => {
 if (!dsUser) { accountClose(); $('auth-dialog').showModal(); return; }
 const opening = $('account-menu').hidden;
 $('account-menu').hidden = !opening; $('open-auth').setAttribute('aria-expanded', String(opening));
};
window.accountAuthChanged = accountRender;
document.addEventListener('click', event => { if (!$('account-control').contains(event.target)) accountClose(); });
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !$('account-menu').hidden) { event.preventDefault(); accountClose(true); } });
$('account-control').addEventListener('focusout', event => { if (!$('account-control').contains(event.relatedTarget)) accountClose(); });
$('account-verify').addEventListener('click', () => { accountClose(); $('auth-dialog').showModal(); });
$('account-logout').addEventListener('click', async () => {
 $('account-logout').disabled = true;
 try { if (await dsLogout()) { accountClose(true); toast('Вы вышли из аккаунта'); } }
 finally { $('account-logout').disabled = false; }
});
$('profile-login').addEventListener('click', () => $('auth-dialog').showModal());
$('profile-background-image').addEventListener('error', () => { $('profile-background-image').hidden = true; });
accountRender();
