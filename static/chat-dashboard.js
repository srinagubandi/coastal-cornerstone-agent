(() => {
'use strict';

const ui = {
  overviewTab: document.getElementById('overview-tab'),
  chatsTab: document.getElementById('chats-tab'),
  notificationsTab: document.getElementById('notifications-tab'),
  overviewPanel: document.getElementById('overview-panel'),
  chatsPanel: document.getElementById('chats-panel'),
  faqTab: document.getElementById('faq-tab'),
  faqPanel: document.getElementById('faq-panel'),
  faqStatus: document.getElementById('faq-status'),
  faqCount: document.getElementById('faq-count'),
  faqSearch: document.getElementById('faq-search'),
  faqList: document.getElementById('faq-list'),
  faqRefresh: document.getElementById('faq-refresh'),
  faqDetail: document.getElementById('faq-detail'),
  faqDetailTitle: document.getElementById('faq-detail-title'),
  faqDetailBody: document.getElementById('faq-detail-body'),
  faqDetailClose: document.getElementById('faq-detail-close'),
  notificationsPanel: document.getElementById('notifications-panel'),
  search: document.getElementById('chat-search'),
  list: document.getElementById('chat-list'),
  detail: document.getElementById('chat-detail'),
  status: document.getElementById('chat-status'),
  refresh: document.getElementById('chat-refresh')
};

if (Object.values(ui).some(el => !el)) {
  return;
}

const state = {
  chats: [],
  selected: '',
  listLoaded: false,
  faqLoaded: false,
  faqItems: [],
  listEpoch: 0,
  detailEpoch: 0
};

const make = (tag, text, className) => {
  const el = document.createElement(tag);
  if (text !== undefined && text !== null) {
    el.textContent = String(text);
  }
  if (className) el.className = className;
  return el;
};

const validId = value => typeof value === 'string' && /^[0-9a-f]{32}$/i.test(value) ? value.toLowerCase() : '';

const hashId = () => {
  const match = location.hash.match(/^#chat=([0-9a-f]{32})$/i);
  return match ? match[1].toLowerCase() : '';
};

const stamp = value => {
  let time = NaN;
  if (typeof value === 'number') {
    time = new Date(value * 1000).getTime();
  } else if (typeof value === 'string') {
    time = new Date(value).getTime();
  }
  return Number.isFinite(time) ? new Date(time).toUTCString() : 'Unavailable';
};

const human = value => {
  if (typeof value === 'string' || typeof value === 'number') {
    return String(value).replace(/_/g, ' ');
  }
  return 'Unknown';
};

const setStatus = (message, isError = false) => {
  ui.status.textContent = message;
  ui.status.setAttribute('data-error', String(isError));
};

const getPrivate = async path => {
  let res;
  try {
    res = await fetch(path, {
      credentials: 'same-origin',
      cache: 'no-store',
      method: 'GET',
      headers: { Accept: 'application/json' }
    });
  } catch {
    throw new Error('Network unavailable. Please try Refresh chats.'); 
  }
  if (res.status === 401) {
    const id = hashId() || validId(state.selected);
    location.replace('/dashboard/login' + (id ? '#chat=' + id : ''));
    throw new Error('Session expired.');
  }
  if (res.status === 404) throw new Error('Record unavailable or expired.');
  if (res.status === 429) throw new Error('Request limit reached. Please wait before refreshing.');
  if (!res.ok) throw new Error('Request unavailable.');
  let data;
  try {
    data = await res.json();
  } catch {
    throw new Error('Invalid response');
  }
  if (typeof data !== 'object' || data === null || Array.isArray(data)) throw new Error('Invalid response');
  return data;
};

const safeSource = value => {
  if (typeof value !== 'string' || /[\x00-\x1f\x7f]/.test(value)) return null;
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol)) return null;
    const validHosts = ['cccbuild.com', 'www.cccbuild.com', 'cccbuild-3mhyn4jl.manus.space'];
    if (!validHosts.includes(url.hostname)) return null;
    if (url.username || url.password || url.port) return null;
    let path = url.pathname;
    let decoded = path;
    for (let i = 0; i < 4; i++) {
      try {
        const temp = decodeURIComponent(decoded);
        if (temp === decoded) break;
        decoded = temp;
      } catch (e) {
        return null;
      }
    }
    if (decoded.includes('%') || /[\\\x00-\x1f\x7f]/.test(decoded)) return null;
    if (/^\/(dashboard|private|static|api)(?:[\/;]|$)/i.test(decoded)) return null;
    return url.href;
  } catch (e) {
    return null;
  }
};

