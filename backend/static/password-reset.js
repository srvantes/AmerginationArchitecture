'use strict';
let prEmail = '', prToken = '', prExpires = 0, prResendAt = 0, prTimer, prBusy = false, prStage = 'request', prAttempts = 0, prVersion = 0;

function prClock() {
 const remaining = Math.max(0, Math.ceil((prExpires - Date.now()) / 1000));
 const resend = Math.max(0, Math.ceil((prResendAt - Date.now()) / 1000));
 $('reset-timer').textContent = prStage === 'request' ? '' : remaining ? (prStage === 'code' ? `Код действует ещё ${remaining} сек. Осталось попыток: ${Math.max(0, 5-prAttempts)}.` : `На смену пароля осталось ${remaining} сек.`) : 'Время истекло. Запросите новый код.';
 $('reset-resend').hidden = prStage === 'request' || (prStage === 'password' && remaining > 0);
 $('reset-resend').textContent = resend ? `Новый код через ${resend} сек.` : 'Отправить новый код';
 $('reset-resend').disabled = prBusy || resend > 0;
 $('reset-code-submit').disabled = prBusy || remaining === 0 || prAttempts >= 5;
 $('reset-password-submit').disabled = prBusy || remaining === 0;
 $('reset-request-submit').disabled = prBusy;
}
function prView(stage) {
 prStage = stage;
 for (const [name, id] of [['request','reset-request-form'],['code','reset-code-form'],['password','reset-password-form']]) $(id).hidden = name !== stage;
 $('reset-resend').hidden = stage !== 'code'; prClock();
}
function prReturn() {
 ++prVersion; prBusy = false;
 window.passwordResetActive = false; prToken = ''; clearInterval(prTimer); prStage = 'request';
 $('password-reset-panel').hidden = true; $('reset-password').value = ''; $('reset-password-repeat').value = ''; $('reset-code').value = '';
 dsAuthView();
}
$('auth-forgot').addEventListener('click', () => {
 ++prVersion; prBusy = false;
 window.passwordResetActive = true; prToken = ''; prEmail = ''; prExpires = 0; prResendAt = 0;
 dsAuthView(); $('password-reset-panel').hidden = false; $('auth-status').textContent = '';
 prView('request'); $('reset-email').focus();
 clearInterval(prTimer); prTimer = setInterval(prClock, 1000);
});
$('reset-back').addEventListener('click', prReturn);

async function prSend() {
 const version = ++prVersion;
 prBusy = true; prClock(); $('auth-status').textContent = 'Подождите…';
 try {
  const data = await dsApi('auth/password/request', {method:'POST', body:JSON.stringify({email:prEmail})});
  if (version !== prVersion) return;
  prToken = ''; prAttempts = 0; $('reset-code').value = ''; prExpires = Date.now() + data.expires_in_seconds * 1000; prResendAt = Date.now() + data.resend_after_seconds * 1000;
  prView('code'); $('auth-status').textContent = data.detail; $('reset-code').focus();
 } catch (error) {
  if (version !== prVersion) return;
  if (error.retryAfter) { prResendAt = Date.now() + error.retryAfter * 1000; if (prStage === 'request') prView('code'); }
  $('auth-status').textContent = error.message;
 } finally { if (version === prVersion) { prBusy = false; prClock(); } }
}
$('reset-request-form').addEventListener('submit', async event => { event.preventDefault(); prEmail = $('reset-email').value.trim(); await prSend(); });
$('reset-resend').addEventListener('click', prSend);
$('reset-code-form').addEventListener('submit', async event => {
 const version = ++prVersion;
 event.preventDefault(); prBusy = true; prClock(); $('auth-status').textContent = 'Проверяем код…';
 try {
  const data = await dsApi('auth/password/verify', {method:'POST', body:JSON.stringify({email:prEmail, code:$('reset-code').value})});
  if (version !== prVersion) return;
  prToken = data.reset_token; $('reset-code').value = ''; prExpires = Date.now() + data.expires_in_seconds * 1000;
  prView('password'); $('auth-status').textContent = 'Введите новый пароль — от 8 до 128 символов.'; $('reset-password').focus();
 } catch (error) { if (version === prVersion) { if (error.status === 400) prAttempts++; $('auth-status').textContent = error.message; } }
 finally { if (version === prVersion) { prBusy = false; prClock(); } }
});
$('reset-password-form').addEventListener('submit', async event => {
 event.preventDefault();
 if ($('reset-password').value !== $('reset-password-repeat').value) { $('auth-status').textContent = 'Пароли не совпадают.'; return; }
 const version = ++prVersion;
 prBusy = true; prClock(); $('auth-status').textContent = 'Сохраняем пароль…';
 try {
  const data = await dsApi('auth/password/reset', {method:'POST', body:JSON.stringify({reset_token:prToken, new_password:$('reset-password').value})});
  if (version !== prVersion) return;
  dsToken = null; dsUser = null; dsAccess = null; dsDrafts = {comments:null,reviews:null}; dsEditing = {comments:null,reviews:null};
  sessionStorage.removeItem('amergination-token'); $('auth-password').value = ''; $('auth-username').value = '';
  dsRegister = false; $('auth-email-label').hidden = true; $('auth-email').required = false; $('auth-password').autocomplete = 'current-password';
  $('auth-submit').textContent = 'Войти'; $('auth-switch').textContent = 'Создать аккаунт';
  prReturn(); dsRenderForms(); $('auth-status').textContent = '';
  $('auth-dialog').close(); toast(data.detail);
 } catch (error) { if (version === prVersion) $('auth-status').textContent = error.message; }
 finally { if (version === prVersion) { prBusy = false; prClock(); } }
});
