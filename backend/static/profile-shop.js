'use strict';
const shopDialog = $('profile-shop');
const shopKind = $('profile-shop-kind');
const shopStatus = $('profile-shop-status');
let shopCatalog = null, shopVersion = 0, shopBusy = false, shopOwner = null;

function shopButton(label, action, disabled) {
 const button = text('button', label, 'secondary-button');
 button.type = 'button';
 button.disabled = disabled || shopBusy;
 button.addEventListener('click', action);
 return button;
}

function shopRender() {
 const kind = shopKind.value;
 const current = dsUser?.profile?.[kind];
 $('profile-shop-balance').textContent = shopCatalog?.balance ?? '—';
 const items = (shopCatalog?.items || []).filter(item => item.kind === kind);
 $('profile-shop-items').replaceChildren(...items.map(item => {
  const card = text('article', '', 'profile-shop-item');
  const preview = text('div', '', 'profile-shop-preview');
  if (item.asset_url) {
   const image = document.createElement('img'); image.alt = ''; image.src = profileMediaSource(item.asset_url);
   preview.append(image);
  } else preview.setAttribute('data-profile-theme', item.id);
  const selected = current === (item.asset_url || item.id);
  const label = selected ? 'Установлено' : item.owned ? 'Применить' : 'Купить за ' + item.price;
  card.append(preview, text('h3', item.name), shopButton(label,
   () => item.owned ? shopEquip(kind, item.id) : shopRun(async () => {
    await dsApi('profile/shop/' + encodeURIComponent(item.id) + '/buy', {method: 'POST'});
    return 'Предмет куплен';
   }, true), selected || (!item.owned && shopCatalog.balance < item.price)));
  return card;
 }));
 if (shopCatalog && !items.length) $('profile-shop-items').append(text('p', 'В этой категории пока нет предметов.', 'subtle'));
 $('profile-shop-upload').hidden = kind === 'profile_theme';
 $('profile-shop-upload').querySelector('button').disabled = shopBusy;
 $('profile-shop-reset').hidden = !current || current === '/static/default_background.jpg';
 $('profile-shop-reset').disabled = shopBusy;
}

async function shopRun(action, refresh = false) {
 if (shopBusy) return;
 const version = shopVersion;
 shopBusy = true;
 shopStatus.textContent = 'Подождите…';
 shopRender();
 try {
  const message = await action();
  if (version !== shopVersion) return;
  if (refresh) {
   const data = await dsApi('profile/shop');
   if (version !== shopVersion) return;
   shopCatalog = data;
  }
  shopStatus.textContent = message;
 } catch (error) { if (version === shopVersion) shopStatus.textContent = error.message; }
 finally { if (version === shopVersion) { shopBusy = false; shopRender(); } }
}

function shopUpdateProfile(profile, version) {
 if (version !== shopVersion || !dsUser) return;
 dsUser.profile = profile;
 profileRefresh();
}

function shopEquip(kind, itemId) {
 const version = shopVersion;
 return shopRun(async () => {
  const profile = await dsApi('profile/shop/equip', {method: 'PUT', body: JSON.stringify({kind, item_id: itemId})});
  shopUpdateProfile(profile, version);
  return 'Оформление обновлено';
 });
}

$('profile-shop-open').addEventListener('click', () => {
 shopOwner = dsUser.id;
 shopDialog.showModal();
 if (shopBusy) return;
 shopRun(async () => '', true);
});
shopDialog.addEventListener('close', () => {
 // Finish an in-flight write for this account even if its dialog was closed.
 $('profile-shop-file').value = '';
});
shopKind.addEventListener('change', () => { $('profile-shop-file').value = ''; shopRender(); });
$('profile-shop-reset').addEventListener('click', () => shopEquip(shopKind.value, null));
$('profile-shop-upload').addEventListener('submit', event => {
 event.preventDefault();
 const input = $('profile-shop-file');
 const image = input.files[0];
 if (!image) return;
 if (image.size > 2 * 1024 * 1024) { shopStatus.textContent = 'Размер фона не должен превышать 2 МБ.'; return; }
 const kind = shopKind.value;
 const version = shopVersion;
 shopRun(async () => {
  const profile = await dsApi('profile/background/' + kind, {method: 'PUT', headers: {'Content-Type': image.type}, body: image});
  shopUpdateProfile(profile, version);
  if (version === shopVersion) input.value = '';
  return 'Фон установлен';
 });
});
window.profileShopAuthChanged = () => {
 if (!shopOwner || dsUser?.id === shopOwner) return;
 ++shopVersion;
 shopOwner = null;
 shopCatalog = null;
 shopBusy = false;
 shopDialog.close();
};
