// Run the actual UI handlers with an isolated DOM and HTTP fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup({restoring = false, hasCookie = false, eligibilityFails = false} = {}) {
  const elements = new Map(), requests = [], storage = new Map();
  let verified = false;
  if (restoring) storage.set('amergination-token', 'pending-token');
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      hidden: false, open: false, value: '', textContent: '', disabled: false,
      events: {}, span: {textContent: ''},
      addEventListener(event, handler) { this.events[event] = handler; },
      querySelector() { return this.span; },
      showModal() { this.open = true; }, close() { this.open = false; },
    });
    return elements.get(id);
  }
  const context = vm.createContext({
    $: element, window: {addEventListener() {}}, URLSearchParams, Date,
    setInterval() { return 1; }, clearInterval() {}, toast() {},
    sessionStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)},
    fetch: async (url, options) => {
      requests.push({url, options});
      let status = 200, data;
      if (url.endsWith('/auth/register')) { status = 201; data = {id: 'pending-id', email_verified: false}; }
      else if (url.endsWith('/auth/login')) { hasCookie = true; status = 204; }
      else if (url.endsWith('/auth/me')) {
        if (hasCookie || options.headers.Authorization) data = {id: 'pending-id', username: 'newuser', email: 'newuser@example.com', email_verified: verified};
        else { status = 401; data = {detail: 'Sign in required'}; }
      }
      else if (url.endsWith('/auth/session')) status = 204;
      else if (url.endsWith('/auth/email/status')) data = {expires_in_seconds: 120, resend_after_seconds: 120, attempts_remaining: 5};
      else if (url.endsWith('/auth/email/verify')) { verified = true; data = {email_verified: true}; }
      else if (url.endsWith('/comments/eligibility')) {
        if (eligibilityFails) { status = 503; data = {detail: 'Eligibility temporarily unavailable'}; }
        else data = {can_write_reviews: false, likes_received: 0};
      } else throw new Error('Unexpected fixture request: ' + url);
      return {status, ok: status < 400, headers: {get() { return null; }}, json: async () => data};
    },
  });
  vm.runInContext(fs.readFileSync('backend/static/discussion.js', 'utf8'), context);
  return {element, context, requests};
}

async function main() {
  const registration = setup();
  vm.runInContext('dsRegister = true', registration.context);
  registration.element('auth-dialog').open = true;
  registration.element('auth-username').value = 'newuser';
  registration.element('auth-email').value = 'newuser@example.com';
  registration.element('auth-password').value = 'test-password-123';
  await registration.element('auth-form').events.submit({preventDefault() {}});
  assert.equal(registration.element('auth-dialog').open, true);
  assert.equal(registration.element('email-verification').hidden, false);
  assert.equal(registration.element('auth-form').hidden, true);
  assert.equal(registration.element('open-auth').span.textContent, 'Подтвердить почту');
  assert.equal(registration.element('verification-resend').disabled, true);
  registration.element('verification-code').value = '000123';
  await registration.element('verification-form').events.submit({preventDefault() {}});
  assert.equal(registration.element('auth-dialog').open, false);
  assert.equal(registration.element('open-auth').span.textContent, 'newuser');
  const verificationRequest = registration.requests.find(request => request.url.endsWith('/email/verify'));
  assert.equal(JSON.parse(verificationRequest.options.body).code, '000123');
  assert.equal(verificationRequest.options.headers.Authorization, undefined);
  assert.equal(verificationRequest.options.headers['X-Amergination-Account'], 'pending-id');

  const browserSession = setup({hasCookie: true});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(browserSession.element('email-verification').hidden, false);
  assert.ok(browserSession.requests.some(request => request.url.endsWith('/auth/session')));

  const restored = setup({restoring: true});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(restored.element('auth-dialog').open, true);
  assert.equal(restored.element('email-verification').hidden, false);

  const partialFailure = setup({restoring: true, eligibilityFails: true});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(partialFailure.element('auth-dialog').open, true);
  assert.equal(partialFailure.element('email-verification').hidden, false);

  // A late 401 from a previous session must not sign out the next account.
  const switched = setup(); let finishOldRequest;
  switched.context.fetch = () => new Promise(resolve => { finishOldRequest = resolve; });
  vm.runInContext('dsToken="old-token";dsUser={id:"old-user"};', switched.context);
  const oldRequest = vm.runInContext('dsApi("users/me/playback-history")', switched.context);
  vm.runInContext('dsToken="new-token";dsUser={id:"new-user"};', switched.context);
  finishOldRequest({status:401,ok:false,json:async()=>({detail:'Expired old session'}),headers:{get(){return null;}}});
  await assert.rejects(oldRequest,/Expired old session/);
  assert.equal(vm.runInContext('dsToken',switched.context),'new-token');
  assert.equal(vm.runInContext('dsUser.id',switched.context),'new-user');
  switched.context.fetch = async () => ({status:401,ok:false,json:async()=>({detail:'Expired current session'}),headers:{get(){return null;}}});
  await assert.rejects(vm.runInContext('dsApi("users/me/playback-history")',switched.context),/Expired current session/);
  assert.equal(vm.runInContext('dsToken',switched.context),null);
  console.log('Frontend auth: registration, confirmation, restored session and partial failure OK');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
