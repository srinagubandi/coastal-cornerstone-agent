'use strict';
let csrf = '';
const status = document.getElementById('status');
const button = document.getElementById('submit');
button.disabled = true;
async function prepare() {
  try {
    const response = await fetch('/private/api/dashboard/login-state', {credentials: 'same-origin', cache: 'no-store'});
    if (!response.ok) throw new Error('Sign in is unavailable. Contact the administrator.');
    csrf = (await response.json()).csrf;
    status.textContent = 'Your connection is ready for secure sign in.';
    button.disabled = false;
  } catch (error) { status.textContent = error.message; }
}
document.getElementById('loginform').addEventListener('submit', async (event) => {
  event.preventDefault();
  button.disabled = true;
  status.textContent = 'Checking credentials…';
  const password = document.getElementById('password');
  try {
    const response = await fetch('/private/api/dashboard/login', {method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
      body: JSON.stringify({email: document.getElementById('email').value, password: password.value})});
    password.value = '';
    if (response.ok) { location.replace('/dashboard/' + (/^#chat=[0-9a-f]{32}$/.test(location.hash) ? location.hash : '')); return; }
    if (response.status === 429) throw new Error('Too many sign-in attempts. Please wait and try again.');
    if (response.status === 403) { await prepare(); throw new Error('Sign-in session expired. Please try again.'); }
    throw new Error('Sign in failed. Check your credentials.');
  } catch (error) { password.value = ''; status.textContent = error.message; button.disabled = false; }
});
prepare();
