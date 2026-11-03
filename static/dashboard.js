'use strict';
const $ = id => document.getElementById(id);
let state = null, csrf = '', queueState = 'all', visible = 200;
const usd = micro => '$' + (Number(micro || 0) / 1000000).toFixed(4);
const stamp = seconds => new Date(Number(seconds) * 1000).toISOString().slice(0, 19).replace('T', ' ');
function text(id, value) { $(id).textContent = String(value); }
function node(tag, value, className) { const e = document.createElement(tag); if (value !== undefined) e.textContent = String(value); if (className) e.className = className; return e; }
function empty(parent, message) { parent.replaceChildren(node('p', message, 'muted')); }
function detail(parent, values) {
  parent.replaceChildren();
  for (const [key, value] of values) { parent.append(node('dt', key), node('dd', value)); }
}
async function request(path, options = {}) {
  const response = await fetch(path, {credentials: 'same-origin', cache: 'no-store', ...options});
  if (response.status === 401) { location.replace('/dashboard/login'); throw new Error('Session expired.'); }
  if (!response.ok) throw new Error(response.status === 429 ? 'Request limit reached. Please wait before refreshing.' : 'Request could not be completed.');
  return response;
}
function trend(rows) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 600 190'); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', 'Incoming questions per UTC day over the last 30 days');
  const max = Math.max(1, ...rows.map(r => r.total));
  for (const [i, row] of rows.entries()) {
    const bar = document.createElementNS(ns, 'rect');
    const height = (row.total / max) * 145;
    bar.setAttribute('x', String(i * 20 + 2)); bar.setAttribute('y', String(155 - height)); bar.setAttribute('width', '14'); bar.setAttribute('height', String(height)); bar.setAttribute('rx', '3'); bar.setAttribute('fill', '#b4986d');
    const title = document.createElementNS(ns, 'title'); title.textContent = row.day + ': ' + row.total + ' questions'; bar.append(title); svg.append(bar);
    if (i === 0 || i === 14 || i === 29) { const label = document.createElementNS(ns, 'text'); label.setAttribute('x', String(i * 20 + 2)); label.setAttribute('y', '179'); label.setAttribute('fill', '#54647a'); label.setAttribute('font-size', '11'); if (i === 29) label.setAttribute('text-anchor', 'end'); label.textContent = row.day.slice(5); svg.append(label); }
  }
  $('trend').replaceChildren(svg);
  text('trendtext', rows.reduce((sum, r) => sum + r.total, 0) + ' retained incoming questions in the 30-day UTC trend. Hover over a bar for its date and count.');
}
function bars(parent, rows) {
  if (!rows.length) { empty(parent, 'No curated FAQ answers recorded in this window.'); return; }
  parent.replaceChildren();
  const max = Math.max(...rows.map(r => r[1]));
  for (const [name, count] of rows.slice(0, 10)) {
    const item = node('div', undefined, 'baritem');
    const heading = node('div', undefined, 'sectionhead'); heading.append(node('span', name), node('strong', count));
    const track = node('div', undefined, 'bartrack'); const fill = node('span'); fill.style.width = (count / max * 100) + '%'; track.append(fill); item.append(heading, track); parent.append(item);
  }
}
function questions() {
  if (!state) return;
  const search = $('search').value.toLocaleLowerCase(), outcome = $('outcome').value;
  const rows = state.events.filter(r => (outcome === 'all' || r.outcome === outcome) && [r.question, r.outcome, r.reason, ...r.faq_ids].join(' ').toLocaleLowerCase().includes(search));
  text('tablecount', rows.length + ' matching questions');
  $('questions').replaceChildren();
  for (const row of rows.slice(0, visible)) {
    const tr = node('tr');
    const outcomeCell = node('td'); outcomeCell.append(node('span', row.outcome.replaceAll('_', ' '), 'badge'), node('small', row.reason.replaceAll('_', ' '), 'block muted'));
    tr.append(node('td', stamp(row.created)), node('td', row.question, 'questioncell'), node('td', row.channel), outcomeCell, node('td', row.faq_ids.join(', ') || '—'), node('td', (row.model_used || 'No model call') + ' · ' + usd(row.cost_micro)));
    $('questions').append(tr);
  }
  if (!rows.length) { const row = node('tr'); const cell = node('td', 'No matching real incoming questions.'); cell.colSpan = 6; row.append(cell); $('questions').append(row); }
  $('more').hidden = rows.length <= visible;
}
function unknowns() {
  const rows = state.unanswered_questions.filter(q => queueState === 'all' || q.state === queueState);
  if (!rows.length) { empty($('unknowns'), 'No retained questions in this review state.'); return; }
  $('unknowns').replaceChildren();
  for (const q of rows) {
    const item = node('article', undefined, 'reviewitem'); const top = node('div', undefined, 'sectionhead');
    top.append(node('span', '#' + q.id + ' · ' + stamp(q.created), 'muted'), node('span', q.state.replaceAll('_', ' ') + ' · ' + q.occurrences + ' occurrence(s)', 'badge'));
    item.append(top, node('p', q.question)); $('unknowns').append(item);
  }
}
function report(report) {
  $('report').replaceChildren();
  if (!report.available) { empty($('report'), report.message); return; }
  $('report').append(node('h3', report.title), node('p', report.notice, 'notice'), node('p', 'Draft generated: ' + report.generated_at, 'muted'));
  for (const section of report.sections) { $('report').append(node('h3', section.heading), node('p', section.text)); for (const url of section.source_urls) { const a = node('a', url); a.href = url; a.rel = 'noopener noreferrer'; $('report').append(a); } }
}
function render() {
  const counts = state.counts, budget = state.model_budget, r = state.readiness;
  text('total', counts.total); text('answered', counts.answered); text('unanswered', counts.unanswered); text('cost', usd(state.period_cost_micro_usd));
  text('budget', usd(budget.committed_micro_usd) + ' committed / $1.00'); $('budgetbar').style.width = Math.min(100, budget.committed_micro_usd / budget.cap_micro_usd * 100) + '%';
  detail($('budgetdetail'), [['UTC month', budget.month], ['Settled charges', usd(budget.settled_micro_usd)], ['In-flight reservations', usd(budget.inflight_micro_usd)], ['Uncertain failures', usd(budget.uncertain_micro_usd)], ['Available budget', usd(budget.remaining_micro_usd)]]);
  detail($('readiness'), [['Eligible FAQs', r.knowledge_count], ['Model configured', r.model_configured ? 'Yes' : 'No — deterministic FAQ lookup still available'], ['Pinned model', r.model], ['Price readiness', r.pricing_status.replaceAll('_', ' ')], ['Last pricing check', r.pricing_checked_at ? stamp(r.pricing_checked_at) : 'Not checked — no paid call has been made'], ['Selection mode', 'Approved IDs only · high effort · 8,192 tokens']]);
  text('emailstatus', state.digest.enabled ? 'Email digest: ' + state.digest.status.replaceAll('_', ' ') : 'Email inactive — owner approval required. No test email has been sent by this service.');
  text('rateblocked', counts.rate_blocked + ' rate-blocked questions and ' + counts.invalid + ' invalid inputs in this window.');
  text('privacy', state.privacy_notice); text('retention', state.retention_notice);
  trend(state.trend); bars($('topfaqs'), state.top_faqs); questions(); unknowns(); report(state.report);
  if (!state.source_usage.length) empty($('sources'), 'No curated source citations recorded in this window.');
  else { $('sources').replaceChildren(); for (const [url, count] of state.source_usage) { const item = node('p'); const a = node('a', url); a.href = url; a.rel = 'noopener noreferrer'; item.append(a, node('span', ' · ' + count + ' use(s)', 'muted')); $('sources').append(item); } }
  text('status', counts.total ? 'Showing retained real incoming questions. No synthetic activity or automatic FAQ approvals.' : 'No real incoming questions have been retained yet. This dashboard does not invent historical activity.');
}
async function load() {
  text('status', 'Loading retained incoming questions…');
  try { const response = await request('/private/api/dashboard/summary?days=' + $('days').value); state = await response.json(); visible = 200; render(); }
  catch (error) { text('status', error.message); }
}
async function download(format) {
  try { const response = await request('/private/api/dashboard/export.' + format + '?days=' + $('days').value); const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = node('a'); link.href = url; link.download = 'coastal-questions.' + format; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
  catch (error) { text('status', error.message); }
}
$('days').addEventListener('change', load);
$('search').addEventListener('input', () => { visible = 200; questions(); });
$('outcome').addEventListener('change', () => { visible = 200; questions(); });
$('more').addEventListener('click', () => { visible += 200; questions(); });
$('exportcsv').addEventListener('click', () => download('csv')); $('exportjson').addEventListener('click', () => download('json'));
for (const button of document.querySelectorAll('[data-state]')) button.addEventListener('click', () => { queueState = button.dataset.state; for (const b of document.querySelectorAll('[data-state]')) b.setAttribute('aria-pressed', String(b === button)); unknowns(); });
$('logout').addEventListener('click', async () => { try { await request('/private/api/dashboard/logout', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: '{}'}); location.replace('/dashboard/login'); } catch (error) { text('status', error.message); } });
(async () => { try { csrf = (await (await request('/private/api/dashboard/session')).json()).csrf; await load(); } catch (error) { text('status', error.message); } })();
