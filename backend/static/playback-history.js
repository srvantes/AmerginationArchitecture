'use strict';

// Last opened episode belongs to the account; it never changes watched counts.
let playbackHistoryIdentity = null, playbackHistoryEpoch = 0, playbackHistoryListVersion = 0;
let playbackHistoryWriteVersion = 0, playbackHistoryWrites = Promise.resolve(), playbackHistoryFailed = null;
const playbackHistoryPlayers = {aniboom:'Aniboom', kodik:'Kodik', cvh:'CVH', sibnet:'Sibnet'};

function playbackHistorySession() {
 return dsUser?.id && dsToken ? dsUser.id + ':' + dsToken : null;
}
function playbackHistoryCurrent(identity, epoch) {
 return !!identity && identity === playbackHistoryIdentity && identity === playbackHistorySession() && epoch === playbackHistoryEpoch;
}
function playbackHistoryPath(source, id) {
 return 'users/me/playback-history/' + encodeURIComponent(source) + '/' + encodeURIComponent(id);
}
function playbackHistoryCard(entry) {
 const link = text('a', '', 'anime-card history-card');
 link.href = animePath(entry)+'#player-section';
 link.setAttribute('aria-label', 'Продолжить ' + entry.anime_title + ', серия ' + entry.episode);
 const poster = text('div', '', 'poster');
 poster.append(text('span', 'Нет постера', 'poster-fallback'));
 poster.append(posterImage(entry.poster_url, entry.anime_title));
 poster.append(text('span', 'Серия ' + entry.episode, 'poster-label'));
 link.append(poster, text('h3', entry.anime_title), text('p', [playbackHistoryPlayers[entry.player],entry.translation_name].filter(Boolean).join(' · ')));
 return link;
}
async function playbackHistoryLoadList() {
 const identity = playbackHistoryIdentity, epoch = playbackHistoryEpoch, version = ++playbackHistoryListVersion;
 if (location.pathname !== '/' || !playbackHistoryCurrent(identity, epoch)) return;
 $('continue-history-status').textContent = '';
 $('retry-continue-history').hidden = true;
 try {
  const entries = await dsApi('users/me/playback-history?limit=12');
  if (!playbackHistoryCurrent(identity, epoch) || version !== playbackHistoryListVersion) return;
  if (!Array.isArray(entries)) throw Error('Не удалось загрузить историю.');
  const valid = entries.filter(entry => entry && ['shikimori','animego'].includes(entry.anime_source)
   && /^[1-9][0-9]{0,19}$/.test(entry.anime_external_id) && Number.isInteger(entry.episode) && entry.episode > 0);
  $('continue-track').replaceChildren(...valid.map(playbackHistoryCard));
  $('continue-section').hidden = !valid.length;
 } catch (error) {
  if (!playbackHistoryCurrent(identity, epoch) || version !== playbackHistoryListVersion) return;
  $('continue-track').replaceChildren(); $('continue-section').hidden = false;
  $('continue-history-status').textContent = 'Не удалось загрузить историю просмотра. Попробуйте ещё раз.';
  $('retry-continue-history').hidden = false;
 }
}
window.playbackHistoryAuthChanged = () => {
 const identity = playbackHistorySession();
 if (identity === playbackHistoryIdentity) return;
 playbackHistoryIdentity = identity; ++playbackHistoryEpoch; ++playbackHistoryListVersion; ++playbackHistoryWriteVersion;
 // A pending request from the previous login must not delay this account or
 // dispatch its queued choices under the new account's credentials.
 playbackHistoryWrites = Promise.resolve(); playbackHistoryFailed = null;
 $('continue-track').replaceChildren(); $('continue-section').hidden = true;
 $('continue-history-status').textContent = ''; $('retry-continue-history').hidden = true;
 $('playback-history-status').textContent = ''; $('retry-playback-history').hidden = true;
 if (identity) return playbackHistoryLoadList();
};
window.playbackHistoryGet = async (source, id) => {
 window.playbackHistoryAuthChanged();
 const identity = playbackHistoryIdentity, epoch = playbackHistoryEpoch;
 if (!playbackHistoryCurrent(identity, epoch)) return null;
 try {
  const entry = await dsApi(playbackHistoryPath(source, id));
  return playbackHistoryCurrent(identity, epoch) ? entry : null;
 } catch (error) { if (error.status === 404) return null; throw error; }
};
window.playbackHistorySave = (anime, choice) => {
 window.playbackHistoryAuthChanged();
 const identity = playbackHistoryIdentity, epoch = playbackHistoryEpoch;
 if (!playbackHistoryCurrent(identity, epoch)) return Promise.resolve(null);
 const version = ++playbackHistoryWriteVersion;
 const pending = {anime:{...anime},choice:{...choice}};
 playbackHistoryFailed = null;
 $('playback-history-status').textContent = ''; $('retry-playback-history').hidden = true;
 const payload = {anime_title:anime.title,poster_url:anime.poster_url || null,anime_slug:anime.slug || null,
  episode:Number(choice.episode),player:choice.player,translation_id:String(choice.translation_id),translation_name:choice.translation_name};
 const write = async () => {
  if (!playbackHistoryCurrent(identity, epoch)) return null;
  try {
   const entry = await dsApi(playbackHistoryPath(anime.source, anime.id), {method:'PUT',body:JSON.stringify(payload),keepalive:true});
   if (playbackHistoryCurrent(identity, epoch) && version === playbackHistoryWriteVersion) {
    playbackHistoryFailed = null; $('playback-history-status').textContent = ''; $('retry-playback-history').hidden = true;
   }
   return entry;
  } catch (error) {
   if (playbackHistoryCurrent(identity, epoch) && version === playbackHistoryWriteVersion) {
    playbackHistoryFailed = pending;
    $('playback-history-status').textContent = 'Не удалось сохранить выбранную серию в аккаунте.';
    $('retry-playback-history').hidden = false;
   }
   return null;
  }
 };
 // Serialize writes so a slow response for episode 1 cannot overwrite episode 2.
 playbackHistoryWrites = playbackHistoryWrites.catch(() => null).then(write);
 return playbackHistoryWrites;
};
$('retry-playback-history').addEventListener('click', () => {
 const pending = playbackHistoryFailed;
 if (pending) return window.playbackHistorySave(pending.anime,pending.choice);
});
$('retry-continue-history').addEventListener('click', playbackHistoryLoadList);
window.playbackHistoryAuthChanged();
window.playerHistoryAuthChanged?.();
