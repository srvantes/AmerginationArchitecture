'use strict';
let mpAnchor = null, mpVersion = 0, mpOpenTimer, mpCloseTimer, mpController, mpRestoringFocus = false;
const mpCard = $('mini-profile-card');
function mpClose(returnFocus = false) {
 clearTimeout(mpOpenTimer);clearTimeout(mpCloseTimer);++mpVersion;mpController?.abort();
 const previous=mpAnchor;mpAnchor=null;mpCard.hidden=true;
 previous?.setAttribute('aria-expanded','false');
 if(returnFocus && previous?.isConnected){mpRestoringFocus=true;try{previous.focus({preventScroll:true});}finally{mpRestoringFocus=false;}}
}
function mpPosition() {
 if(mpCard.hidden)return;
 if(!mpAnchor?.isConnected){mpClose();return;}
 const anchor=mpAnchor.getBoundingClientRect(),card=mpCard.getBoundingClientRect();
 if(anchor.bottom<0 || anchor.top>window.innerHeight){mpClose();return;}
 const left=Math.max(12,Math.min(anchor.left,window.innerWidth-card.width-12));
 let top=anchor.bottom+10;if(top+card.height>window.innerHeight-12)top=Math.max(12,anchor.top-card.height-10);
 top=Math.max(12,Math.min(top,window.innerHeight-card.height-12));
 mpCard.style.left=Math.round(left)+'px';mpCard.style.top=Math.round(top)+'px';
}
async function mpOpen(anchor, keyboard = false) {
 if(!anchor.isConnected)return;
 if(keyboard || document.activeElement===anchor)anchor.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});
 clearTimeout(mpOpenTimer);clearTimeout(mpCloseTimer);
 if(mpAnchor===anchor && !mpCard.hidden){mpPosition();if(keyboard)$('mini-profile-title').focus({preventScroll:true});return;}
 mpClose();mpAnchor=anchor;
 const version=++mpVersion,userId=anchor.dataset.miniUser;
 mpController=new AbortController();
 $('mini-profile-title').textContent=anchor.querySelector('.discussion-author-name')?.textContent || 'Мини-профиль';
 $('mini-profile-username').textContent='';$('mini-profile-bio').textContent='';$('mini-profile-country').textContent='';
 $('mini-profile-achievements').replaceChildren();$('mini-profile-avatar').replaceChildren();
 $('mini-profile-status').textContent='Загружаем профиль…';
 $('mini-profile-background').hidden=true;$('mini-profile-background').removeAttribute('src');
 $('mini-profile-title').href='/profile/'+encodeURIComponent(userId);
 anchor.setAttribute('aria-expanded','true');mpCard.hidden=false;mpPosition();
 if(keyboard)$('mini-profile-title').focus({preventScroll:true});
 try {
  const data=await dsApi('profile/'+encodeURIComponent(userId)+'/mini',{signal:mpController.signal});
  if(version!==mpVersion)return;
  const profile=data.profile;
  $('mini-profile-title').textContent=profile.nickname || profile.username;
  $('mini-profile-username').textContent='@'+profile.username;
  $('mini-profile-country').textContent=profile.country || '';
  $('mini-profile-bio').textContent=profile.bio || 'Описание пока не добавлено.';
  accountAvatar($('mini-profile-avatar'),{username:profile.username,profile});
  const background=safeUrl(profile.profile_background);
  if(background){$('mini-profile-background').src=background;$('mini-profile-background').hidden=false;}
  $('mini-profile-achievements').replaceChildren(...data.achievements.slice(0,4).map(item=>{
   const badge=text('span',item.title,'mini-profile-badge');badge.title=item.description;return badge;
  }));
  $('mini-profile-status').textContent=data.achievements.length ? '' : 'Витрина достижений пока пуста.';
  mpPosition();
 }catch(error){if(version===mpVersion){$('mini-profile-status').textContent=error.status===404 ? 'Пользователь не найден.' : 'Не удалось загрузить профиль. Попробуйте ещё раз.';mpPosition();}}
}
function mpScheduleClose() {
 clearTimeout(mpOpenTimer);clearTimeout(mpCloseTimer);
 mpCloseTimer=setTimeout(()=>{
  if(mpCard.contains(document.activeElement) || mpAnchor?.contains(document.activeElement))return;
  mpClose();
 },180);
}
document.addEventListener('pointerover',event=>{
 if(event.pointerType==='touch')return;
 const anchor=event.target.closest?.('[data-mini-user]');
 if(!anchor || anchor.contains(event.relatedTarget))return;
 clearTimeout(mpOpenTimer);clearTimeout(mpCloseTimer);mpOpenTimer=setTimeout(()=>mpOpen(anchor),220);
});
document.addEventListener('pointerout',event=>{
 const anchor=event.target.closest?.('[data-mini-user]');
 if(anchor && !anchor.contains(event.relatedTarget) && !mpCard.contains(event.relatedTarget))mpScheduleClose();
});
document.addEventListener('focusin',event=>{if(mpRestoringFocus)return;const anchor=event.target.closest?.('[data-mini-user]');if(anchor)mpOpen(anchor);});
document.addEventListener('focusout',event=>{
 if((mpCard.contains(event.target)||mpAnchor?.contains(event.target)) && !mpCard.contains(event.relatedTarget) && !mpAnchor?.contains(event.relatedTarget))mpScheduleClose();
});
document.addEventListener('click',event=>{
 const anchor=event.target.closest?.('[data-mini-user]');
 if(anchor && (event.pointerType==='touch'||matchMedia('(hover: none)').matches) && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey){event.preventDefault();mpOpen(anchor);return;}
 if(!mpCard.contains(event.target) && !mpAnchor?.contains(event.target))mpClose();
});
document.addEventListener('keydown',event=>{
 const anchor=event.target.closest?.('[data-mini-user]');
 if(anchor && event.key==='ArrowDown'){event.preventDefault();mpOpen(anchor,true);}
 else if(event.key==='Escape' && !mpCard.hidden){event.preventDefault();mpClose(true);}
});
mpCard.addEventListener('pointerenter',()=>{clearTimeout(mpOpenTimer);clearTimeout(mpCloseTimer);});
mpCard.addEventListener('pointerleave',event=>{if(!mpAnchor?.contains(event.relatedTarget))mpScheduleClose();});
document.addEventListener('scroll',event=>{if(!mpCard.contains(event.target))mpPosition();},true);
window.addEventListener('resize',mpPosition);
$('mini-profile-background').addEventListener('error',()=>{$('mini-profile-background').hidden=true;});