const emailPairs = value => {
  const pairs = [];
  if (Array.isArray(value)) {
    for (const item of value) {
      if (item && typeof item === 'object' && item.kind) {
        const label = human(item.kind);
        const text = human(item.state || item.status || 'Not queued');
        pairs.push([label, text]);
      }
    }
  } else if (value && typeof value === 'object') {
    for (const [kind, v] of Object.entries(value)) {
      if (v === null) continue;
      const label = human(kind);
      const text = human((v && (v.state || v.status)) || v || 'Not queued');
      pairs.push([label, text]);
    }
  }
  return pairs.length ? pairs : [['Status', 'Not queued']];
};

function markSelection(){const buttons=ui.list.querySelectorAll('button[data-chat-id]');for(const button of buttons){const chatId=button.dataset.chatId;if(chatId===state.selected){button.setAttribute('aria-current','true');}else{button.setAttribute('aria-current','false');}}}

function renderList() {
  const query = ui.search.value.trim().toLowerCase();
  const nodes = [];
  let focusedButtonId = '';
  if (ui.list.contains(document.activeElement)) {
    focusedButtonId = document.activeElement.dataset?.chatId || '';
  }
  let foundFocus = false;

  for (const chat of state.chats) {
    if (!chat || !validId(chat.id)) continue;
    const id = validId(chat.id);
    const contactPhrase = chat.contact_received ? 'Contact received' : 'No contact received';
    const previewText = chat.preview || 'No retained message preview';
    const searchable = [
      id,
      previewText,
      human(chat.status),
      contactPhrase,
      stamp(chat.created),
      stamp(chat.last_seen),
      ...emailPairs(chat.email_states).flat()
    ].join(' ').toLowerCase();

    if (query && !searchable.includes(query)) continue;

    const btn = make('button', previewText, 'cc-chat-row-link');
    btn.type = 'button';
    btn.dataset.chatId = id;
    btn.setAttribute('aria-controls', 'chat-detail');
    btn.setAttribute('aria-current', String(id === state.selected));

    const questionCell = make('td');
    questionCell.appendChild(btn);
    const notificationText = emailPairs(chat.email_states).map(([label, text]) => `${label}: ${text}`).join(' · ');
    const row = make('tr');
    row.append(
      make('td', stamp(chat.created)),
      questionCell,
      make('td', human(chat.status)),
      make('td', String(Math.max(0, chat.message_count || 0))),
      make('td', contactPhrase),
      make('td', notificationText)
    );
    nodes.push(row);

    if (id === focusedButtonId) foundFocus = true;
  }

  if (nodes.length === 0) {
    const emptyRow = make('tr');
    const emptyCell = make('td', query ? 'No chats match your search.' : 'No retained chats yet.', 'cc-chat-empty');
    emptyCell.colSpan = 6;
    emptyRow.appendChild(emptyCell);
    nodes.push(emptyRow);
  }

  ui.list.replaceChildren(...nodes);

  if (foundFocus) {
    const newBtn = ui.list.querySelector(`[data-chat-id="${focusedButtonId}"]`);
    if (newBtn) newBtn.focus();
  } else if (focusedButtonId) {
    ui.search.focus();
  }
}

function contactSection(contact){const section=make('section');section.appendChild(make('h4','Contact and follow-up'));if(!contact||typeof contact!=='object'||Array.isArray(contact)){const p=make('p','No contact details submitted.','cc-chat-empty');section.appendChild(p);return section;}const dl=make('dl',undefined,'cc-chat-contact');const fields=[['Name',contact.name],['Email',contact.email],['Phone',contact.phone],['Message',contact.message]];fields.forEach(([label,value])=>{const dt=make('dt',label);const dd=make('dd',typeof value==='string'||typeof value==='number'?String(value):'Unavailable');dl.appendChild(dt);dl.appendChild(dd);});section.appendChild(dl);return section;}

