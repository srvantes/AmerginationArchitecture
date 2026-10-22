'use strict';
let peOwner = null, peBusy = false, pePreviewUrl = null;
function peClearPreview() { if (pePreviewUrl) URL.revokeObjectURL(pePreviewUrl); pePreviewUrl = null; }
function peClear() {
 peOwner = null; peClearPreview();
 $('profile-editor-form').reset(); $('profile-editor-status').textContent = '';
 $('profile-editor-preview').replaceChildren();
}
window.profileEditorAuthChanged = () => {
 if (peOwner && peOwner !== dsUser?.id) { $('profile-editor-dialog').close(); peClear(); }
};
$('profile-edit').addEventListener('click', () => {
 if (!dsUser) { $('auth-dialog').showModal(); return; }
 if (peBusy) return;
 peClear(); peOwner = dsUser.id;
 $('profile-edit-name').value = dsUser.profile?.nickname || '';
 $('profile-edit-bio').value = dsUser.profile?.bio || '';
 $('profile-edit-country').value = dsUser.profile?.country || '';
 $('profile-edit-name').placeholder = dsUser.username;
 accountAvatar($('profile-editor-preview'), dsUser);
 $('profile-editor-dialog').showModal(); $('profile-edit-name').focus();
});
$('profile-edit-avatar').addEventListener('change', () => {
 peClearPreview(); $('profile-editor-status').textContent = '';
 const file = $('profile-edit-avatar').files[0];
 if (!file) { accountAvatar($('profile-editor-preview'), dsUser); return; }
 if (!['image/jpeg','image/png','image/webp'].includes(file.type) || file.size > 2 * 1024 * 1024) {
  $('profile-editor-status').textContent = 'Выберите JPEG, PNG или WebP размером до 2 МБ.';
  $('profile-edit-avatar').value = ''; accountAvatar($('profile-editor-preview'), dsUser); return;
 }
 pePreviewUrl = URL.createObjectURL(file);
 const image = document.createElement('img'); image.src = pePreviewUrl; image.alt = 'Предпросмотр аватара';
 $('profile-editor-preview').replaceChildren(image);
});
$('profile-editor-dialog').addEventListener('close', () => { if (!peBusy) peClear(); });
$('profile-editor-form').addEventListener('submit', async event => {
 event.preventDefault();
 if (peBusy || !dsUser || peOwner !== dsUser.id) return;
 const owner = peOwner;
 const payload = {nickname:$('profile-edit-name').value.trim() || null, bio:$('profile-edit-bio').value.trim() || null, country:$('profile-edit-country').value.trim() || null};
 const file = $('profile-edit-avatar').files[0];
 peBusy = true; $('profile-editor-save').disabled = true;
 for (const id of ['profile-edit-name','profile-edit-bio','profile-edit-country','profile-edit-avatar']) $(id).disabled = true;
 $('profile-editor-status').textContent = 'Сохраняем…';
 let avatarSaved = false;
 try {
  if (file) {
   const profile = await dsApi('profile/avatar', {method:'POST', headers:{'Content-Type':file.type}, body:file});
   if (dsUser?.id !== owner) return;
   dsUser.profile = profile; $('profile-edit-avatar').value = ''; avatarSaved = true;
   accountRender();
  }
  const profile = await dsApi('profile/settings', {method:'PATCH', body:JSON.stringify(payload)});
  if (dsUser?.id !== owner) return;
  dsUser.profile = profile; accountRender(); $('profile-editor-dialog').close(); peClear(); toast('Профиль сохранён');
 } catch (error) {
  if (dsUser?.id === owner) $('profile-editor-status').textContent = (avatarSaved ? 'Аватар сохранён. Остальные изменения не сохранены: ' : '') + error.message;
 } finally {
  peBusy = false; $('profile-editor-save').disabled = false;
  for (const id of ['profile-edit-name','profile-edit-bio','profile-edit-country','profile-edit-avatar']) $(id).disabled = false;
  if (!$('profile-editor-dialog').open) peClear();
 }
});
