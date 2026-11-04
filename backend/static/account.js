'use strict';
let profileVersion = 0;
let profileViewVersion = 0;
async function profileLoadLibrary(targetId = null) {
 const version = ++profileVersion;
 $('profile-watching').replaceChildren();
 for (const id of ['profile-anime-count','profile-episode-count','profile-review-count']) $(id).textContent = '—';
 if (!dsUser && !targetId) return;
 $('profile-library-status').textContent = 'Загружаем список…';
 try {
  const data = await dsApi(targetId ? 'users/' + targetId + '/watchlist/summary' : 'users/me/watchlist/summary');
  if (version !== profileVersion) return;
  $('profile-anime-count').textContent = data.completed;
  $('profile-episode-count').textContent = data.episodes_watched;
  $('profile-review-count').textContent = data.reviews_written;
  $('profile-library-status').textContent = data.watching.length ? '' : 'Пока ничего не смотрите. Добавьте тайтл в список со статусом «Смотрю».';
  $('profile-watching').replaceChildren(...data.watching.map(entry => {
   const card = text('a', '', 'profile-watching-card');
   const path=animePath(entry);if(path)card.href=path;
   const mark = text('span', entry.anime_title.slice(0,1).toLocaleUpperCase('ru-RU'), 'profile-title-mark'); mark.setAttribute('aria-hidden','true');
   const copy = text('div', '', 'profile-watching-copy'); copy.append(text('h3', entry.anime_title), text('p', 'Просмотрено серий: ' + entry.episodes_watched, 'subtle'));
   card.append(mark, copy); return card;
  }));
 } catch (error) { if (version === profileVersion) $('profile-library-status').textContent = error.status === 403 ? 'Список аниме и статистика просмотра скрыты владельцем.' : error.message; }
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
 profileRefresh();
}
async function profileRefresh() {
 const version = ++profileViewVersion; ++profileVersion;
 window.profileAchievementTarget = null; window.profileAchievementsChanged?.(null);
 $('profile-watching').replaceChildren();
 for (const id of ['profile-anime-count','profile-episode-count','profile-review-count']) $(id).textContent = '—';
 $('profile-account-panel').hidden = true; $('profile-edit').hidden = true; $('profile-public-link').hidden = true;
 $('profile-email').textContent = ''; $('profile-verified').textContent = '';
 $('profile-content').hidden = true; $('profile-login').hidden = true;
 if (!profileUserId && !dsUser) {
  $('profile-login').hidden = false;
  $('profile-status').textContent = dsToken ? 'Проверяем вход…' : 'Войдите, чтобы открыть профиль.';
  return;
 }
 $('profile-status').textContent = 'Загружаем профиль…';
 let user;
 const owner = !!dsUser && (!profileUserId || dsUser.id === profileUserId);
 try {
  if (owner) user = dsUser;
  else { const data = await dsApi('profile/' + profileUserId); user = {id:data.id,username:data.username,profile:data}; }
 } catch (error) { if (version === profileViewVersion) $('profile-status').textContent = error.status === 404 ? 'Пользователь не найден.' : error.message; return; }
 if (version !== profileViewVersion) return;
 const profile = user.profile || {};
 window.profileAchievementTarget = {userId:user.id,owner};
 window.profileAchievementsChanged?.(window.profileAchievementTarget);
 $('profile-content').hidden = false; $('profile-status').textContent = '';
 $('profile-account-panel').hidden = !owner; $('profile-edit').hidden = !owner; $('profile-public-link').hidden = !owner;
 $('profile-public-link').href = '/profile/' + encodeURIComponent(user.id);
 const canViewList = owner || profile.show_watchlist;
 for (const id of ['profile-list-link','profile-all-list']) { $(id).hidden = !canViewList; $(id).href = owner ? '/my-list' : '/profile/' + encodeURIComponent(user.id) + '/list'; }
 accountAvatar($('profile-avatar'), user);
 $('profile-name').textContent = profile.nickname || user.username;
 $('profile-username').textContent = '@' + user.username;
 $('profile-email').textContent = owner ? user.email : '';
 $('profile-verified').textContent = owner ? (user.email_verified ? 'Почта подтверждена' : 'Почта не подтверждена') : '';
 $('profile-bio').textContent = profile.bio || 'Описание пока не добавлено.';
 $('profile-country').textContent = profile.country || ''; $('profile-country').hidden = !profile.country;
 const background = safeUrl(profile.profile_background);
 $('profile-background-image').hidden = true;
 $('profile-background-image').removeAttribute('src');
 if (background) { $('profile-background-image').src = background; $('profile-background-image').hidden = false; }
 const joined = new Date(profile.created_at);
 $('profile-joined').textContent = Number.isNaN(joined.getTime()) ? '' : 'На сайте с ' + joined.toLocaleDateString('ru-RU', {month:'long',year:'numeric'});
 if (canViewList) profileLoadLibrary(owner ? null : user.id);
 else $('profile-library-status').textContent = 'Список аниме и статистика просмотра скрыты владельцем.';
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