function messageSection(messages) {
  const section = make('section');
  const h4 = make('h4', 'Messages');
  const ol = make('ol', undefined, 'cc-chat-messages');
  section.appendChild(h4);
  section.appendChild(ol);
  if (!Array.isArray(messages)) return section;
  let hasMessages = false;
  for (const msg of messages) {
    if (!msg || typeof msg !== 'object' || !msg.role) continue;
    const role = msg.role;
    if (role !== 'visitor' && role !== 'assistant') continue;
    hasMessages = true;
    const li = make('li', undefined, 'cc-chat-message');
    if (role === 'assistant') li.classList.add('cc-chat-message--assistant');
    const header = make('header');
    const roleText = role === 'visitor' ? 'Visitor' : 'Coastal Cornerstone assistant';
    const timeText = stamp(msg.created);
    const headerText = roleText + ' · ' + timeText;
    const pHeader = make('p', headerText, 'cc-chat-message-header');
    header.appendChild(pHeader);
    li.appendChild(header);
    const text = typeof msg.text === 'string' ? msg.text : '';
    const pText = make('p', text, 'cc-chat-message-text');
    li.appendChild(pText);
    const sources = Array.isArray(msg.sources) ? msg.sources : [];
    const sourceUrls = [...new Set(sources.map(safeSource).filter(Boolean))];
    if (sourceUrls.length > 0) {
      const ulSources = make('ul', undefined, 'cc-chat-sources');
      for (const url of sourceUrls) {
        const srcLi = make('li');
        const a = make('a', url, undefined);
        a.href = url;
        a.rel = 'noopener noreferrer';
        srcLi.appendChild(a);
        ulSources.appendChild(srcLi);
      }
      li.appendChild(ulSources);
    }
    const faqIds = Array.isArray(msg.faq_ids) ? msg.faq_ids : [];
    if (faqIds.length > 0) {
      const faqText = faqIds.map(human).join(', ');
      if (faqText) {
        const faqP = make('p', 'FAQ IDs: ' + faqText);
        li.appendChild(faqP);
      }
    }
    ol.appendChild(li);
  }
  if (!hasMessages) {
    const emptyLi = make('li', 'No retained messages', 'cc-chat-empty');
    ol.appendChild(emptyLi);
  }
  return section;
}

