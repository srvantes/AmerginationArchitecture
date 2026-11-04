'use strict';
let achVersion = 0, achItems = [], achSelected = [], achTarget = null, achBusy = false;
const achSymbols = {email_verified:'@',first_anime:'I',ten_anime:'X',eleven_likes:'11',first_review:'✎'};
function achIcon(item) { const icon = text('span', achSymbols[item.code] || '◇', 'achievement-icon'); icon.setAttribute('aria-hidden','true'); return icon; }
function achRender() {
 const chosen = achItems.filter(item => item.awarded_at && item.showcase_slot).sort((a,b) => a.showcase_slot-b.showcase_slot);
 $('profile-achievement-count').textContent = achTarget?.owner ? achItems.filter(item=>item.awarded_at).length + ' / ' + achItems.length : '';
 $('profile-achievement-cards').replaceChildren(...chosen.map(item => {
  const card = text('article', '', 'achievement-card'), copy = text('div', '', 'achievement-copy');
  copy.append(text('h3',item.title),text('p',item.description,'subtle'));
  const date = text('time',new Date(item.awarded_at).toLocaleDateString('ru-RU'),'achievement-date'); date.dateTime=item.awarded_at;
  copy.append(date); card.append(achIcon(item),copy); return card;
 }));
 $('profile-achievement-status').textContent = chosen.length ? '' : achTarget?.owner ? 'Выберите полученные достижения для витрины.' : 'Пользователь пока не добавил достижения на витрину.';
}
async function achLoad(target) {
 const version=++achVersion; achTarget=target; achItems=[]; achSelected=[]; achBusy=false;
 $('achievement-dialog').close(); $('achievement-catalog').replaceChildren(); $('profile-achievement-cards').replaceChildren();
 $('profile-achievement-count').textContent=''; $('achievement-settings').hidden=!target?.owner; $('achievement-settings').disabled=true;
 if(!target) { $('profile-achievement-status').textContent=''; return; }
 $('profile-achievement-status').textContent='Загружаем достижения…';
 try {
  const items=await dsApi(target.owner ? 'profile/me/achievements' : 'profile/'+target.userId+'/achievements');
  if(version!==achVersion)return;
  achItems=items; achRender(); $('achievement-settings').disabled=false;
 } catch(error) { if(version===achVersion)$('profile-achievement-status').textContent=error.message; }
}
function achSelectionView() {
 $('achievement-selection-count').textContent='Выбрано: '+achSelected.length+' / 4';
 $('achievement-save').disabled=achBusy;
 for(const item of achItems) {
  const input=$('achievement-select-'+item.code); if(!input)continue;
  input.checked=achSelected.includes(item.code);
  input.disabled=achBusy || !item.awarded_at || (achSelected.length>=4 && !input.checked);
 }
}
$('achievement-settings').addEventListener('click',()=>{
 if(!achTarget?.owner)return;
 achSelected=achItems.filter(item=>item.awarded_at && item.showcase_slot).sort((a,b)=>a.showcase_slot-b.showcase_slot).map(item=>item.code);
 $('achievement-save-status').textContent='';
 $('achievement-catalog').replaceChildren(...achItems.map(item=>{
  const label=text('label','','achievement-option'+(item.awarded_at ? '' : ' achievement-locked'));
  const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.id='achievement-select-'+item.code;
  checkbox.setAttribute('aria-label',item.title);
  checkbox.addEventListener('change',()=>{
   if(checkbox.checked && achSelected.length<4)achSelected.push(item.code);
   else achSelected=achSelected.filter(code=>code!==item.code);
   achSelectionView();
  });
  const copy=text('div','','achievement-copy');copy.append(text('h3',item.title),text('p',item.description,'subtle'));
  if(item.awarded_at)copy.append(text('p','Получено '+new Date(item.awarded_at).toLocaleDateString('ru-RU'),'achievement-date'));
  else {
   copy.append(text('p',item.progress+' / '+item.target,'subtle'));
   const progress=document.createElement('progress');progress.max=item.target;progress.value=item.progress;progress.setAttribute('aria-label','Прогресс: '+item.title);copy.append(progress);
  }
  label.append(checkbox,achIcon(item),copy);return label;
 }));
 achSelectionView();$('achievement-dialog').showModal();
});
$('achievement-form').addEventListener('submit',async event=>{
 event.preventDefault();if(achBusy || !achTarget?.owner)return;
 const version=achVersion;achBusy=true;achSelectionView();$('achievement-save-status').textContent='Сохраняем…';
 try {
  const chosen=await dsApi('profile/me/achievements/showcase',{method:'PUT',body:JSON.stringify({codes:achSelected})});
  if(version!==achVersion)return;
  achItems=achItems.map(item=>({...item,showcase_slot:chosen.find(row=>row.code===item.code)?.showcase_slot || null}));
  achRender();$('achievement-dialog').close();toast('Витрина сохранена');
 }catch(error){if(version===achVersion)$('achievement-save-status').textContent=error.message;}
 finally{if(version===achVersion){achBusy=false;achSelectionView();}}
});
window.profileAchievementsChanged=achLoad;
achLoad(window.profileAchievementTarget || null);
