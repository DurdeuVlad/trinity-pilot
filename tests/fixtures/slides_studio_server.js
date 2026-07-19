#!/usr/bin/env node
/* Deterministic, local-only browser fixture for hard Trinity Pilot demos. */
const http = require('http');
const crypto = require('crypto');

const host = '127.0.0.1';
const port = Number(process.env.SLIDES_STUDIO_PORT || 0);
const state = { deck: null, audit: [], intake: [], cases: {}, acknowledgements: [] };

function reset() {
  state.deck = {
    published: false,
    shareToken: 'SLIDES-SIGNALDESK-2026',
    slides: [{ id: 'slide-1', title: '', body: '', notes: '', theme: 'light', layout: 'title', asset: '' }],
  };
  state.audit = [];
  state.intake = [];
  state.cases = { 'INC-204': { id: 'INC-204', status: 'Open', owner: 'Unassigned' } };
  state.acknowledgements = [];
}
reset();

function json(res, code, value) {
  res.writeHead(code, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' });
  res.end(JSON.stringify(value));
}
function html(res, body) {
  res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' });
  res.end(body);
}
function read(req) { return new Promise(resolve => { let body = ''; req.on('data', c => body += c); req.on('end', () => resolve(body ? JSON.parse(body) : {})); }); }
function requireUi(req, res) { if (req.headers['x-slides-studio-ui'] !== '1') { json(res, 403, { error: 'visible UI interaction required' }); return false; } return true; }
function audit(type, detail) { state.audit.push({ seq: state.audit.length + 1, type, detail, at: new Date().toISOString() }); }
function slide(id) { return state.deck.slides.find(item => item.id === id); }
function page(title, body, script = '') {
  return `<!doctype html><html><head><meta charset="utf-8"><title>${title}</title><style>
  body{margin:0;font:15px Inter,Arial,sans-serif;background:#f4f6fb;color:#172033}button,input,textarea,select{font:inherit}button{cursor:pointer}.bar{padding:14px 24px;background:#172033;color:white}.wrap{display:flex;min-height:calc(100vh - 52px)}.nav{width:230px;background:white;border-right:1px solid #d7dce8;padding:16px}.main{padding:26px;flex:1}.slide-btn{width:100%;margin:4px 0;text-align:left;padding:9px}.card{background:white;border:1px solid #d7dce8;border-radius:10px;padding:18px;margin:12px 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.wide{width:100%;box-sizing:border-box;padding:9px;margin-top:4px}.asset,.theme,.layout{padding:10px;margin:4px;border:1px solid #b9c4da;background:#fff}.selected{outline:3px solid #2d6cdf}.dark{background:#172033;color:#fff}.warning{background:#fff2cc}.workflow{background:#dff3e4}.closing{background:#efe0ff}
  </style></head><body><div class="bar"><b>Slides Studio</b> <span aria-label="local test fixture">Local test fixture</span></div>${body}<script>${script}</script></body></html>`;
}

function studio() {
  const slides = state.deck.slides.map((s, i) => `<button class="slide-btn" data-slide="${s.id}">Slide ${i + 1}: ${s.title || 'Untitled'}</button>`).join('');
  return page('Slides Studio editor', `<div class="wrap"><aside class="nav"><button id="add-slide">Add slide</button><button id="duplicate-slide">Duplicate</button><button id="delete-slide">Delete</button><hr>${slides}</aside><main class="main"><div class="card"><label>Slide title<input id="title" class="wide" aria-label="Slide title"></label><label>Slide body<textarea id="body" class="wide" rows="6" aria-label="Slide body"></textarea></label><label>Speaker notes<textarea id="notes" class="wide" rows="3" aria-label="Speaker notes"></textarea></label></div><div class="card"><b>Theme</b><button class="theme" data-theme="light">Light</button><button class="theme" data-theme="dark">Dark</button><button class="theme" data-theme="vivid">Vivid</button><br><b>Layout</b><button class="layout" data-layout="title">Title</button><button class="layout" data-layout="two-column">Two column</button><button class="layout" data-layout="solution">Solution</button><button class="layout" data-layout="comparison">Comparison</button><button class="layout" data-layout="closing">Closing</button><br><b>Assets</b><button class="asset" data-asset="warning">Warning asset</button><button class="asset" data-asset="workflow">Workflow asset</button><button class="asset" data-asset="closing">Closing asset</button></div><button id="review-deck">Review deck</button></main></div>`, `
  let selected='slide-1'; let deck=null;
  async function api(path, body){const r=await fetch(path,{method:'POST',headers:{'content-type':'application/json','x-slides-studio-ui':'1'},body:JSON.stringify(body||{})});return r.json()}
  async function load(){deck=await fetch('/api/deck').then(r=>r.json()); const s=deck.slides.find(x=>x.id===selected)||deck.slides[0]; selected=s.id; title.value=s.title; body.value=s.body; notes.value=s.notes; document.querySelectorAll('[data-slide]').forEach(b=>b.classList.toggle('selected',b.dataset.slide===selected));}
  document.querySelectorAll('[data-slide]').forEach(b=>b.onclick=async()=>{selected=b.dataset.slide; await api('/api/event',{type:'select_slide',id:selected}); await load()});
  for(const id of ['title','body','notes']) document.getElementById(id).oninput=()=>api('/api/event',{type:'fill',id:selected,field:id,value:document.getElementById(id).value});
  document.querySelectorAll('[data-theme]').forEach(b=>b.onclick=async()=>{await api('/api/event',{type:'theme',id:selected,value:b.dataset.theme});await load()});
  document.querySelectorAll('[data-layout]').forEach(b=>b.onclick=async()=>{await api('/api/event',{type:'layout',id:selected,value:b.dataset.layout});await load()});
  document.querySelectorAll('[data-asset]').forEach(b=>b.onclick=async()=>{await api('/api/event',{type:'asset',id:selected,value:b.dataset.asset});await load()});
  document.getElementById('add-slide').onclick=async()=>{const r=await api('/api/event',{type:'add_slide'});selected=r.id;location.reload()};
  document.getElementById('duplicate-slide').onclick=async()=>{const r=await api('/api/event',{type:'duplicate_slide',id:selected});selected=r.id;location.reload()};
  document.getElementById('delete-slide').onclick=async()=>{await api('/api/event',{type:'delete_slide',id:selected});location.reload()};
  document.getElementById('review-deck').onclick=async()=>{await api('/api/event',{type:'review'});location='/slides/review'}; load();`);
}
function review() {
  const summary = state.deck.slides.map((s, i) => `<li>${i + 1}. <b>${s.title || 'Untitled'}</b> — ${s.layout}, ${s.theme}, ${s.asset || 'no asset'}<br>${s.body}</li>`).join('');
  return page('Slides Studio review', `<main class="main"><div class="card"><h1>Deck review</h1><p id="slide-count">Slide count: ${state.deck.slides.length}</p><ol>${summary}</ol><button id="publish-deck">Publish deck</button><p id="published"></p></div></main>`, `document.getElementById('publish-deck').onclick=async()=>{const r=await fetch('/api/event',{method:'POST',headers:{'content-type':'application/json','x-slides-studio-ui':'1'},body:JSON.stringify({type:'publish'})}).then(x=>x.json());document.getElementById('published').textContent='Published. Share token: '+r.shareToken}`);
}
function intake() { return page('Operations intake', `<main class="main"><form id="intake" class="card"><h1>Operations intake</h1><label>Name<input name="name" required></label><label>Email<input name="email" required></label><label>Team<input name="team" required></label><label>Priority<input name="priority" required></label><label>Summary<textarea name="summary" required></textarea></label><label><input type="checkbox" name="policy" required> I accept the response policy</label><button>Submit incident</button><p id="result"></p></form></main>`, `intake.onsubmit=async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(intake));const r=await fetch('/api/intake',{method:'POST',headers:{'content-type':'application/json','x-slides-studio-ui':'1'},body:JSON.stringify(d)}).then(x=>x.json());result.textContent='Submission confirmed: '+r.confirmation}`); }
function triage() { return page('Case triage', `<main class="main"><div class="card"><label>Find case<input id="filter"></label><button id="find">Search</button><div id="case"></div></div></main>`, `find.onclick=async()=>{const id=filter.value;const c=await fetch('/api/case/'+encodeURIComponent(id)).then(r=>r.json());case.innerHTML='<h2>'+c.id+'</h2><label>Status<input id="status" value="'+c.status+'"></label><label>Owner<input id="owner" value="'+c.owner+'"></label><button id="save">Save case</button><p id="saved"></p>';save.onclick=async()=>{const r=await fetch('/api/case/'+id,{method:'POST',headers:{'content-type':'application/json','x-slides-studio-ui':'1'},body:JSON.stringify({status:status.value,owner:owner.value})}).then(x=>x.json());saved.textContent='Saved '+r.status+' for '+r.owner}}`); }
function knowledge() { return page('Knowledge base', `<main class="main"><div class="card"><h1>Knowledge base</h1><a id="open-runbook" href="/knowledge/runbook">Open escalation runbook</a></div></main>`); }
function runbook() { return page('Escalation runbook', `<main class="main"><div class="card"><h1>Escalation runbook</h1><p id="required-fact">The escalation window is 15 minutes.</p><a id="open-ack" href="/knowledge/acknowledge">Acknowledge runbook</a></div></main>`); }
function acknowledge() { return page('Acknowledge runbook', `<main class="main"><form id="ack" class="card"><label>Operator<input name="operator" required></label><label><input type="checkbox" name="confirmed" required> I acknowledge the 15 minute window</label><button>Acknowledge</button><p id="result"></p></form></main>`, `ack.onsubmit=async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(ack));const r=await fetch('/api/ack',{method:'POST',headers:{'content-type':'application/json','x-slides-studio-ui':'1'},body:JSON.stringify(d)}).then(x=>x.json());result.textContent='Acknowledged: '+r.token}`); }

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${host}`);
  if (req.method === 'GET' && url.pathname === '/health') return json(res, 200, { ok: true });
  if (req.method === 'POST' && url.pathname === '/_test/reset') { reset(); return json(res, 200, { ok: true }); }
  if (req.method === 'GET' && url.pathname === '/_test/audit') return json(res, 200, state);
  if (req.method === 'GET' && url.pathname === '/api/deck') return json(res, 200, state.deck);
  if (req.method === 'POST' && url.pathname === '/api/event') {
    if (!requireUi(req, res)) return;
    const event = await read(req); const s = slide(event.id);
    if (event.type === 'fill' && s && ['title','body','notes'].includes(event.field)) s[event.field] = String(event.value || '');
    if (event.type === 'theme' && s) s.theme = event.value;
    if (event.type === 'layout' && s) s.layout = event.value;
    if (event.type === 'asset' && s) s.asset = event.value;
    if (event.type === 'add_slide') { const item = { id: 'slide-' + (state.deck.slides.length + 1), title:'', body:'', notes:'', theme:'light', layout:'title', asset:'' }; state.deck.slides.push(item); audit('add_slide', item.id); return json(res, 200, { id: item.id }); }
    if (event.type === 'duplicate_slide' && s) { const item = { ...s, id: 'slide-' + (state.deck.slides.length + 1) }; state.deck.slides.push(item); audit('duplicate_slide', item.id); return json(res, 200, { id: item.id }); }
    if (event.type === 'delete_slide' && state.deck.slides.length > 1) state.deck.slides = state.deck.slides.filter(item => item.id !== event.id);
    if (event.type === 'publish') state.deck.published = true;
    audit(event.type, { id: event.id, field: event.field, value: event.value });
    return json(res, 200, { ok: true, shareToken: state.deck.shareToken });
  }
  if (req.method === 'POST' && url.pathname === '/api/intake') { if (!requireUi(req, res)) return; const data = await read(req); const confirmation = 'INC-' + String(state.intake.length + 101); state.intake.push({ ...data, confirmation }); audit('intake_submit', confirmation); return json(res, 200, { confirmation }); }
  if (req.method === 'GET' && url.pathname.startsWith('/api/case/')) return json(res, 200, state.cases[decodeURIComponent(url.pathname.split('/').pop())] || {});
  if (req.method === 'POST' && url.pathname.startsWith('/api/case/')) { if (!requireUi(req, res)) return; const id = decodeURIComponent(url.pathname.split('/').pop()); const data = await read(req); state.cases[id] = { id, ...data }; audit('case_save', state.cases[id]); return json(res, 200, state.cases[id]); }
  if (req.method === 'POST' && url.pathname === '/api/ack') { if (!requireUi(req, res)) return; const data = await read(req); const token = 'ACK-15M'; state.acknowledgements.push({ ...data, token }); audit('acknowledge', token); return json(res, 200, { token }); }
  if (req.method === 'GET' && url.pathname === '/') return html(res, '<a href="/slides">Open Slides Studio</a>');
  if (req.method === 'GET' && url.pathname === '/slides') return html(res, studio());
  if (req.method === 'GET' && url.pathname === '/slides/review') return html(res, review());
  if (req.method === 'GET' && url.pathname === '/intake') return html(res, intake());
  if (req.method === 'GET' && url.pathname === '/triage') return html(res, triage());
  if (req.method === 'GET' && url.pathname === '/knowledge') return html(res, knowledge());
  if (req.method === 'GET' && url.pathname === '/knowledge/runbook') return html(res, runbook());
  if (req.method === 'GET' && url.pathname === '/knowledge/acknowledge') return html(res, acknowledge());
  res.writeHead(404); res.end('Not found');
});
server.listen(port, host, () => console.log(JSON.stringify({ host, port: server.address().port })));
