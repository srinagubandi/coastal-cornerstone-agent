

const notificationSettingsEl = $('notification-settings');
const notificationStatusEl = $('notification-status');
const notificationDeliveriesEl = $('notification-deliveries');
function notificationMessage(value) { if (notificationStatusEl) notificationStatusEl.textContent = String(value); }
function renderNotificationDeliveries(rows) {
  if (!notificationDeliveriesEl) return;
  notificationDeliveriesEl.replaceChildren();
  for (const row of rows || []) { const tr = node('tr'); tr.append(node('td', stamp(row.created)), node('td', row.trigger), node('td', (row.recipients || []).join(', ')), node('td', row.status)); notificationDeliveriesEl.append(tr); }
  if (!rows || !rows.length) { const tr = node('tr'); const td = node('td', 'No notification deliveries recorded.'); td.colSpan = 4; tr.append(td); notificationDeliveriesEl.append(tr); }
}
function renderNotificationSettings(rows) {
  if (!notificationSettingsEl) return;
  notificationSettingsEl.replaceChildren();
  for (const row of rows || []) {
    const article = node('article', undefined, 'reviewitem'); const label = node('label'); const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = !!row.enabled; checkbox.disabled = row.trigger === 'contact_form'; label.append(checkbox, node('strong', row.trigger.replaceAll('_', ' ')));
    const recipients = document.createElement('input'); recipients.type = 'text'; recipients.value = (row.recipients || []).join(', '); recipients.placeholder = 'name@cccbuild.com'; recipients.disabled = row.trigger === 'contact_form';
    const save = node('button', 'Save', 'ghost'); save.type = 'button'; save.addEventListener('click', async () => { save.disabled = true; notificationMessage('Saving ' + row.trigger + '…'); try { const values = recipients.value.split(',').map(x => x.trim()).filter(Boolean); const response = await request('/private/api/dashboard/notifications/update', {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:JSON.stringify({trigger:row.trigger, enabled:checkbox.checked, recipients:values})}); if (!response.ok) throw new Error('Setting could not be saved.'); notificationMessage('Saved ' + row.trigger + '.'); await loadNotifications(); } catch (error) { notificationMessage(error.message); } finally { save.disabled = false; } });
    article.append(label, node('span', row.trigger === 'contact_form' ? ' Always on for contact follow-up.' : ' Optional trigger.', 'muted'), recipients, save); notificationSettingsEl.append(article);
  }
}
async function loadNotifications() { if (!notificationSettingsEl) return; try { const settings = await (await request('/private/api/dashboard/notifications/settings')).json(); renderNotificationSettings(settings.settings); const deliveries = await (await request('/private/api/dashboard/notifications/deliveries')).json(); renderNotificationDeliveries(deliveries.deliveries); notificationMessage('Settings loaded. Test sends go only to ' + settings.test_recipient + '.'); } catch (error) { notificationMessage(error.message); } }
if (notificationSettingsEl) { $('notifications-tab').addEventListener('click', loadNotifications); $('notification-refresh').addEventListener('click', loadNotifications); $('notification-test').addEventListener('click', async () => { const button = $('notification-test'); button.disabled = true; notificationMessage('Sending the test email to sri@srinagubandi.com…'); try { const response = await request('/private/api/dashboard/notifications/test', {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:'{}'}); if (!response.ok) throw new Error('Test email could not be sent.'); notificationMessage('Test email request accepted for sri@srinagubandi.com.'); await loadNotifications(); } catch (error) { notificationMessage(error.message); } finally { button.disabled = false; } }); }
