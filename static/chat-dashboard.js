(() => {
'use strict';

const ui = {
  overviewTab: document.getElementById('overview-tab'),
  chatsTab: document.getElementById('chats-tab'),
  overviewPanel: document.getElementById('overview-panel'),
  chatsPanel: document.getElementById('chats-panel'),
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

    const btn = make('button', '', 'cc-chat-select');
    btn.type = 'button';
    btn.dataset.chatId = id;
    btn.setAttribute('aria-controls', 'chat-detail');
    btn.setAttribute('aria-current', String(id === state.selected));

    const statusSpan = make('span', human(chat.status), 'cc-chat-row');
    const createdSpan = make('span', stamp(chat.created), 'cc-chat-row');
    const previewSpan = make('span', previewText, 'cc-chat-preview');
    const countSpan = make('span', `Messages: ${Math.max(0, chat.message_count || 0)}`, 'cc-chat-meta');
    const contactSpan = make('span', contactPhrase, 'cc-chat-meta');
    const seenSpan = make('span', `Last activity: ${stamp(chat.last_seen)}`, 'cc-chat-meta');

    const badgeNodes = [];
    for (const [label, text] of emailPairs(chat.email_states)) {
      const badge = make('span', `${label}: ${text}`, 'cc-chat-badge');
      badgeNodes.push(badge);
    }

    btn.append(statusSpan, createdSpan, previewSpan, countSpan, contactSpan, seenSpan, ...badgeNodes);

    const li = make('li', '', 'cc-chat-item');
    li.appendChild(btn);
    nodes.push(li);

    if (id === focusedButtonId) foundFocus = true;
  }

  if (nodes.length === 0) {
    const emptyLi = make('li', query ? 'No chats match your search.' : 'No retained chats yet.', 'cc-chat-empty');
    nodes.push(emptyLi);
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

function detailPlaceholder(message){const h3=make('h3','Conversation','chat-detail-title');h3.id='chat-detail-title';const p=make('p',message,'cc-chat-empty');ui.detail.replaceChildren(h3,p)}function renderDetail(data){const h3=make('h3','Conversation '+validId(data.id),'chat-detail-title');h3.id='chat-detail-title';const summary=make('p','Status: '+human(data.status)+' · Created: '+stamp(data.created)+' · Last activity: '+stamp(data.last_seen)),notifications=make('section','','notifications'),h4=make('h4','Notification delivery'),dl=make('dl','','cc-chat-email'),pairs=emailPairs(data.email_states);for(const[kind,state]of pairs){const dt=make('dt',kind),dd=make('dd',state);dl.append(dt,dd)}notifications.append(h4,dl);const contact=contactSection(data.contact),messages=messageSection(data.messages);ui.detail.replaceChildren(h3,summary,contact,notifications,messages)}

function setTab(chats, focus = false) {
  ui.overviewTab.setAttribute('aria-selected', String(!chats));
  ui.chatsTab.setAttribute('aria-selected', String(chats));
  ui.overviewTab.tabIndex = chats ? -1 : 0;
  ui.chatsTab.tabIndex = chats ? 0 : -1;
  ui.overviewPanel.hidden = chats;
  ui.chatsPanel.hidden = !chats;
  if (focus) {
    (chats ? ui.chatsTab : ui.overviewTab).focus();
  }
  if (chats && !state.listLoaded && ui.list.getAttribute('aria-busy') !== 'true') {
    loadList();
  }
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
  setTab(true);
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
    setTab(false);
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

function onTabKey(e,isChats){
  switch(e.key){
    case'ArrowRight':setTab(!isChats,true);e.preventDefault();break;
    case'ArrowLeft':setTab(!isChats,true);e.preventDefault();break;
    case'Home':setTab(false,true);e.preventDefault();break;
    case'End':setTab(true,true);e.preventDefault();break;
  }
}

ui.overviewTab.addEventListener('keydown',e=>onTabKey(e,false));
ui.chatsTab.addEventListener('keydown',e=>onTabKey(e,true));
ui.overviewTab.addEventListener('click',()=>setTab(false,true));
ui.chatsTab.addEventListener('click',()=>setTab(true,true));

window.addEventListener('hashchange',followHash);

if(hashId())followHash();
else setTab(false);
})();