function detailPlaceholder(message){const h3=make('h3','Conversation','chat-detail-title');h3.id='chat-detail-title';const p=make('p',message,'cc-chat-empty');ui.detail.replaceChildren(h3,p)}
function reviewSection(review,id){
  const section=make('section','','cc-chat-review');
  const nav=make('nav','Dashboard › Chats › Conversation','cc-breadcrumbs');nav.setAttribute('aria-label','Breadcrumb');
  const h4=make('h4','Review this conversation');
  const label=make('label','Classification');
  const select=document.createElement('select');select.id='chat-review-classification';select.name='classification';
  [['unreviewed','Unreviewed'],['ignore','Ignore'],['needs_answer','Needs answer'],['faq_candidate','FAQ candidate'],['sensitive_private','Sensitive/private']].forEach(([value,text])=>{const o=document.createElement('option');o.value=value;o.textContent=text;select.append(o)});
  select.value=review?.classification||'unreviewed';label.append(select);
  const answerLabel=make('label','Admin answer draft');const answer=document.createElement('textarea');answer.id='chat-review-answer';answer.maxLength=12000;answer.rows=5;answer.placeholder='Write an answer for review; this does not publish it.';answer.value=review?.answer_draft||'';answerLabel.append(answer);
  const noteLabel=make('label','Admin note');const note=document.createElement('textarea');note.id='chat-review-note';note.maxLength=2000;note.rows=3;note.placeholder='Why this classification or answer was chosen';note.value=review?.admin_note||'';noteLabel.append(note);
  const save=make('button','Save review','primary');save.type='button';save.addEventListener('click',async()=>{save.disabled=true;try{const response=await fetch('/private/api/dashboard/chats/'+id+'/review',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':window.chatDashboardCsrf||''},body:JSON.stringify({classification:select.value,answer_draft:answer.value,admin_note:note.value})});if(response.status===401){location.replace('/dashboard/login#chat='+id);return}if(!response.ok)throw new Error('Review could not be saved.');const data=await response.json();save.textContent='Saved';setTimeout(()=>{save.textContent='Save review'},1200);if(state.chats){const row=state.chats.find(x=>x.id===id);if(row)row.classification=data.review.classification;renderList()}}catch(error){save.textContent=error.message;setTimeout(()=>{save.textContent='Save review'},1800)}finally{save.disabled=false}});
  const status=make('p',review?.updated?'Last updated '+stamp(review.updated)+' by '+(review.updated_by||'admin'):'Not yet reviewed','muted');section.append(nav,h4,label,answerLabel,noteLabel,save,status);return section;
}
function renderDetail(data){const h3=make('h3','Conversation '+validId(data.id),'chat-detail-title');h3.id='chat-detail-title';const summary=make('p','Status: '+human(data.status)+' · Created: '+stamp(data.created)+' · Last activity: '+stamp(data.last_seen)),notifications=make('section','','notifications'),h4=make('h4','Notification delivery'),dl=make('dl','','cc-chat-email'),pairs=emailPairs(data.email_states);for(const[kind,state]of pairs){const dt=make('dt',kind),dd=make('dd',state);dl.append(dt,dd)}notifications.append(h4,dl);const contact=contactSection(data.contact),messages=messageSection(data.messages),review=reviewSection(data.review,data.id);ui.detail.replaceChildren(h3,summary,review,contact,notifications,messages)}
function renderFaqList() {
  const query = ui.faqSearch.value.trim().toLowerCase();
  const items = state.faqItems.filter(item => {
    const text = [item.id, item.question, item.answer, item.state, item.category, item.source].filter(Boolean).join(' ').toLowerCase();
    return !query || text.includes(query);
  });
  ui.faqCount.textContent = `${items.length} of ${state.faqItems.length} drafts`;
  const rows = items.map(item => {
    const row = make('tr');
    const question = make('button', item.question || 'Untitled question', 'cc-chat-row-link');
    question.type = 'button'; question.dataset.faqId = validId(item.id) || '';
    const questionCell = make('td'); questionCell.appendChild(question);
    row.append(questionCell, make('td', human(item.state || 'draft')), make('td', item.answer ? 'Answer drafted' : 'Needs answer'), make('td', item.source || item.source_url || 'Private draft'), make('td', stamp(item.updated || item.created)));
    return row;
  });
  if (!rows.length) { const row = make('tr'); const cell = make('td', query ? 'No FAQ drafts match this search.' : 'No FAQ drafts loaded.', 'cc-chat-empty'); cell.colSpan = 5; row.appendChild(cell); rows.push(row); }
  ui.faqList.replaceChildren(...rows);
}

async function loadFaq(force = false) {
  if (!force && state.faqLoaded) return;
  ui.faqStatus.textContent = 'Loading private FAQ drafts…';
  try {
    const data = await getPrivate('/private/api/dashboard/faq-review/drafts');
    if (!Array.isArray(data.items)) throw new Error('Invalid FAQ review response');
    state.faqItems = data.items;
    state.faqLoaded = true;
    renderFaqList();
    ui.faqStatus.textContent = 'Drafts are private until an Admin deliberately publishes an approved version.';
  } catch (error) {
    ui.faqStatus.textContent = error.message;
    ui.faqCount.textContent = 'Load failed';
  }
}

async function selectFaq(value) {
  const id = validId(value);
  if (!id) return;
  ui.faqDetail.hidden = false;
  ui.faqDetailTitle.textContent = 'FAQ draft';
  ui.faqDetailBody.replaceChildren(make('p', 'Loading draft…', 'muted'));
  try {
    const data = await getPrivate('/private/api/dashboard/faq-review/drafts/' + id);
    const question = make('h3', data.question || 'Untitled question');
    const stateLine = make('p', 'Status: ' + human(data.state || 'new'), 'badge');
    const questionLabel = make('label', 'Question');
    const questionInput = document.createElement('textarea'); questionInput.rows = 3; questionInput.value = data.question || ''; questionLabel.appendChild(questionInput);
    const answerLabel = make('label', 'Answer draft');
    const answerInput = document.createElement('textarea'); answerInput.rows = 8; answerInput.value = data.answer || ''; answerLabel.appendChild(answerInput);
    const tagsLabel = make('label', 'Tags (comma-separated)');
    const tagsInput = document.createElement('input'); tagsInput.type = 'text'; tagsInput.value = Array.isArray(data.tags) ? data.tags.join(', ') : ''; tagsLabel.appendChild(tagsInput);
    const source = make('p', 'Source: ' + (data.source || data.source_url || 'Private draft'), 'muted');
    const actions = make('div', undefined, 'actions');
    const save = make('button', 'Save draft', 'ghost'); const ready = make('button', 'Mark ready for approval', 'primary'); const reject = make('button', 'Reject', 'ghost');
    const saveDraft = async stateValue => {
      for (const button of [save, ready, reject]) button.disabled = true;
      try {
        const response = await fetch('/private/api/dashboard/faq-review/drafts/' + id + '/save', {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': window.chatDashboardCsrf || ''}, body: JSON.stringify({revision: data.revision, question: questionInput.value, answer: answerInput.value, tags: tagsInput.value.split(',').map(value => value.trim()).filter(Boolean), state: stateValue})});
        if (response.status === 401) { location.replace('/dashboard/login'); return; }
        if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.error || 'FAQ draft could not be saved.'); }
        ui.faqStatus.textContent = stateValue === 'ready' ? 'Draft marked ready for approval.' : stateValue === 'rejected' ? 'Draft rejected.' : 'Draft saved.';
        await loadFaq(true);
        await selectFaq(id);
      } catch (error) { ui.faqStatus.textContent = error.message; } finally { for (const button of [save, ready, reject]) button.disabled = false; }
    };
    save.addEventListener('click', () => saveDraft(data.state || 'in_progress'));
    ready.addEventListener('click', () => saveDraft('ready'));
    reject.addEventListener('click', () => saveDraft('rejected'));
    actions.append(save, ready, reject);
    ui.faqDetailBody.replaceChildren(question, stateLine, questionLabel, answerLabel, tagsLabel, source, actions);
  } catch (error) {
    ui.faqDetailBody.replaceChildren(make('p', error.message, 'notice'));
  }
}

function setTab(tab, focus = false) {
  const chats = tab === 'chats', faq = tab === 'faq', notifications = tab === 'notifications';
  ui.overviewTab.setAttribute('aria-selected', String(!chats && !faq && !notifications));
  ui.chatsTab.setAttribute('aria-selected', String(chats));
  ui.faqTab.setAttribute('aria-selected', String(faq));
  ui.notificationsTab.setAttribute('aria-selected', String(notifications));
  ui.overviewTab.tabIndex = !chats && !faq && !notifications ? 0 : -1;
  ui.chatsTab.tabIndex = chats ? 0 : -1;
  ui.faqTab.tabIndex = faq ? 0 : -1;
  ui.notificationsTab.tabIndex = notifications ? 0 : -1;
  ui.overviewPanel.hidden = chats || faq || notifications;
  ui.chatsPanel.hidden = !chats;
  ui.faqPanel.hidden = !faq;
  ui.notificationsPanel.hidden = !notifications;
  if (focus) {
    (notifications ? ui.notificationsTab : faq ? ui.faqTab : chats ? ui.chatsTab : ui.overviewTab).focus();
  }
  if (chats && !state.listLoaded && ui.list.getAttribute('aria-busy') !== 'true') {
    loadList();
  }
  if (faq) loadFaq();
}

async function loadList(force = false) {
  if (!force && state.listLoaded) return;
  const epoch = ++state.listEpoch;
  if (!state.selected) setStatus('Loading conversations');
  ui.list.setAttribute('aria-busy', 'true');
  try {
    const data = await getPrivate('/private/api/dashboard/chats');
    if (epoch !== state.listEpoch) return;
    if (!Array.isArray(data.chats)) throw new Error('Invalid conversation list');
    state.chats = data.chats;
    state.listLoaded = true;
    renderList();
    if (!state.selected) setStatus('Conversations loaded');
  } catch (error) {
    if (epoch !== state.listEpoch) return;
    state.listLoaded = false;
    ui.list.replaceChildren(make('li', 'Conversations could not be loaded. Try Refresh chats.', 'cc-chat-empty'));
    if (!state.selected) setStatus(error.message, true);
  } finally {
    if (epoch === state.listEpoch) {
      ui.list.setAttribute('aria-busy', 'false');
    }
  }
}

async function selectChat(value, updateHash = true) {
  const id = validId(value);
  if (!id) return;
  state.selected = id;
  setTab('chats');
  markSelection();
  if (updateHash) history.replaceState(null, '', location.pathname + location.search + '#chat=' + id);
  const epoch = ++state.detailEpoch;
  ui.detail.setAttribute('aria-busy', 'true');
  detailPlaceholder('Loading conversation');
  setStatus('Loading conversation');
  try {
    const data = await getPrivate('/private/api/dashboard/chats/' + id);
    if (epoch !== state.detailEpoch || state.selected !== id) return;
    if (validId(data.id) !== id || !Array.isArray(data.messages)) throw new Error('Invalid conversation detail');
    renderDetail(data);
    setStatus('Conversation loaded');
  } catch (error) {
    if (epoch === state.detailEpoch && state.selected === id) {
      detailPlaceholder('This conversation is unavailable. It may have expired.');
      setStatus(error.message, true);
    }
  } finally {
    if (epoch === state.detailEpoch) ui.detail.setAttribute('aria-busy', 'false');
  }
}

async function refreshChats(){
  if(ui.refresh.disabled)return;
  ui.refresh.disabled=true;
  ui.refresh.setAttribute('aria-busy','true');
  try{
    await Promise.all([
      loadList(true),
      state.selected?selectChat(state.selected,false):Promise.resolve()
    ]);
  }finally{
    ui.refresh.disabled=false;
    ui.refresh.setAttribute('aria-busy','false');
  }
}

function followHash(){
  const id=hashId();
  if(id){
    selectChat(id,false);
  }else{
    state.selected='';
    state.detailEpoch++;
    ui.detail.setAttribute('aria-busy','false');
    detailPlaceholder('No conversation selected');
    markSelection();
    setTab('overview');
  }
}

ui.refresh.addEventListener('click',refreshChats);
ui.search.addEventListener('input',renderList);
ui.list.addEventListener('click',e=>{
  if(!(e.target instanceof Element))return;
  const btn=e.target.closest('button[data-chat-id]');
  if(btn&&ui.list.contains(btn)){
    selectChat(btn.dataset.chatId,true);
  }
});

function onTabKey(e,tab){
  const tabs=['overview','chats','faq','notifications'], index=tabs.indexOf(tab);
  switch(e.key){
    case'ArrowRight':setTab(tabs[(index+1)%tabs.length],true);e.preventDefault();break;
    case'ArrowLeft':setTab(tabs[(index+tabs.length-1)%tabs.length],true);e.preventDefault();break;
    case'Home':setTab('overview',true);e.preventDefault();break;
    case'End':setTab('notifications',true);e.preventDefault();break;
  }
}

ui.overviewTab.addEventListener('keydown',e=>onTabKey(e,'overview'));
ui.chatsTab.addEventListener('keydown',e=>onTabKey(e,'chats'));
ui.faqTab.addEventListener('keydown',e=>onTabKey(e,'faq'));
ui.notificationsTab.addEventListener('keydown',e=>onTabKey(e,'notifications'));
ui.overviewTab.addEventListener('click',()=>setTab('overview',true));
ui.chatsTab.addEventListener('click',()=>setTab('chats',true));
ui.faqTab.addEventListener('click',()=>setTab('faq',true));
ui.notificationsTab.addEventListener('click',()=>setTab('notifications',true));
ui.faqRefresh.addEventListener('click',()=>loadFaq(true));
ui.faqSearch.addEventListener('input',renderFaqList);
ui.faqList.addEventListener('click',e=>{if(!(e.target instanceof Element))return;const btn=e.target.closest('button[data-faq-id]');if(btn)selectFaq(btn.dataset.faqId);});
ui.faqDetailClose.addEventListener('click',()=>{ui.faqDetail.hidden=true;ui.faqSearch.focus();});

window.addEventListener('hashchange',followHash);

if(hashId())followHash();
else setTab('overview');
})();
