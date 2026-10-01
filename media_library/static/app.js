/* 影像圖書館 前端 */
'use strict';

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const LS = {
  get(k, d) { try { const v = localStorage.getItem('vl.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('vl.' + k, JSON.stringify(v)); } catch { /* 無痕模式等 */ } },
};

const FIELD_ORDER = ['status', 'filename', 'full_path', 'media_type', 'description', 'highlights', 'keywords',
  'shot_time', 'processed_time', 'md_path', 'backup_path', 'error'];
let LABEL = {
  status: '狀態', filename: '檔名', full_path: '完整路徑', media_type: '媒體類型', description: '內容描述',
  highlights: '重點', keywords: '關鍵字', shot_time: '拍攝時間', processed_time: '處理時間',
  md_path: 'Markdown 路徑', backup_path: '備份路徑', error: '錯誤原因',
};
const DEFAULT_STATUSES = ['待確認', '已審核', '已確認', '需複查', '錯誤'];
const SPRITE_FRAMES = 12;

const S = {
  items: [], byId: new Map(), root: '', batches: [],
  f: { q: '', folder: '', status: new Set(), type: new Set(), kw: new Set(), picked: false, avail: '', marked: false },
  sort: LS.get('sort', 'full_path'), dir: LS.get('dir', 1), view: LS.get('view', 'grid'),
  sel: new Set(), filtered: [],
};

/* ---------------- utils ---------------- */
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const splitKw = s => (s || '').split(/[、，,;；|\n]+/).map(x => x.trim()).filter(Boolean);
const splitHl = s => (s || '').split(/[；;\n]+/).map(x => x.trim()).filter(Boolean);
function qTokens() { return S.f.q.toLowerCase().split(/\s+/).filter(Boolean); }
function hl(text, tokens = qTokens()) {
  let h = esc(text);
  if (!tokens.length || !text) return h;
  const re = new RegExp('(' + tokens.map(t => esc(t).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'gi');
  return h.replace(re, '<mark>$1</mark>');
}
function fmtDur(t) {
  if (t == null || isNaN(t)) return '';
  t = Math.max(0, t);
  const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = Math.floor(t % 60);
  return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(s).padStart(2, '0');
}
function fmtClock(t) {
  t = Math.max(0, t || 0);
  const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${s.toFixed(2).padStart(5, '0')}`;
}
function fmtTC(t, fps) {
  t = Math.max(0, t || 0);
  const nf = Math.round(fps || 30);
  const total = Math.floor(t * (fps || 30) + 1e-6);
  const f = total % nf, secs = Math.floor(total / nf);
  const h = Math.floor(secs / 3600), m = Math.floor(secs % 3600 / 60), s = secs % 60;
  return [h, m, s, f].map(x => String(x).padStart(2, '0')).join(':');
}
function fmtSize(b) {
  if (!b) return '';
  const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return b.toFixed(i > 1 ? 1 : 0) + ' ' + u[i];
}
function fmtDate(s) {
  if (!s) return '';
  const d = new Date(s);
  if (isNaN(d)) return s;
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
function statusClass(s) {
  s = s || '';
  if (/錯誤|失敗|error|fail/i.test(s)) return 'st-err';
  if (/已確認|完成|已處理|ok|done/i.test(s)) return 'st-ok';
  if (/待|複查|確認/.test(s)) return 'st-warn';
  return '';
}
let toastTimer;
function toast(msg, ms = 2600) {
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.hidden = true, ms);
}
async function api(url, opt = {}) {
  if (opt.json !== undefined) {
    opt.body = JSON.stringify(opt.json); opt.headers = { 'Content-Type': 'application/json' }; delete opt.json;
  }
  const r = await fetch(url, opt);
  if (!r.ok) {
    let m = r.statusText; try { m = (await r.json()).detail || m; } catch { }
    throw new Error(m);
  }
  return r.json();
}
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

/* ---------------- data ---------------- */
async function load() {
  const d = await api('/api/media');
  if (d.field_labels) LABEL = { ...LABEL, ...d.field_labels };
  S.items = d.items.map(m => derive({ ...m, _folder: m.rel_dir || '' }));
  S.byId = new Map(S.items.map(m => [m.id, m]));
  S.root = d.root; S.batches = d.batches;
  $('#rootName').textContent = d.root_name ? '／ ' + d.root_name : '';
  $('#rootName').title = d.root;
  for (const id of [...S.sel]) if (!S.byId.has(id)) S.sel.delete(id);
  updateDatalists();
  renderSidebar(); render();
  return d;
}
function derive(m) {
  m._kw = splitKw(m.keywords);
  m._hay = [m.filename, m.full_path, m.description, m.highlights, m.keywords, m.status, m.media_type, m.note,
    m.error, m.shot_time, m.md_path, m.backup_path, ...Object.values(m.extra || {})].join('\n').toLowerCase();
  return m;
}
function updateDatalists() {
  const kc = countBy(S.items, m => m._kw);
  $('#kwList').innerHTML = [...kc].sort((a, b) => b[1] - a[1]).map(([k]) => `<option value="${esc(k)}">`).join('');
  $('#statusList').innerHTML = statusOptions().map(s => `<option value="${esc(s)}">`).join('');
}
/* 把伺服器回傳的最新資料套用到本地（目錄、播放清單、目前播放中） */
function applyItem(d) {
  const local = S.byId.get(d.id);
  const keep = { _folder: local?._folder ?? '', marker_count: d.markers ? d.markers.length : local?.marker_count };
  for (const o of [local, ...P.list.filter(x => x.id === d.id && x !== local)]) {
    if (!o) continue;
    for (const k of Object.keys(d)) if (k !== 'markers' && k !== 'changed') o[k] = d[k];
    Object.assign(o, keep); derive(o);
  }
  if (P.cur?.id === d.id) Object.assign(P.cur, d);
}
/* 儲存欄位：fields = {status: '…', keywords: [...], 'x:自訂欄位': '…'} */
async function saveFields(id, fields, msg) {
  try {
    const d = await api('/api/media/' + id, { method: 'PATCH', json: { fields } });
    applyItem(d);
    if ('full_path' in fields) load();  // 資料夾、檔案可否存取需重新計算
    if (d.changed?.length) { pollSync(true); if (msg) osd(msg); }
    updateDatalists();
    return d;
  } catch (e) { toast('儲存失敗：' + e.message, 4000); throw e; }
}

function matches(m, skip) {
  const f = S.f;
  if (skip !== 'folder' && f.folder && !(m._folder === f.folder || m._folder.startsWith(f.folder + '/'))) return false;
  if (skip !== 'status' && f.status.size && !f.status.has(m.status || '（空白）')) return false;
  if (skip !== 'type' && f.type.size && !f.type.has(m.media_type || '（空白）')) return false;
  if (skip !== 'kw' && f.kw.size) for (const k of f.kw) if (!m._kw.includes(k)) return false;
  if (f.picked && !m.picked) return false;
  if (f.marked && !m.marker_count) return false;
  if (f.avail === 'yes' && !m.available) return false;
  if (f.avail === 'no' && m.available) return false;
  const toks = qTokens();
  for (const t of toks) if (!m._hay.includes(t)) return false;
  return true;
}

function applyFilters() {
  const key = S.sort, dir = S.dir;
  S.filtered = S.items.filter(m => matches(m)).sort((a, b) => {
    let x = a[key], y = b[key];
    if (key === 'size' || key === 'duration' || key === 'rating') { x = x || 0; y = y || 0; return (x - y) * dir; }
    x = (x || '').toString(); y = (y || '').toString();
    return x.localeCompare(y, 'zh-Hant', { numeric: true }) * dir;
  });
  return S.filtered;
}

/* ---------------- sidebar ---------------- */
function countBy(arr, fn) {
  const m = new Map();
  for (const x of arr) for (const k of [].concat(fn(x))) m.set(k, (m.get(k) || 0) + 1);
  return m;
}

function renderSidebar() {
  // 資料夾樹
  const base = S.items.filter(m => matches(m, 'folder'));
  const tree = { children: new Map(), n: 0 };
  for (const m of base) {
    tree.n++;
    let node = tree, path = '';
    for (const seg of m._folder ? m._folder.split('/') : []) {
      path = path ? path + '/' + seg : seg;
      if (!node.children.has(seg)) node.children.set(seg, { children: new Map(), n: 0, path });
      node = node.children.get(seg); node.n++;
    }
  }
  // 確保目前選取的資料夾也存在
  const rows = [`<div class="node ${S.f.folder ? '' : 'on'}" data-folder=""><span class="ic">▣</span>全部<span class="n">${tree.n}</span></div>`];
  const walk = (node, depth) => {
    for (const [name, ch] of [...node.children].sort((a, b) => a[0].localeCompare(b[0], 'zh-Hant', { numeric: true }))) {
      rows.push(`<div class="node ${S.f.folder === ch.path ? 'on' : ''}" data-folder="${esc(ch.path)}" style="padding-left:${8 + depth * 14}px" title="${esc(ch.path)}">
        <span class="ic">${ch.children.size ? '▾' : '▸'}</span>${esc(name)}<span class="n">${ch.n}</span></div>`);
      walk(ch, depth + 1);
    }
  };
  walk(tree, 1);
  $('#folderTree').innerHTML = rows.join('');

  const facet = (el, key, field) => {
    const base = S.items.filter(m => matches(m, key));
    const c = countBy(base, m => m[field] || '（空白）');
    for (const v of S.f[key]) if (!c.has(v)) c.set(v, 0);
    el.innerHTML = [...c].sort((a, b) => b[1] - a[1]).map(([k, n]) =>
      `<div class="opt ${S.f[key].has(k) ? 'on' : ''}" data-${key}="${esc(k)}"><span class="badge-status ${statusClass(key === 'status' ? k : '')}" style="position:static;padding:0 6px">${key === 'status' ? '●' : '▪'}</span>${esc(k)}<span class="n">${n}</span></div>`
    ).join('') || '<div class="muted">—</div>';
  };
  facet($('#statusFacet'), 'status', 'status');
  facet($('#typeFacet'), 'type', 'media_type');

  const nPick = S.items.filter(m => m.picked).length, nMark = S.items.filter(m => m.marker_count).length;
  const nNo = S.items.filter(m => !m.available).length;
  $('#miscFacet').innerHTML = `
    <div class="opt ${S.f.picked ? 'on' : ''}" data-misc="picked">★ 已挑選<span class="n">${nPick}</span></div>
    <div class="opt ${S.f.marked ? 'on' : ''}" data-misc="marked">🔖 有標記點<span class="n">${nMark}</span></div>
    <div class="opt ${S.f.avail === 'yes' ? 'on' : ''}" data-misc="avail-yes">✔ 檔案可存取<span class="n">${S.items.length - nNo}</span></div>
    <div class="opt ${S.f.avail === 'no' ? 'on' : ''}" data-misc="avail-no">⚠ 檔案無法存取<span class="n">${nNo}</span></div>`;

  // 關鍵字雲
  const kb = S.items.filter(m => matches(m, 'kw'));
  const kc = countBy(kb, m => m._kw);
  S.kwCounts = kc;
  const top = [...kc].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh-Hant'));
  const show = top.slice(0, 40);
  for (const k of S.f.kw) if (!show.find(x => x[0] === k)) show.unshift([k, kc.get(k) || 0]);
  $('#kwCloud').innerHTML = show.map(([k, n]) => `<span class="chip ${S.f.kw.has(k) ? 'on' : ''}" data-kw="${esc(k)}">${esc(k)}<span class="n">${n}</span></span>`).join('')
    || '<span class="muted">—</span>';
  $('#kwMore').textContent = `全部 (${kc.size})`;

  renderBatches();
}

$('#sidebar').addEventListener('click', e => {
  const t = e.target.closest('[data-folder],[data-status],[data-type],[data-kw],[data-misc],[data-delbatch]');
  if (!t) return;
  const f = S.f;
  if (t.dataset.folder !== undefined) f.folder = t.dataset.folder;
  else if (t.dataset.status !== undefined) toggleSet(f.status, t.dataset.status);
  else if (t.dataset.type !== undefined) toggleSet(f.type, t.dataset.type);
  else if (t.dataset.kw !== undefined) toggleSet(f.kw, t.dataset.kw);
  else if (t.dataset.misc) {
    const k = t.dataset.misc;
    if (k === 'picked') f.picked = !f.picked;
    else if (k === 'marked') f.marked = !f.marked;
    else { const v = k.split('-')[1]; f.avail = f.avail === v ? '' : v; }
  } else if (t.dataset.delbatch) { delBatch(+t.dataset.delbatch); return; }
  refresh();
});
function toggleSet(s, v) { s.has(v) ? s.delete(v) : s.add(v); }

async function delBatch(id) {
  const b = S.batches.find(x => x.id === id);
  if (!confirm(`確定要從資料庫移除「${b?.source_name}」匯入的 ${b?.row_count} 筆資料？\n（不會刪除影片檔案；屬於此批的挑選、備註、標記點會一併移除）`)) return;
  await api('/api/batches/' + id, { method: 'DELETE' });
  toast('已移除'); load();
}

/* ---------------- main render ---------------- */
function refresh() { renderSidebar(); render(); }

function render() {
  const list = applyFilters();
  $('#count').textContent = list.length;
  renderActiveFilters();
  $('#grid').hidden = S.view !== 'grid';
  $('#list').hidden = S.view !== 'list';
  $$('.seg [data-view]').forEach(b => b.classList.toggle('on', b.dataset.view === S.view));
  $('#sort').value = S.sort; $('#sortDir').textContent = S.dir > 0 ? '↑' : '↓';
  const empty = $('#empty');
  if (!S.items.length) {
    empty.hidden = false; $('#grid').hidden = $('#list').hidden = true;
    empty.innerHTML = `<div><div class="big">尚未匯入任何媒體清冊</div>
      <div>點右上角「匯入清冊」，或直接把 Video Library Organizer 產生的 Excel 拖曳到此視窗。</div>
      <p><button class="btn primary" onclick="document.getElementById('fileInput').click()">選擇 Excel 檔案</button></p></div>`;
  } else if (!list.length) {
    empty.hidden = false; $('#grid').hidden = $('#list').hidden = true;
    empty.innerHTML = `<div><div class="big">沒有符合條件的媒體</div><button class="btn" id="clearAll">清除所有篩選</button></div>`;
    $('#clearAll').onclick = clearFilters;
  } else empty.hidden = true;
  if (S.view === 'grid') renderGrid(list); else renderList(list);
  renderBulk();
}

function renderActiveFilters() {
  const f = S.f, parts = [];
  if (f.q) parts.push(['q', `搜尋：${f.q}`]);
  if (f.folder) parts.push(['folder', `📁 ${f.folder}`]);
  for (const v of f.status) parts.push(['status:' + v, v]);
  for (const v of f.type) parts.push(['type:' + v, v]);
  for (const v of f.kw) parts.push(['kw:' + v, '#' + v]);
  if (f.picked) parts.push(['picked', '★ 已挑選']);
  if (f.marked) parts.push(['marked', '有標記點']);
  if (f.avail) parts.push(['avail', f.avail === 'yes' ? '可存取' : '無法存取']);
  $('#activeFilters').innerHTML = parts.map(([k, l]) => `<span class="chip" data-rm="${esc(k)}" title="移除條件">${esc(l)} ✕</span>`).join(' ')
    + (parts.length > 1 ? ' <button class="link" id="clearF">全部清除</button>' : '');
  const c = $('#clearF'); if (c) c.onclick = clearFilters;
}
$('#activeFilters').addEventListener('click', e => {
  const k = e.target.closest('[data-rm]')?.dataset.rm; if (!k) return;
  const f = S.f;
  if (k === 'q') { f.q = ''; $('#q').value = ''; }
  else if (k === 'folder') f.folder = '';
  else if (k === 'picked') f.picked = false;
  else if (k === 'marked') f.marked = false;
  else if (k === 'avail') f.avail = '';
  else { const [t, ...v] = k.split(':'); f[t].delete(v.join(':')); }
  refresh();
});
function clearFilters() {
  Object.assign(S.f, { q: '', folder: '', picked: false, marked: false, avail: '' });
  S.f.status.clear(); S.f.type.clear(); S.f.kw.clear(); $('#q').value = '';
  refresh();
}

function thumbHTML(m, cls = '') {
  if (!m.available) return `<div class="ph">⚠ 檔案無法存取<br><span style="opacity:.7">請檢查路徑對應設定</span></div>`;
  return `<img loading="lazy" src="/api/thumb/${m.id}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'ph',textContent:'無法產生縮圖'}))">
    <div class="scrub"></div><div class="scrubbar"></div>`;
}
function stars(n) { return n ? `<span class="stars-mini">${'★'.repeat(n)}</span>` : ''; }

function renderGrid(list) {
  const toks = qTokens();
  $('#grid').innerHTML = list.map(m => `
    <article class="card ${S.sel.has(m.id) ? 'sel' : ''}" data-id="${m.id}">
      <div class="thumb">${thumbHTML(m)}
        ${m.duration ? `<span class="badge-dur">${fmtDur(m.duration)}</span>` : ''}
        ${m.status ? `<span class="badge-status ${statusClass(m.status)}">${esc(m.status)}</span>` : ''}
      </div>
      ${m.picked ? '<span class="pickstar" title="已挑選">★</span>' : ''}
      <span class="chk" data-chk title="選取">✓</span>
      <div class="body">
        <div class="name"><span title="${esc(m.filename)}">${hl(m.filename, toks)}</span>${stars(m.rating)}</div>
        <div class="folder" title="${esc(m.full_path)}">📁 ${esc(m._folder || '（根目錄）')}</div>
        <div class="desc">${hl(m.description || '', toks) || '<span class="muted">（無內容描述）</span>'}</div>
        <div class="kw">${m._kw.slice(0, 8).map(k => `<span class="chip ${S.f.kw.has(k) ? 'on' : ''}" data-kw="${esc(k)}">${hl(k, toks)}</span>`).join('')}</div>
        <div class="meta">
          ${m.width ? `<span>${m.width}×${m.height}</span>` : ''}${m.fps ? `<span>${m.fps}fps</span>` : ''}
          ${m.size ? `<span>${fmtSize(m.size)}</span>` : ''}${m.marker_count ? `<span>🔖 ${m.marker_count}</span>` : ''}
          ${m.note ? '<span title="有備註">📝</span>' : ''}
        </div>
      </div>
    </article>`).join('');
}

const LIST_EDITABLE = new Set(['status', 'filename', 'media_type', 'description', 'highlights', 'keywords', 'shot_time',
  'processed_time', 'md_path', 'backup_path', 'error', 'note', 'full_path']);
function renderList(list) {
  const toks = qTokens();
  const extraKeys = [...new Set(list.flatMap(m => Object.keys(m.extra || {})))];
  const cols = [
    ['', '', m => `<input type="checkbox" data-chk ${S.sel.has(m.id) ? 'checked' : ''}>`],
    ['', '', m => m.available ? `<img class="tthumb" loading="lazy" src="/api/thumb/${m.id}" alt="">` : '<div class="tthumb"></div>'],
    ['picked', '★', m => m.picked ? '<span style="color:var(--star)">★</span>' : '', 'nowrap'],
    ['status', LABEL.status, m => m.status ? `<span class="badge-status ${statusClass(m.status)}" style="position:static">${esc(m.status)}</span>` : '', 'nowrap'],
    ['filename', LABEL.filename, m => `<strong>${hl(m.filename, toks)}</strong>`, 'nowrap'],
    ['_folder', '資料夾', m => esc(m._folder), 'nowrap'],
    ['media_type', LABEL.media_type, m => esc(m.media_type), 'nowrap'],
    ['duration', '時長', m => fmtDur(m.duration), 'nowrap'],
    ['width', '解析度', m => m.width ? `${m.width}×${m.height}` : '', 'nowrap'],
    ['rating', '評等', m => stars(m.rating), 'nowrap'],
    ['description', LABEL.description, m => hl(m.description, toks), 'wrap'],
    ['highlights', LABEL.highlights, m => hl(m.highlights, toks), 'wrap'],
    ['keywords', LABEL.keywords, m => hl(m.keywords, toks), 'wrap'],
    ['shot_time', LABEL.shot_time, m => esc(fmtDate(m.shot_time)), 'nowrap'],
    ['processed_time', LABEL.processed_time, m => esc(fmtDate(m.processed_time)), 'nowrap'],
    ['size', '大小', m => fmtSize(m.size), 'nowrap'],
    ['md_path', LABEL.md_path, m => hl(m.md_path, toks), 'path'],
    ['backup_path', LABEL.backup_path, m => hl(m.backup_path, toks), 'path'],
    ['error', LABEL.error, m => hl(m.error, toks), 'wrap'],
    ['note', '備註', m => hl(m.note, toks), 'wrap'],
    ...extraKeys.map(k => ['', k, m => hl((m.extra || {})[k], toks), 'wrap', 'x:' + k]),
    ['full_path', LABEL.full_path, m => hl(m.full_path, toks), 'path'],
  ];
  const allSel = list.length && list.every(m => S.sel.has(m.id));
  $('#list').innerHTML = `<table class="tbl"><thead><tr>${cols.map(([k, l], i) =>
    i === 0 ? `<th><input type="checkbox" id="selAll" ${allSel ? 'checked' : ''}></th>` :
      `<th ${k ? `data-sort="${k}"` : ''} class="${S.sort === k ? 'sorted' : ''}">${esc(l)}${S.sort === k ? (S.dir > 0 ? ' ↑' : ' ↓') : ''}</th>`).join('')}</tr></thead>
    <tbody>${list.map(m => `<tr data-id="${m.id}" class="${S.sel.has(m.id) ? 'sel' : ''}">${cols.map(c => {
      const f = c[4] || (LIST_EDITABLE.has(c[0]) ? c[0] : '');
      return `<td class="${c[3] || ''}${f ? ' editable' : ''}" ${f ? `data-f="${esc(f)}" title="雙擊編輯"` : ''}>${c[2](m) ?? ''}</td>`;
    }).join('')}</tr>`).join('')}</tbody></table>`;
  $('#selAll').onchange = e => { list.forEach(m => e.target.checked ? S.sel.add(m.id) : S.sel.delete(m.id)); render(); };
}

$('#list').addEventListener('click', e => {
  const th = e.target.closest('th[data-sort]');
  if (th) {
    const k = th.dataset.sort;
    if (S.sort === k) S.dir = -S.dir; else { S.sort = k; S.dir = 1; }
    LS.set('sort', S.sort); LS.set('dir', S.dir);
    if ([...$('#sort').options].some(o => o.value === k)) $('#sort').value = k;
    render(); return;
  }
  const tr = e.target.closest('tr[data-id]'); if (!tr) return;
  const id = +tr.dataset.id;
  if (e.target.closest('[data-chk]')) { toggleSet(S.sel, id); render(); return; }
  if (e.ctrlKey || e.metaKey) { toggleSet(S.sel, id); render(); return; }
  if (e.target.closest('.cell-ed')) return;
  clearTimeout(S.clickTimer);
  S.clickTimer = setTimeout(() => openViewer(id), e.target.closest('td.editable') ? 260 : 0);
});
$('#list').addEventListener('dblclick', e => {
  const td = e.target.closest('td[data-f]'); if (!td || td.querySelector('.cell-ed')) return;
  clearTimeout(S.clickTimer);
  const id = +td.parentElement.dataset.id, key = td.dataset.f, m = S.byId.get(id);
  const v = getVal(m, key) ?? '';
  const long = LONG_FIELDS.has(key) || TAG_FIELDS[key] || String(v).length > 40 || key === 'note';
  td.innerHTML = long ? `<textarea class="cell-ed" rows="4"></textarea>` : `<input class="cell-ed" ${key === 'status' ? 'list="statusList"' : ''}>`;
  const ed = td.firstChild; ed.value = v; ed.focus(); ed.select();
  let done = false;
  const finish = async save => {
    if (done) return; done = true;
    if (save && ed.value !== String(v)) {
      try { await saveFields(id, { [key]: ed.value }); toast('已儲存：' + fieldLabel(key)); } catch { }
    }
    refresh();
  };
  ed.addEventListener('keydown', ev => {
    ev.stopPropagation();
    if (ev.key === 'Escape') finish(false);
    else if (ev.key === 'Enter' && (ed.tagName === 'INPUT' || ev.ctrlKey)) { ev.preventDefault(); finish(true); }
  });
  ed.addEventListener('blur', () => finish(true));
});

$('#grid').addEventListener('click', e => {
  const card = e.target.closest('.card'); if (!card) return;
  const id = +card.dataset.id;
  const kw = e.target.closest('[data-kw]');
  if (kw) { e.stopPropagation(); toggleSet(S.f.kw, kw.dataset.kw); refresh(); return; }
  if (e.target.closest('[data-chk]') || e.ctrlKey || e.metaKey) {
    toggleSet(S.sel, id); card.classList.toggle('sel', S.sel.has(id)); renderBulk(); return;
  }
  if (e.shiftKey && S.lastClick != null) {
    const ids = S.filtered.map(m => m.id), a = ids.indexOf(S.lastClick), b = ids.indexOf(id);
    if (a >= 0 && b >= 0) { ids.slice(Math.min(a, b), Math.max(a, b) + 1).forEach(i => S.sel.add(i)); render(); return; }
  }
  S.lastClick = id;
  openViewer(id);
});

/* 縮圖滑鼠移動預覽（預覽格） */
const spriteCache = new Map();
function loadSprite(id) {
  if (!spriteCache.has(id)) spriteCache.set(id, new Promise((res, rej) => {
    const im = new Image(); im.onload = () => res(im.src); im.onerror = rej; im.src = '/api/sprite/' + id;
  }));
  return spriteCache.get(id);
}
$('#grid').addEventListener('mouseover', e => {
  const th = e.target.closest('.thumb'); if (!th || th._sp) return;
  const card = th.closest('.card'), m = S.byId.get(+card.dataset.id);
  if (!m?.available) return;
  th._sp = true;
  const sc = $('.scrub', th); if (!sc) return;
  loadSprite(m.id).then(src => {
    sc.style.backgroundImage = `url("${src}")`;
    sc.style.backgroundSize = `${SPRITE_FRAMES * 100}% 100%`;
    sc.classList.add('ready');
  }).catch(() => { });
});
$('#grid').addEventListener('mousemove', e => {
  const th = e.target.closest('.thumb'); if (!th) return;
  const sc = $('.scrub.ready', th); if (!sc) return;
  const r = th.getBoundingClientRect(), x = Math.min(0.999, Math.max(0, (e.clientX - r.left) / r.width));
  const i = Math.floor(x * SPRITE_FRAMES);
  sc.style.backgroundPosition = `${(i / (SPRITE_FRAMES - 1)) * 100}% 0`;
  $('.scrubbar', th).style.width = (x * 100) + '%';
});

/* ---------------- bulk ---------------- */
function statusOptions() {
  return [...new Set([...DEFAULT_STATUSES, ...S.items.map(m => m.status).filter(Boolean)])];
}
function renderBulk() {
  const n = S.sel.size;
  $('#bulkbar').hidden = !n;
  $('#selCount').textContent = n;
  const bs = $('#bulkStatus');
  bs.innerHTML = '<option value="">設定狀態…</option>' + statusOptions().map(s => `<option>${esc(s)}</option>`).join('');
}
$('#bulkbar').addEventListener('click', async e => {
  const a = e.target.closest('[data-bulk]')?.dataset.bulk; if (!a) return;
  const ids = [...S.sel];
  if (a === 'clear') { S.sel.clear(); render(); return; }
  if (a === 'export') { exportIds(ids); return; }
  if (a === 'play') { const list = S.filtered.filter(m => S.sel.has(m.id)); if (list.length) openViewer(list[0].id, list); return; }
  if (a === 'kwadd' || a === 'kwrm') {
    const kws = splitKw($('#bulkKw').value);
    if (!kws.length) { toast('請先輸入關鍵字'); $('#bulkKw').focus(); return; }
    const r = await api('/api/media/bulk_keywords', { method: 'POST', json: { ids, [a === 'kwadd' ? 'add' : 'remove']: kws } });
    toast(`${a === 'kwadd' ? '已加入' : '已移除'}「${kws.join('、')}」：${r.count} 筆有變更`);
    $('#bulkKw').value = ''; await load(); pollSync(true); return;
  }
  await api('/api/media/bulk', { method: 'POST', json: { ids, set: { picked: a === 'pick' ? 1 : 0 } } });
  ids.forEach(i => S.byId.get(i).picked = a === 'pick' ? 1 : 0);
  toast(a === 'pick' ? `已將 ${ids.length} 筆加入挑選` : `已將 ${ids.length} 筆移出挑選`);
  refresh();
});
$('#bulkStatus').addEventListener('change', async e => {
  const v = e.target.value; if (!v) return;
  const ids = [...S.sel];
  await api('/api/media/bulk', { method: 'POST', json: { ids, set: { status: v } } });
  toast(`已將 ${ids.length} 筆設為「${v}」`); await load(); pollSync(true);
});

function exportIds(ids) {
  const a = document.createElement('a');
  a.href = '/api/export' + (ids && ids.length ? '?ids=' + ids.join(',') : '');
  a.click();
}
$('#btnExport').onclick = () => {
  const all = S.filtered.length === S.items.length;
  exportIds(all ? null : S.filtered.map(m => m.id));
  toast(`匯出 ${S.filtered.length} 筆（含挑選、評等、備註、標記點）`);
};

/* ---------------- toolbar ---------------- */
$('#q').addEventListener('input', debounce(e => { S.f.q = e.target.value.trim(); refresh(); }, 150));
$('#sort').onchange = e => { S.sort = e.target.value; LS.set('sort', S.sort); render(); };
$('#sortDir').onclick = () => { S.dir = -S.dir; LS.set('dir', S.dir); render(); };
$$('.toolbar .seg [data-view]').forEach(b => b.onclick = () => { S.view = b.dataset.view; LS.set('view', S.view); render(); });
const cs = $('#cardSize');
cs.value = LS.get('card', 260);
document.documentElement.style.setProperty('--card', cs.value + 'px');
cs.oninput = () => { document.documentElement.style.setProperty('--card', cs.value + 'px'); LS.set('card', +cs.value); };

/* ---------------- import ---------------- */
$('#btnImport').onclick = () => { $('#importDlg').showModal(); $('#impPath').focus(); };
$('#impFileBtn').onclick = () => { $('#importDlg').close(); $('#fileInput').click(); };
$('#impPathBtn').onclick = importPath;
$('#impPath').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); importPath(); } });
async function importPath() {
  const p = $('#impPath').value.trim().replace(/^"|"$/g, '');
  if (!p) { $('#impPath').focus(); return; }
  toast('匯入中…', 60000);
  try {
    const r = await api('/api/import_path', { method: 'POST', json: { path: p } });
    $('#importDlg').close();
    toast(`匯入完成：${r.rows} 筆（新增 ${r.inserted}、更新 ${r.updated}）。修改會即時寫回此 Excel`, 5000);
    await load(); pollSync(); setTimeout(load, 4000);
  } catch (err) { toast('匯入失敗：' + err.message, 5000); }
}
$('#fileInput').onchange = e => { const f = e.target.files[0]; if (f) importFile(f); e.target.value = ''; };
async function importFile(file) {
  if (!/\.xls[xm]$/i.test(file.name)) { toast('請選擇 .xlsx 格式的媒體清冊'); return; }
  toast(`匯入中：${file.name}…`, 60000);
  const fd = new FormData(); fd.append('file', file);
  try {
    const r = await api('/api/import', { method: 'POST', body: fd });
    toast(`匯入完成：共 ${r.rows} 筆（新增 ${r.inserted}、更新 ${r.updated}）。` +
      (r.source_path ? `已自動連結原始檔，修改會即時寫回：${r.source_path}` : '找不到原始檔位置，請在左側「已匯入清冊」按「連結原始檔」以啟用寫回 Excel'), 7000);
    pollSync();
    await load();
    setTimeout(load, 4000); // 背景讀取技術資訊後再更新一次
  } catch (err) { toast('匯入失敗：' + err.message, 5000); }
}
let dragDepth = 0;
window.addEventListener('dragenter', e => { if (e.dataTransfer?.types.includes('Files')) { dragDepth++; $('#dropzone').hidden = false; } });
window.addEventListener('dragleave', () => { if (--dragDepth <= 0) { dragDepth = 0; $('#dropzone').hidden = true; } });
window.addEventListener('dragover', e => e.preventDefault());
window.addEventListener('drop', e => {
  e.preventDefault(); dragDepth = 0; $('#dropzone').hidden = true;
  const f = e.dataTransfer.files[0]; if (f) importFile(f);
});

/* ---------------- settings ---------------- */
$('#btnSettings').onclick = openSettings;
async function openSettings() {
  const [cfg, st] = await Promise.all([api('/api/config'), api('/api/status')]);
  const rows = $('#mapRows'); rows.innerHTML = '';
  (cfg.path_maps.length ? cfg.path_maps : [{ from: '', to: '' }]).forEach(addMapRow);
  const sample = S.items.find(m => !m.available) || S.items[0];
  $('#mapHint').innerHTML = sample ? `清冊中的路徑範例：<br><code>${esc(sample.full_path)}</code>` +
    (S.root ? `<br>共同上層目錄：<code>${esc(S.root)}</code> <button type="button" class="link" id="useRoot">用此作為「來源」</button>` : '') : '';
  const ur = $('#useRoot');
  if (ur) ur.onclick = () => { const r = $$('.map-row', rows).find(r => !$('.from', r).value) || addMapRow({ from: '', to: '' }); $('.from', r).value = S.root + '\\'; };
  $('#cfgSync').checked = cfg.sync_excel !== false;
  $('#cfgSyncUser').checked = !!cfg.sync_user_fields;
  $('#cfgSyncCom').checked = cfg.sync_via_excel_app !== false;
  $('#sysInfo').innerHTML = `<div class="k">ffmpeg</div><div class="v">${st.tools.ffmpeg ? '✔ 已找到' : '✖ 找不到（無法產生縮圖、預覽與代理檔）'}</div>
    <div class="k">ffprobe</div><div class="v">${st.tools.ffprobe ? '✔ 已找到' : '✖ 找不到（無法讀取時長、解析度）'}</div>
    <div class="k">背景掃描</div><div class="v">${st.probing ? '進行中…' : '閒置'}</div>
    <div class="k">媒體數量</div><div class="v">${S.items.length} 筆，其中 ${S.items.filter(m => !m.available).length} 筆無法存取</div>`;
  $('#settingsDlg').showModal();
}
function addMapRow(m) {
  const d = document.createElement('div'); d.className = 'map-row';
  d.innerHTML = `<input class="from" placeholder="來源前綴，例如 \\\\192.168.1.10\\" value="${esc(m.from)}"><span>→</span>
    <input class="to" placeholder="本機路徑，例如 Z:\\" value="${esc(m.to)}"><button type="button" class="btn sm ghost" title="刪除">✕</button>`;
  $('button', d).onclick = () => d.remove();
  $('#mapRows').appendChild(d); return d;
}
$('#addMap').onclick = () => addMapRow({ from: '', to: '' });
$('#saveSettings').onclick = async () => {
  const maps = $$('#mapRows .map-row').map(r => ({ from: $('.from', r).value, to: $('.to', r).value }));
  await api('/api/config', { method: 'PUT', json: {
    path_maps: maps, sync_excel: $('#cfgSync').checked, sync_user_fields: $('#cfgSyncUser').checked,
    sync_via_excel_app: $('#cfgSyncCom').checked } });
  pollSync(true);
  $('#settingsDlg').close();
  const d = await load();
  const ok = d.items.filter(m => m.available).length;
  toast(`已儲存。${ok} / ${d.items.length} 筆檔案可存取`, 4000);
  setTimeout(load, 3000);
};
$('#btnRescan').onclick = async () => { await api('/api/rescan', { method: 'POST' }); toast('已開始重新掃描'); setTimeout(load, 3000); };
$('#kwMore').onclick = () => { renderKwAll(); $('#kwDlg').showModal(); $('#kwFilter').focus(); };
$('#kwFilter').oninput = renderKwAll;
function renderKwAll() {
  const f = $('#kwFilter').value.trim().toLowerCase();
  const all = [...(S.kwCounts || [])].filter(([k]) => !f || k.toLowerCase().includes(f)).sort((a, b) => b[1] - a[1]);
  $('#kwAll').innerHTML = all.map(([k, n]) => `<span class="chip kwm ${S.f.kw.has(k) ? 'on' : ''}" data-kw="${esc(k)}" title="點擊篩選">${esc(k)}<span class="n">${n}</span>
    <button type="button" data-kwren="${esc(k)}" title="重新命名／合併（套用到所有媒體）">✎</button><button type="button" data-kwdel="${esc(k)}" title="從所有媒體刪除此關鍵字">✕</button></span>`).join('') || '<span class="muted">無</span>';
}
$('#kwAll').addEventListener('click', async e => {
  const ren = e.target.closest('[data-kwren]'), del = e.target.closest('[data-kwdel]');
  if (ren || del) {
    e.preventDefault(); e.stopPropagation();
    const k = (ren || del).dataset[ren ? 'kwren' : 'kwdel'];
    const n = S.items.filter(m => m._kw.includes(k)).length;
    let to = '';
    if (ren) {
      to = (prompt(`將關鍵字「${k}」重新命名為（輸入已存在的關鍵字即可合併）：
共 ${n} 筆媒體會一併修改並寫回 Excel`, k) || '').trim();
      if (!to || to === k) return;
    } else if (!confirm(`確定要從 ${n} 筆媒體中刪除關鍵字「${k}」？
（會寫回 Excel，可在各媒體的「修改紀錄」還原）`)) return;
    try {
      const r = await api('/api/keywords', { method: 'POST', json: { from: k, to } });
      if (S.f.kw.delete(k) && to) S.f.kw.add(to);
      toast(ren ? `已將「${k}」改為「${to}」：${r.count} 筆` : `已刪除「${k}」：${r.count} 筆`);
      await load(); renderKwAll(); pollSync(true);
    } catch (err) { toast(err.message); }
    return;
  }
  const k = e.target.closest('[data-kw]')?.dataset.kw; if (!k) return;
  toggleSet(S.f.kw, k); refresh(); renderKwAll();
});

/* =========================================================
   播放器
   ========================================================= */
const V = $('#video');
const P = {
  list: [], idx: -1, cur: null, fps: 29.97, tcMode: LS.get('tcMode', 'tc'),
  A: null, B: null, auto: LS.get('autoNext', false), shuttle: 0, shuttleTimer: null, useProxy: false,
};
V.volume = LS.get('vol', 1); V.muted = LS.get('muted', false);

function openViewer(id, list) {
  P.list = list || S.filtered.slice();
  P.idx = P.list.findIndex(m => m.id === id);
  if (P.idx < 0) { const m = S.byId.get(id); if (!m) return; P.list = [m]; P.idx = 0; }
  $('#viewer').hidden = false;
  document.body.style.overflow = 'hidden';
  renderPlaylist();
  loadCurrent();
}
function closeViewer() {
  savePos();
  stopShuttle();
  V.pause(); V.removeAttribute('src'); V.load();
  if (document.fullscreenElement) document.exitFullscreen();
  $('#viewer').hidden = true;
  if (location.hash) history.replaceState(null, '', location.pathname);
  refresh();
}
$('#vClose').onclick = closeViewer;

async function loadCurrent(autoplay = false) {
  const m0 = P.list[P.idx]; if (!m0) return;
  savePos();
  stopShuttle();
  P.A = P.B = null; updateAB();
  history.replaceState(null, '', '#m=' + m0.id);
  $('#vName').textContent = m0.filename;
  $('#vDir').textContent = m0.full_path;
  $('#vPos').textContent = `${P.idx + 1} / ${P.list.length}`;
  $('#vPrev').disabled = P.idx <= 0; $('#vNext').disabled = P.idx >= P.list.length - 1;
  $$('.pl-item').forEach((el, i) => el.classList.toggle('cur', i === P.idx));
  $('.pl-item.cur')?.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
  let m;
  try { m = await api('/api/media/' + m0.id); } catch (e) { toast(e.message); return; }
  if (P.list[P.idx]?.id !== m.id) return; // 已切換
  Object.assign(S.byId.get(m.id) || {}, { ...m, marker_count: m.markers.length });
  P.cur = m;
  P.editing.clear();
  P.fps = m.fps || 29.97;
  renderDetails();
  P.sprite = null;
  if (m.available) loadSprite(m.id).then(src => { if (P.cur?.id === m.id) P.sprite = src; }).catch(() => { });
  setSource(autoplay);
}

function setSource(autoplay) {
  const m = P.cur;
  hideMsg();
  V.removeAttribute('src');
  if (!m.available && !m.has_proxy) {
    V.load();
    showMsg(`<h3>⚠ 找不到原始檔案</h3><p>${esc(m.full_path)}</p>
      <p class="muted">若檔案位於網路磁碟，請確認可連線，或在「設定 → 路徑對應」中把此路徑換算到本機可讀取的位置。</p>
      <button class="btn primary" id="msgSettings">開啟設定</button>`);
    $('#msgSettings').onclick = openSettings;
    return;
  }
  // 已知瀏覽器不支援的編碼（如 4:2:2 10-bit）常會「無錯誤但畫面全黑」，因此事先提示產生代理檔
  if (m.available && !m.playable && !m.has_proxy && P.forceOriginal !== m.id) {
    V.load();
    const codec = [m.vcodec, m.vprofile, m.pix_fmt].filter(Boolean).join(' / ');
    showMsg(`<h3>此檔案的編碼瀏覽器無法正常顯示</h3>
      <p>${esc(m.filename)}<br>編碼：${esc(codec)}</p>
      <p class="muted">產生一份 H.264 代理檔供瀏覽檢視（原始檔不受影響，產生後會保留快取）。</p>
      <button class="btn primary" id="msgProxy">產生代理檔並播放</button>
      <button class="btn" id="msgForce">仍嘗試播放原始檔</button>
      <a class="btn" href="/api/download/${m.id}">下載原始檔</a>`);
    $('#msgProxy').onclick = () => makeProxy(m.id);
    $('#msgForce').onclick = () => { P.forceOriginal = m.id; setSource(true); };
    return;
  }
  P.useProxy = m.has_proxy && (!m.playable || !m.available || P.preferProxy);
  V.src = `/api/stream/${m.id}${P.useProxy ? '?proxy=1' : ''}`;
  V.playbackRate = +$('#cRate').value;
  V.load();
  const resume = LS.get('pos.' + m.id, 0);
  V.addEventListener('loadedmetadata', function onMeta() {
    V.removeEventListener('loadedmetadata', onMeta);
    if (resume > 3 && resume < V.duration - 3) { V.currentTime = resume; osd('從 ' + fmtClock(resume).slice(0, 8) + ' 繼續播放'); }
    if (autoplay || P.auto && P.autoStarted) V.play().catch(() => { });
    renderSeekMarkers();
  });
  if (autoplay) V.play().catch(() => { });
}

V.addEventListener('error', () => {
  if (!P.cur || !V.getAttribute('src')) return;
  const m = P.cur;
  const codec = [m.vcodec, m.vprofile, m.pix_fmt].filter(Boolean).join(' / ');
  if (P.useProxy) { showMsg(`<h3>代理檔播放失敗</h3><p>${esc(m.filename)}</p>`); return; }
  showMsg(`<h3>瀏覽器無法直接播放此檔案</h3>
    <p>${esc(m.filename)}${codec ? `<br>編碼：${esc(codec)}` : ''}</p>
    <p class="muted">可產生一份 H.264 / ${'720p'} 代理檔供瀏覽檢視（原始檔不受影響，完成後會保留快取）。</p>
    <button class="btn primary" id="msgProxy">產生代理檔</button>
    <a class="btn" href="/api/download/${m.id}">下載原始檔</a>`);
  $('#msgProxy').onclick = () => makeProxy(m.id);
});

async function makeProxy(id) {
  try { await api('/api/proxy/' + id, { method: 'POST' }); } catch (e) { toast(e.message); return; }
  showMsg(`<h3>正在產生代理檔…</h3><div class="progress"><div id="pxBar"></div></div><p id="pxTxt">0%</p>`);
  const tick = async () => {
    if (P.cur?.id !== id) return;
    const s = await api('/api/proxy/' + id);
    if (s.state === 'done') {
      P.cur.has_proxy = true; S.byId.get(id).has_proxy = true; P.preferProxy = true;
      setSource(true); renderTech(); return;
    }
    if (s.state === 'error') { showMsg(`<h3>代理檔產生失敗</h3><p>${esc(s.msg || '')}</p>`); return; }
    const pct = Math.round((s.progress || 0) * 100);
    const bar = $('#pxBar'); if (bar) bar.style.width = pct + '%';
    const t = $('#pxTxt'); if (t) t.textContent = pct + '%';
    setTimeout(tick, 1000);
  };
  tick();
}

function showMsg(html) { const el = $('#stageMsg'); el.innerHTML = `<div class="box">${html}</div>`; el.hidden = false; }
function hideMsg() { $('#stageMsg').hidden = true; }

function savePos() {
  if (!P.cur || !V.duration || isNaN(V.duration)) return;
  const t = V.currentTime;
  if (t > 3 && t < V.duration - 3) LS.set('pos.' + P.cur.id, Math.round(t * 10) / 10);
  else { try { localStorage.removeItem('vl.pos.' + P.cur.id); } catch { } }
}
setInterval(() => { if (!V.paused) savePos(); }, 5000);

function go(delta) {
  const n = P.idx + delta;
  if (n < 0 || n >= P.list.length) { osd(delta > 0 ? '已是最後一部' : '已是第一部'); return; }
  const wasPlaying = !V.paused;
  P.idx = n; loadCurrent(wasPlaying);
}
$('#vPrev').onclick = $('#cPrev').onclick = () => go(-1);
$('#vNext').onclick = $('#cNext').onclick = () => go(1);

function renderPlaylist() {
  $('#playlist').innerHTML = P.list.map((m, i) => `
    <div class="pl-item ${i === P.idx ? 'cur' : ''}" data-i="${i}" title="${esc(m.filename)}">
      <div class="im" style="${m.available ? `background-image:url('/api/thumb/${m.id}')` : ''}">${m.duration ? `<span class="badge-dur">${fmtDur(m.duration)}</span>` : ''}</div>
      <div class="nm">${m.picked ? '★ ' : ''}${esc(m.filename)}</div>
    </div>`).join('');
}
$('#playlist').addEventListener('click', e => {
  const it = e.target.closest('.pl-item'); if (!it) return;
  P.idx = +it.dataset.i; loadCurrent(!V.paused || true);
});

/* ---- 播放控制 ---- */
function togglePlay() {
  if (!V.getAttribute('src')) return;
  stopShuttle();
  if (V.paused || V.ended) { V.playbackRate = +$('#cRate').value; V.play().catch(e => toast('無法播放：' + e.message)); }
  else V.pause();
}
function flashBig() { const b = $('#bigPlay'); b.innerHTML = V.paused ? '<svg viewBox="0 0 24 24" width="56" height="56"><path d="M6 5h4v14H6zm8 0h4v14h-4z" fill="currentColor"/></svg>' : '<svg viewBox="0 0 24 24" width="56" height="56"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>'; b.classList.add('show'); setTimeout(() => b.classList.remove('show'), 350); }
$('#cPlay').onclick = togglePlay;
V.addEventListener('click', () => { togglePlay(); flashBig(); });
V.addEventListener('dblclick', toggleFull);
V.addEventListener('play', () => { P.autoStarted = true; updatePlayIcon(); });
V.addEventListener('pause', updatePlayIcon);
V.addEventListener('ended', () => {
  updatePlayIcon();
  if (P.cur) { try { localStorage.removeItem('vl.pos.' + P.cur.id); } catch { } }
  if (P.auto && !V.loop && P.idx < P.list.length - 1) { osd('自動播放下一部'); go(1); setTimeout(() => V.play().catch(() => { }), 300); }
});
function updatePlayIcon() {
  $('#playIcon').innerHTML = V.paused ? '<path d="M8 5v14l11-7z"/>' : '<path d="M6 5h4v14H6zm8 0h4v14h-4z"/>';
  $('#stage').classList.toggle('paused', V.paused);
  pokeUI();
}

function seekBy(d) { if (!V.duration) return; V.currentTime = Math.min(V.duration, Math.max(0, V.currentTime + d)); osd((d > 0 ? '+' : '') + d + ' 秒'); }
$('#cBack').onclick = () => seekBy(-5);
$('#cFwd').onclick = () => seekBy(5);
function stepFrame(n) {
  stopShuttle(); V.pause();
  V.currentTime = Math.min(V.duration || 0, Math.max(0, V.currentTime + n / P.fps));
  osd(n > 0 ? '下一格 ▶' : '◀ 上一格');
}
$('#cFrameB').onclick = () => stepFrame(-1);
$('#cFrameF').onclick = () => stepFrame(1);

$('#cRate').onchange = e => { stopShuttle(); V.playbackRate = +e.target.value; osd('速度 ' + e.target.value + '×'); };
V.addEventListener('ratechange', () => {
  const r = String(V.playbackRate);
  if ([...$('#cRate').options].some(o => o.value === r)) $('#cRate').value = r;
});

// J/K/L 變速：L 往前加速，J 倒轉（以逐步跳轉模擬）
const SHUTTLE = [1, 2, 4, 8];
function shuttle(dir) {
  if (!V.duration) return;
  if (dir > 0) {
    if (P.shuttle < 0) stopShuttle();
    const i = V.paused ? 0 : Math.min(SHUTTLE.length - 1, SHUTTLE.indexOf(V.playbackRate) + 1);
    V.playbackRate = SHUTTLE[Math.max(0, i)]; V.play(); P.shuttle = 0;
    osd('▶ ' + V.playbackRate + '×');
  } else {
    V.pause();
    const cur = P.shuttle < 0 ? -P.shuttle : 0;
    const i = cur ? Math.min(SHUTTLE.length - 1, SHUTTLE.indexOf(cur) + 1) : 0;
    P.shuttle = -SHUTTLE[i];
    clearInterval(P.shuttleTimer);
    P.shuttleTimer = setInterval(() => {
      const t = V.currentTime + P.shuttle * 0.1;
      if (t <= 0) { V.currentTime = 0; stopShuttle(); return; }
      V.currentTime = t;
    }, 100);
    osd('◀◀ ' + -P.shuttle + '×');
  }
}
function stopShuttle() { if (P.shuttleTimer) { clearInterval(P.shuttleTimer); P.shuttleTimer = null; } P.shuttle = 0; }

// 音量
function updateVol() {
  $('#cVol').value = V.muted ? 0 : V.volume;
  $('#volIcon').innerHTML = V.muted || V.volume === 0
    ? '<path d="M3 9v6h4l5 5V4L7 9z M16.5 9.5l5 5m0-5l-5 5" stroke="currentColor" stroke-width="2" fill="currentColor"/>'
    : V.volume < .5 ? '<path d="M3 9v6h4l5 5V4L7 9z M16 9a3 3 0 010 6z"/>' : '<path d="M3 9v6h4l5 5V4L7 9z M16 7a5 5 0 010 10z M16 3a9 9 0 010 18v-2a7 7 0 000-14z"/>';
  LS.set('vol', V.volume); LS.set('muted', V.muted);
}
V.addEventListener('volumechange', updateVol); updateVol();
$('#cVol').oninput = e => { V.volume = +e.target.value; V.muted = V.volume === 0; };
$('#cMute').onclick = () => { V.muted = !V.muted; osd(V.muted ? '靜音' : '音量 ' + Math.round(V.volume * 100) + '%'); };
function volBy(d) { V.muted = false; V.volume = Math.min(1, Math.max(0, Math.round((V.volume + d) * 100) / 100)); osd('音量 ' + Math.round(V.volume * 100) + '%'); }

// 時間顯示
function fmtT(t) { return P.tcMode === 'tc' ? fmtTC(t, P.fps) : fmtClock(t); }
$('#cTc').onclick = () => { P.tcMode = P.tcMode === 'tc' ? 'clock' : 'tc'; LS.set('tcMode', P.tcMode); $('#cTc').textContent = P.tcMode === 'tc' ? 'TC' : '秒'; updateTime(); renderMarks(); };
$('#cTc').textContent = P.tcMode === 'tc' ? 'TC' : '秒';
function updateTime() {
  const d = V.duration || 0, t = V.currentTime || 0;
  $('#tCur').textContent = fmtT(t);
  $('#tDur').textContent = fmtT(d);
  const pct = d ? t / d * 100 : 0;
  $('#seekProgress').style.width = pct + '%';
  $('#seekThumb').style.left = pct + '%';
  if (V.buffered.length && d) {
    let end = 0;
    for (let i = 0; i < V.buffered.length; i++) if (V.buffered.start(i) <= t + 0.5) end = Math.max(end, V.buffered.end(i));
    $('#seekBuffer').style.width = (end / d * 100) + '%';
  }
}
V.addEventListener('timeupdate', updateTime);
V.addEventListener('durationchange', () => { updateTime(); renderSeekMarkers(); updateAB(); });
V.addEventListener('seeked', updateTime);
V.addEventListener('progress', updateTime);

// A-B 區段循環（以 rAF 精準檢查）
function abLoop() {
  if (P.A != null && P.B != null && P.B > P.A && !V.paused && V.currentTime >= P.B) V.currentTime = P.A;
  requestAnimationFrame(abLoop);
}
requestAnimationFrame(abLoop);
function setA() { P.A = V.currentTime; if (P.B != null && P.B <= P.A) P.B = null; updateAB(); osd('A 點 ' + fmtT(P.A)); }
function setB() { if (P.A == null) P.A = 0; if (V.currentTime <= P.A) { osd('B 點必須在 A 點之後'); return; } P.B = V.currentTime; updateAB(); osd('B 點 ' + fmtT(P.B) + '（區段循環）'); V.currentTime = P.A; }
function clearAB() { P.A = P.B = null; updateAB(); osd('已清除 A-B 區段'); }
function updateAB() {
  const d = V.duration || 0, el = $('#seekAB');
  $('#cA').classList.toggle('on', P.A != null); $('#cB').classList.toggle('on', P.B != null);
  if (P.A == null || !d) { el.hidden = true; return; }
  el.hidden = false;
  el.style.left = (P.A / d * 100) + '%';
  el.style.width = (((P.B ?? P.A + d * 0.003) - P.A) / d * 100) + '%';
}
$('#cA').onclick = setA;
$('#cB').onclick = setB;
$('#cA').oncontextmenu = $('#cB').oncontextmenu = e => { e.preventDefault(); clearAB(); };

function toggleLoop() { V.loop = !V.loop; $('#cLoop').classList.toggle('on', V.loop); osd(V.loop ? '循環播放：開' : '循環播放：關'); }
$('#cLoop').onclick = toggleLoop;
$('#cAuto').classList.toggle('on', P.auto);
$('#cAuto').onclick = () => { P.auto = !P.auto; LS.set('autoNext', P.auto); $('#cAuto').classList.toggle('on', P.auto); osd(P.auto ? '自動播放下一部：開' : '自動播放下一部：關'); };

function toggleFull() {
  if (document.fullscreenElement) document.exitFullscreen();
  else $('#stage').requestFullscreen().catch(() => { });
}
$('#cFull').onclick = toggleFull;
async function togglePip() {
  try {
    if (document.pictureInPictureElement) await document.exitPictureInPicture();
    else await V.requestPictureInPicture();
  } catch (e) { toast('子母畫面無法使用：' + e.message); }
}
$('#cPip').onclick = togglePip;

function snapshot() {
  if (!V.videoWidth) return;
  const c = document.createElement('canvas'); c.width = V.videoWidth; c.height = V.videoHeight;
  c.getContext('2d').drawImage(V, 0, 0);
  c.toBlob(b => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(b);
    a.download = `${P.cur.filename.replace(/\.[^.]+$/, '')}_${fmtTC(V.currentTime, P.fps).replace(/:/g, '-')}.png`;
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    osd('已擷取畫面');
  }, 'image/png');
}
$('#cShot').onclick = snapshot;
$('#cHelp').onclick = () => $('#helpDlg').showModal();

// 進度條：拖曳 + 懸停預覽
const seek = $('#seekwrap');
function seekPos(e) { const r = seek.getBoundingClientRect(); return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)); }
seek.addEventListener('pointerdown', e => {
  if (e.target.closest('.seek-markers i')) return;
  if (!V.duration) return;
  seek.setPointerCapture(e.pointerId);
  P.dragging = true; V.currentTime = seekPos(e) * V.duration;
});
seek.addEventListener('pointermove', e => {
  const x = seekPos(e), d = V.duration || 0;
  if (P.dragging && d) V.currentTime = x * d;
  const h = $('#seekHover'); h.hidden = !d;
  const r = seek.getBoundingClientRect();
  h.style.left = Math.min(r.width - 82, Math.max(82, x * r.width)) + 'px';
  $('#shTime').textContent = fmtT(x * d);
  const img = $('#shImg');
  if (P.sprite) {
    const i = Math.min(SPRITE_FRAMES - 1, Math.floor(x * SPRITE_FRAMES));
    img.classList.remove('none');
    img.style.backgroundImage = `url("${P.sprite}")`;
    img.style.backgroundSize = `${SPRITE_FRAMES * 100}% 100%`;
    img.style.backgroundPosition = `${i / (SPRITE_FRAMES - 1) * 100}% 0`;
  } else img.classList.add('none');
});
seek.addEventListener('pointerup', () => P.dragging = false);
seek.addEventListener('pointerleave', () => { if (!P.dragging) $('#seekHover').hidden = true; });

// 控制列自動隱藏
let uiTimer;
function pokeUI() {
  const st = $('#stage'); st.classList.remove('hide-ui');
  clearTimeout(uiTimer);
  uiTimer = setTimeout(() => { if (!V.paused && !P.dragging) st.classList.add('hide-ui'); }, 2500);
}
$('#stage').addEventListener('mousemove', pokeUI);
$('#stage').addEventListener('mouseleave', () => { if (!V.paused) $('#stage').classList.add('hide-ui'); });

let osdTimer;
function osd(text) { const o = $('#osd'); o.textContent = text; o.classList.add('show'); clearTimeout(osdTimer); osdTimer = setTimeout(() => o.classList.remove('show'), 1100); }

/* ---- 鍵盤 ---- */
document.addEventListener('keydown', e => {
  const tag = (e.target.tagName || '').toLowerCase();
  const typing = tag === 'input' && !['range', 'checkbox'].includes(e.target.type) || tag === 'textarea' || tag === 'select' || e.target.isContentEditable;
  if ($('dialog[open]')) return;
  if ($('#viewer').hidden) {
    if (e.key === '/' && !typing) { e.preventDefault(); $('#q').focus(); }
    if (e.key === 'Escape' && typing) e.target.blur();
    return;
  }
  if (typing) { if (e.key === 'Escape') e.target.blur(); return; }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key;
  const handled = () => { e.preventDefault(); pokeUI(); };
  if (e.shiftKey && /^[!@#$%1-5]$/.test(k) || e.shiftKey && /^Digit[1-5]$/.test(e.code)) {
    const n = +e.code.replace('Digit', ''); if (n >= 1 && n <= 5) { setRating(P.cur.rating === n ? 0 : n); handled(); return; }
  }
  switch (k) {
    case ' ': case 'k': case 'K': togglePlay(); flashBig(); return handled();
    case 'j': case 'J': shuttle(-1); return handled();
    case 'l': case 'L': shuttle(1); return handled();
    case 'ArrowLeft': seekBy(e.shiftKey ? -1 : -5); return handled();
    case 'ArrowRight': seekBy(e.shiftKey ? 1 : 5); return handled();
    case 'ArrowUp': volBy(.05); return handled();
    case 'ArrowDown': volBy(-.05); return handled();
    case ',': case '<': stepFrame(-1); return handled();
    case '.': case '>': stepFrame(1); return handled();
    case 'm': case 'M': $('#cMute').click(); return handled();
    case 'f': case 'F': toggleFull(); return handled();
    case 'p': togglePip(); return handled();
    case 'P': go(-1); return handled();
    case 'N': go(1); return handled();
    case 'Home': V.currentTime = 0; return handled();
    case 'End': V.currentTime = Math.max(0, (V.duration || 0) - 0.05); return handled();
    case '[': setA(); return handled();
    case ']': setB(); return handled();
    case '\\': clearAB(); return handled();
    case 'r': case 'R': toggleLoop(); return handled();
    case 'x': case 'X': addMarker(); return handled();
    case 's': case 'S': snapshot(); return handled();
    case '*': togglePick(); return handled();
    case '?': $('#helpDlg').showModal(); return handled();
    case 'Escape':
      if (document.fullscreenElement) return;
      closeViewer(); return handled();
  }
  if (/^[0-9]$/.test(k) && V.duration) { V.currentTime = V.duration * (+k / 10); return handled(); }
});

/* ---- 詳細資料面板 ---- */
$$('.d-tabs [data-tab]').forEach(b => b.onclick = () => showTab(b.dataset.tab));
function showTab(t) {
  $$('.d-tabs [data-tab]').forEach(b => b.classList.toggle('on', b.dataset.tab === t));
  $$('.d-pane').forEach(p => p.hidden = p.dataset.pane !== t);
  if (t === 'md') loadMd();
  if (t === 'hist') loadHist();
  LS.set('tab', t);
}
showTab(LS.get('tab', 'info') === 'md' ? 'info' : LS.get('tab', 'info'));

function renderDetails() {
  const m = P.cur;
  $('#dPick').classList.toggle('on', !!m.picked);
  $('#dPick').textContent = m.picked ? '★ 已挑選' : '☆ 挑選';
  $('#dStars').innerHTML = [1, 2, 3, 4, 5].map(n => `<button data-r="${n}" class="${n <= (m.rating || 0) ? 'on' : ''}" title="${n} 星">★</button>`).join('');
  $('#dStatus').innerHTML = statusOptions().map(s => `<option ${s === m.status ? 'selected' : ''}>${esc(s)}</option>`).join('');
  $('#dDownload').href = '/api/download/' + m.id;
  $('#dDownload').toggleAttribute('hidden', !m.available);
  $('#dNote').value = m.note || '';
  $('#mdTabBtn').hidden = !m.md_path;
  if (!m.md_path && !$('#paneMd').hidden) showTab('info');
  $('#paneMd').dataset.loaded = '';
  if (!$('#paneMd').hidden) loadMd();

  renderInfo();
  renderTech();
  renderMarks();
  if (!$('#paneHist').hidden) loadHist();
}

function renderTech() {
  const m = P.cur; if (!m) return;
  const rows = [
    ['時長', m.duration ? `${fmtClock(m.duration)}（${m.duration.toFixed(2)} 秒）` : ''],
    ['解析度', m.width ? `${m.width} × ${m.height}` : ''],
    ['影格率', m.fps ? m.fps + ' fps' : ''],
    ['視訊編碼', [m.vcodec, m.vprofile].filter(Boolean).join(' / ')],
    ['像素格式', m.pix_fmt],
    ['音訊編碼', m.acodec],
    ['位元率', m.bitrate ? (m.bitrate / 1e6).toFixed(2) + ' Mbps' : ''],
    ['檔案大小', m.size ? `${fmtSize(m.size)}（${m.size.toLocaleString()} bytes）` : ''],
    ['檔案建立時間', fmtDate(m.creation_time)],
    ['瀏覽器相容', m.vcodec ? (m.playable ? '✔ 可直接播放' : '✖ 需使用代理檔') : '未知'],
    ['代理檔', m.has_proxy ? '✔ 已產生' : '—'],
    ['實際讀取路徑', m.resolved_path || '⚠ 無法存取'],
    ['資訊讀取時間', fmtDate(m.probed_at)],
  ];
  $('#paneTech').innerHTML = `<div class="kv">${rows.map(([k, v]) => `<div class="k">${k}</div><div class="v">${esc(v || '—')}</div>`).join('')}</div>
    <p style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap">
      ${m.available && !m.has_proxy ? `<button class="btn sm" id="tProxy">產生代理檔</button>` : ''}
      ${m.has_proxy && m.available ? `<button class="btn sm" id="tSwitch">切換為${P.useProxy ? '原始檔' : '代理檔'}</button>` : ''}
    </p>`;
  const tp = $('#tProxy'); if (tp) tp.onclick = () => makeProxy(m.id);
  const ts = $('#tSwitch'); if (ts) ts.onclick = () => { const t = V.currentTime; P.preferProxy = !P.useProxy; setSource(false); V.addEventListener('loadedmetadata', () => V.currentTime = t, { once: true }); renderTech(); };
}

function copyText(t) {
  navigator.clipboard?.writeText(t).then(() => toast('已複製'), () => {
    const ta = document.createElement('textarea'); ta.value = t; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); ta.remove(); toast('已複製');
  });
}
$('#dCopy').onclick = () => copyText(P.cur.full_path);

async function patchCur(body, msg) {
  const id = P.cur.id;
  try {
    await saveFields(id, body, msg);
    if ('picked' in body) renderPlaylist();
    if (P.cur?.id === id) { renderDetailsHeader(); if ('status' in body) refreshField('status'); }
  } catch { }
}
function renderDetailsHeader() {
  const m = P.cur;
  $('#dPick').classList.toggle('on', !!m.picked);
  $('#dPick').textContent = m.picked ? '★ 已挑選' : '☆ 挑選';
  $$('#dStars button').forEach(b => b.classList.toggle('on', +b.dataset.r <= (m.rating || 0)));
}
function togglePick() { patchCur({ picked: P.cur.picked ? 0 : 1 }, P.cur.picked ? '已移出挑選' : '★ 已加入挑選'); }
function setRating(n) { patchCur({ rating: n }, n ? '評等 ' + '★'.repeat(n) : '清除評等'); }
$('#dPick').onclick = togglePick;
$('#dStars').addEventListener('click', e => { const b = e.target.closest('[data-r]'); if (b) setRating(+b.dataset.r === P.cur.rating ? 0 : +b.dataset.r); });
$('#dStatus').onchange = e => patchCur({ status: e.target.value }, '狀態：' + e.target.value);
$('#dNote').addEventListener('input', debounce(() => patchCur({ note: $('#dNote').value }), 600));

/* ---- 清冊欄位：檢視 / 編輯（變更會即時寫回原始 Excel） ---- */
const LONG_FIELDS = new Set(['description', 'error']);
const TAG_FIELDS = { keywords: '、', highlights: '；' };
const USER_LABEL = { picked: '挑選', rating: '評等', note: '備註' };
const FIELD_HINT = {
  filename: '只修改清冊內容，不會重新命名實際檔案',
  full_path: '只修改清冊內容，不會搬移實際檔案；修改後面板會以新路徑尋找影片',
};
// Video Library Organizer 重新分析時，這些欄位會依實際檔案與分析紀錄重寫；
// 狀態、內容描述、重點、關鍵字、拍攝時間與自訂欄位的修改則會保留
const ORGANIZER_OWNED = new Set(['filename', 'full_path', 'media_type', 'processed_time', 'md_path', 'backup_path', 'error']);
const isOrganizerBatch = b => !!b && ['Markdown 路徑', '備份路徑', '錯誤原因'].every(h => (b.columns || []).includes(h));
function fieldHint(m, key) {
  const hints = FIELD_HINT[key] ? [FIELD_HINT[key]] : [];
  if (ORGANIZER_OWNED.has(key) && isOrganizerBatch(S.batches.find(b => b.id === m.batch_id)))
    hints.push('此欄位由 Video Library Organizer 產生，重新分析後會恢復原值');
  return hints.join('；');
}
P.editAll = LS.get('editAll', false);
P.editing = new Set();     // 個別開啟編輯的欄位
P.newFields = new Map();   // media_id -> Set(新增中的自訂欄位名稱)

const fieldLabel = f => LABEL[f] || USER_LABEL[f] || (f.startsWith('x:') ? f.slice(2) : f);
const getVal = (m, key) => key.startsWith('x:') ? (m.extra || {})[key.slice(2)] : m[key];
const splitFor = (k, v) => k === 'highlights' ? splitHl(v) : splitKw(v);

function fieldList(m) {
  const batch = S.batches.find(b => b.id === m.batch_id);
  const keyOf = Object.fromEntries(Object.entries(LABEL).map(([k, v]) => [v, k]));
  const order = batch?.columns?.length ? batch.columns : FIELD_ORDER.map(k => LABEL[k]);
  const out = [], seen = new Set();
  const push = (key, label) => { if (!seen.has(key)) { seen.add(key); out.push({ key, label }); } };
  for (const label of order) if (!Object.values(USER_LABEL).includes(label)) push(keyOf[label] || 'x:' + label, label);
  for (const k of FIELD_ORDER) push(k, LABEL[k]);
  for (const k of Object.keys(m.extra || {})) push('x:' + k, k);
  for (const k of P.newFields.get(m.id) || []) push('x:' + k, k);
  return out;
}

function renderInfo() {
  const m = P.cur; if (!m) return;
  const batch = S.batches.find(b => b.id === m.batch_id);
  $('#paneInfo').innerHTML = `
    <div class="info-head">
      <button class="btn sm ${P.editAll ? 'primary' : ''}" id="editAllBtn" title="開啟後所有欄位都可直接修改">${P.editAll ? '✓ 完成編輯' : '✎ 編輯所有欄位'}</button>
      ${P.editAll ? '<button class="btn sm" id="addFieldBtn" title="新增自訂欄位（會在 Excel 新增一欄）">＋ 新增欄位</button>' : ''}
      <span class="sync-inline" id="syncInline"></span>
    </div>
    ${fieldList(m).map(f => fieldHTML(m, f)).join('')}
    <div class="field"><div class="k">清冊來源</div><div class="v muted">${esc(batch?.source_name || '')}　第 ${m.row_no || '?'} 列</div></div>`;
  updateSyncInline();
}

function fieldHTML(m, f) {
  const v = getVal(m, f.key);
  const editing = P.editAll || P.editing.has(f.key);
  const copy = v && /path/.test(f.key) ? `<button class="link" data-copy="${esc(v)}">複製</button>` : '';
  const act = editing ? (P.editAll ? '' : '<button class="link" data-donef>完成</button>')
    : '<button class="link edit-btn" data-editf title="編輯此欄位">✎ 編輯</button>';
  return `<div class="field ${editing ? 'editing' : ''}" data-fkey="${esc(f.key)}">
    <div class="k"><span>${esc(f.label)}</span><span class="fk-act"><span class="saved">✓ 已儲存</span>${copy}${act}</span></div>
    ${editing ? editorHTML(f.key, v) : viewHTML(f.key, v)}
    ${editing && fieldHint(m, f.key) ? `<div class="hint">⚠ ${fieldHint(m, f.key)}</div>` : ''}
  </div>`;
}

function viewHTML(k, v) {
  const toks = qTokens();
  if (v == null || v === '') return '<div class="v empty">（空白）</div>';
  if (k === 'keywords') return `<div class="chips">${splitKw(v).map(x => `<span class="chip" data-kwgo="${esc(x)}" title="篩選此關鍵字">${hl(x, toks)}</span>`).join('')}</div>`;
  if (k === 'highlights') { const a = splitHl(v); return a.length > 1 ? `<ul class="hl">${a.map(x => `<li>${hl(x, toks)}</li>`).join('')}</ul>` : `<div class="v">${hl(v, toks)}</div>`; }
  if (k === 'status') return `<div class="v"><span class="badge-status ${statusClass(v)}" style="position:static">${esc(v)}</span></div>`;
  if (/path/.test(k)) return `<div class="v path">${hl(v, toks)}</div>`;
  if (/_time$/.test(k)) return `<div class="v" title="${esc(v)}">${esc(fmtDate(v))}</div>`;
  return `<div class="v">${hl(v, toks)}</div>`;
}

function editorHTML(k, v) {
  v = v ?? '';
  if (TAG_FIELDS[k]) return tagEditorHTML(k, splitFor(k, v));
  if (k === 'status') return `<input class="ed" data-ed list="statusList" value="${esc(v)}" data-orig="${esc(v)}" placeholder="例如 待確認、已確認">`;
  if (LONG_FIELDS.has(k) || String(v).length > 60)
    return `<textarea class="ed" data-ed rows="${Math.min(12, Math.max(3, Math.ceil(String(v).length / 26)))}" data-orig="${esc(v)}" placeholder="Ctrl+Enter 儲存，Esc 取消">${esc(v)}</textarea>`;
  return `<input class="ed" data-ed value="${esc(v)}" data-orig="${esc(v)}" ${/path/.test(k) ? 'spellcheck="false"' : ''} placeholder="Enter 儲存，Esc 取消">`;
}

function tagEditorHTML(k, list) {
  return `<div class="tags" data-tags="${k}">${list.map((t, i) =>
    `<span class="tag" data-i="${i}"><span class="tt" title="雙擊修改文字">${esc(t)}</span><button type="button" data-tagrm="${i}" title="刪除">✕</button></span>`).join('')}
    <input class="tag-in" placeholder="${k === 'keywords' ? '＋ 新增關鍵字（Enter）' : '＋ 新增重點（Enter）'}" ${k === 'keywords' ? 'list="kwList"' : ''}></div>`;
}

function refreshField(key, focusSel) {
  const m = P.cur; if (!m) return;
  const el = $(`#paneInfo [data-fkey="${CSS.escape(key)}"]`);
  const f = fieldList(m).find(x => x.key === key);
  if (el && f) {
    el.outerHTML = fieldHTML(m, f);
    if (focusSel) $(`#paneInfo [data-fkey="${CSS.escape(key)}"] ${focusSel}`)?.focus();
  }
  if (key === 'status') $('#dStatus').innerHTML = statusOptions().map(s => `<option ${s === m.status ? 'selected' : ''}>${esc(s)}</option>`).join('');
}
function flashSaved(key) {
  const s = $(`#paneInfo [data-fkey="${CSS.escape(key)}"] .saved`); if (!s) return;
  s.classList.add('show'); setTimeout(() => s.classList.remove('show'), 1600);
}

async function commitEd(el) {
  const key = el.closest('[data-fkey]')?.dataset.fkey; if (!key || !P.cur) return;
  if (el.value === el.dataset.orig) { if (!P.editAll && P.editing.has(key) && !el._keep) { /* 未修改 */ } return; }
  el.dataset.orig = el.value;
  try {
    await saveFields(P.cur.id, { [key]: el.value }, '已儲存：' + fieldLabel(key));
    if (!P.editAll) { P.editing.delete(key); refreshField(key); }
    else if (key === 'status') refreshField('status', '.ed');
    flashSaved(key);
    afterEdit();
  } catch { }
}
async function commitTags(key, list, refocus) {
  try {
    await saveFields(P.cur.id, { [key]: list });
    refreshField(key, refocus ? '.tag-in' : null);
    flashSaved(key); afterEdit();
  } catch { refreshField(key); }
}
function afterEdit() { if (!$('#paneHist').hidden) loadHist(); }
const curTags = key => $$(`#paneInfo [data-tags="${key}"] .tt`).map(x => x.textContent.trim()).filter(Boolean);

$('#paneInfo').addEventListener('click', async e => {
  const c = e.target.closest('[data-copy]');
  if (c) { copyText(c.dataset.copy); return; }
  if (e.target.closest('#editAllBtn')) {
    P.editAll = !P.editAll; LS.set('editAll', P.editAll); P.editing.clear(); renderInfo(); return;
  }
  if (e.target.closest('#addFieldBtn')) {
    const name = (prompt('新欄位名稱（儲存內容後，會在 Excel 清冊最右邊新增這一欄）') || '').trim();
    if (!name) return;
    if (fieldList(P.cur).some(f => f.label === name) || Object.values(USER_LABEL).includes(name)) { toast('已有同名欄位'); return; }
    if (!P.newFields.has(P.cur.id)) P.newFields.set(P.cur.id, new Set());
    P.newFields.get(P.cur.id).add(name);
    renderInfo(); $(`#paneInfo [data-fkey="${CSS.escape('x:' + name)}"] .ed`)?.focus(); return;
  }
  const field = e.target.closest('[data-fkey]'); if (!field) return;
  const key = field.dataset.fkey;
  if (e.target.closest('[data-editf]')) {
    P.editing.add(key); refreshField(key, TAG_FIELDS[key] ? '.tag-in' : '.ed'); return;
  }
  if (e.target.closest('[data-donef]')) { P.editing.delete(key); refreshField(key); return; }
  const rm = e.target.closest('[data-tagrm]');
  if (rm) { const list = curTags(key); list.splice(+rm.dataset.tagrm, 1); commitTags(key, list); return; }
  const k = e.target.closest('[data-kwgo]');
  if (k) { S.f.kw.add(k.dataset.kwgo); closeViewer(); refresh(); toast('已篩選關鍵字：' + k.dataset.kwgo); }
});
$('#paneInfo').addEventListener('dblclick', e => {
  const tt = e.target.closest('.tt'); if (!tt) return;
  tt.contentEditable = 'true'; tt.dataset.orig = tt.textContent; tt.focus();
  const r = document.createRange(); r.selectNodeContents(tt); const s = getSelection(); s.removeAllRanges(); s.addRange(r);
});
$('#paneInfo').addEventListener('keydown', e => {
  const tt = e.target.closest('.tt[contenteditable="true"]');
  if (tt) {
    if (e.key === 'Enter') { e.preventDefault(); tt.blur(); }
    else if (e.key === 'Escape') { tt.textContent = tt.dataset.orig; tt.blur(); }
    e.stopPropagation(); return;
  }
  const ti = e.target.closest('.tag-in');
  if (ti) {
    const key = ti.closest('[data-tags]').dataset.tags;
    if (e.key === 'Enter' || ['、', '，', ',', '；', ';'].includes(e.key)) {
      e.preventDefault();
      const add = splitFor(key, ti.value); if (!add.length) return;
      const list = curTags(key); for (const a of add) if (!list.includes(a)) list.push(a);
      ti.value = ''; commitTags(key, list, true);
    } else if (e.key === 'Backspace' && !ti.value) {
      const list = curTags(key); if (!list.length) return;
      e.preventDefault(); list.pop(); commitTags(key, list, true);
    } else if (e.key === 'Escape') { ti.value = ''; ti.blur(); }
    return;
  }
  const ed = e.target.closest('[data-ed]'); if (!ed) return;
  if (e.key === 'Escape') { ed.value = ed.dataset.orig; ed.blur(); e.preventDefault(); }
  else if (e.key === 'Enter' && (ed.tagName === 'INPUT' || e.ctrlKey || e.metaKey)) { e.preventDefault(); ed.blur(); }
});
$('#paneInfo').addEventListener('focusout', e => {
  const tt = e.target.closest('.tt[contenteditable="true"]');
  if (tt) {
    tt.contentEditable = 'false';
    const key = tt.closest('[data-tags]').dataset.tags;
    if (tt.textContent.trim() !== tt.dataset.orig) {
      const list = curTags(key).filter((x, i, a) => a.indexOf(x) === i); commitTags(key, list);
    }
    return;
  }
  const ti = e.target.closest('.tag-in');
  if (ti && ti.value.trim()) {
    const key = ti.closest('[data-tags]').dataset.tags;
    const list = curTags(key); for (const a of splitFor(key, ti.value)) if (!list.includes(a)) list.push(a);
    ti.value = ''; commitTags(key, list); return;
  }
  const ed = e.target.closest('[data-ed]'); if (ed) commitEd(ed);
});

/* ---- 修改紀錄 ---- */
const SRC_LABEL = { edit: '面板', bulk: '批次', keyword: '關鍵字管理', excel: 'Excel 端', revert: '還原' };
const short = s => s == null || s === '' ? '（空白）' : (String(s).length > 120 ? String(s).slice(0, 120) + '…' : String(s));
async function loadHist() {
  const m = P.cur; if (!m) return;
  const list = await api(`/api/media/${m.id}/edits`).catch(() => []);
  if (P.cur?.id !== m.id) return;
  $('#paneHist').innerHTML = `<p class="muted" style="margin-top:0;font-size:12px">記錄在面板、批次操作與 Excel 端（重新載入時）所做的修改。按「還原」會把該欄位改回修改前的內容，並同步寫回 Excel。</p>` +
    (list.length ? list.map(e => `
    <div class="he">
      <div class="he-h"><strong>${esc(fieldLabel(e.field))}</strong><span class="src src-${esc(e.source)}">${esc(SRC_LABEL[e.source] || e.source)}</span>
        <span class="muted">${esc(fmtDate(e.at))}</span><button class="link" data-revert="${e.id}" title="改回修改前的內容">還原</button></div>
      <div class="he-v"><span class="old">${esc(short(e.old))}</span><span class="arr">→</span><span class="new">${esc(short(e.new))}</span></div>
    </div>`).join('') : '<div class="muted">尚無修改紀錄</div>');
}
$('#paneHist').addEventListener('click', async e => {
  const b = e.target.closest('[data-revert]'); if (!b) return;
  try {
    const d = await api(`/api/edits/${b.dataset.revert}/revert`, { method: 'POST' });
    applyItem(d); renderInfo(); renderDetailsHeader(); loadHist(); pollSync(true); updateDatalists();
    toast('已還原');
  } catch (err) { toast('還原失敗：' + err.message); }
});

/* ---- Excel 同步狀態 ---- */
let syncTimer, syncData = [];
const extNotified = new Set();
async function pollSync(soon) {
  clearTimeout(syncTimer);
  if (soon) { syncTimer = setTimeout(() => pollSync(), 900); return; }
  try { syncData = (await api('/api/sync')).batches; renderSync(); } catch { }
  syncTimer = setTimeout(() => pollSync(), syncData.some(b => b.pending) ? 2000 : 8000);
}
const SYNC_TXT = {
  ok: ['✓', 'Excel 已同步'], pending: ['⟳', '寫入 Excel 中…'], locked: ['⚠', 'Excel 開啟中，關閉後自動寫入'],
  error: ['✖', 'Excel 寫入失敗'], unlinked: ['○', '未連結 Excel'], off: ['○', '已關閉寫回 Excel'],
};
function renderSync() {
  const bd = $('#syncBadge');
  if (!syncData.length) { bd.hidden = true; } else {
    const order = ['error', 'locked', 'pending', 'unlinked', 'off', 'ok'];
    const worst = order.find(s => syncData.some(b => b.state === s)) || 'ok';
    const pend = syncData.reduce((a, b) => a + b.pending, 0);
    bd.hidden = false; bd.className = 'sync-badge s-' + worst;
    bd.textContent = `${SYNC_TXT[worst][0]} ${SYNC_TXT[worst][1]}${pend ? `（${pend}）` : ''}`;
    bd.title = syncData.map(b => `${b.source_name}：${b.msg || ''}${b.source_path ? '\n' + b.source_path : ''}`).join('\n\n');
  }
  for (const b of syncData) {
    if (b.external_changed && !extNotified.has(b.id)) {
      extNotified.add(b.id);
      toast(`「${b.source_name}」已在 Excel 中被修改，可在左側「已匯入清冊」按「重新載入」套用`, 6000);
    }
  }
  renderBatches(); updateSyncInline();
}
function updateSyncInline() {
  const el = $('#syncInline'); if (!el || !P.cur) return;
  const b = syncData.find(x => x.id === P.cur.batch_id);
  if (!b) { el.textContent = ''; return; }
  el.className = 'sync-inline s-' + b.state;
  el.textContent = `${SYNC_TXT[b.state]?.[0] || ''} ${b.state === 'unlinked' ? '未連結 Excel，修改只存在面板' : SYNC_TXT[b.state]?.[1] || ''}`;
  el.title = b.msg || '';
}
$('#syncBadge').onclick = () => {
  if (!$('#viewer').hidden) return;
  const bl = $('#batchList'); bl.scrollIntoView({ behavior: 'smooth', block: 'center' });
  bl.classList.add('flash'); setTimeout(() => bl.classList.remove('flash'), 1200);
};

function renderBatches() {
  const st = Object.fromEntries(syncData.map(b => [b.id, b]));
  $('#batchList').innerHTML = S.batches.slice().reverse().map(b => {
    const s = st[b.id] || {};
    return `<div class="b">
      <div class="t">${esc(b.source_name)}</div>
      <div class="bp" title="${esc(s.source_path || b.source_path || '')}">${esc(s.source_path || b.source_path || '未連結原始 Excel 檔案')}</div>
      <div class="bs s-${esc(s.state || '')}" title="${esc(s.msg || '')}">${SYNC_TXT[s.state]?.[0] || ''} ${esc(s.msg || '')}${s.pending ? `（${s.pending} 項）` : ''}${s.external_changed ? '<br>⚠ Excel 已在外部修改' : ''}</div>
      <div class="s">${esc(b.sheet)}・${b.row_count} 筆・${fmtDate(b.imported_at)}</div>
      <div class="ba">
        <button class="link" data-link="${b.id}" title="指定原始 Excel 位置，之後的修改會寫回此檔">${s.source_path || b.source_path ? '變更檔案' : '連結原始檔'}</button>
        ${s.source_path || b.source_path ? `<button class="link" data-reload="${b.id}" title="從 Excel 重新載入（套用在 Excel 裡做的修改）">重新載入</button>
        <button class="link" data-syncnow="${b.id}" title="立即嘗試寫入">立即同步</button>` : ''}
        <button class="link danger" data-delbatch="${b.id}" title="從面板移除此清冊（不會刪除 Excel 與影片）">移除</button>
      </div></div>`;
  }).join('') || '<div class="muted">尚未匯入</div>';
}
$('#batchList').addEventListener('click', async e => {
  const t = e.target.closest('[data-link],[data-reload],[data-syncnow]'); if (!t) return;
  e.stopPropagation();
  try {
    if (t.dataset.link) {
      const b = S.batches.find(x => x.id === +t.dataset.link);
      const p = (prompt('請輸入原始 Excel 清冊的完整路徑\n（在檔案總管對檔案按 Shift+右鍵 →「複製路徑」）', b?.source_path || '') || '').trim();
      if (!p) return;
      await api(`/api/batches/${t.dataset.link}/link`, { method: 'POST', json: { path: p } });
      toast('已連結，之後的修改會即時寫回此 Excel'); await load(); pollSync(true);
    } else if (t.dataset.reload) {
      let r;
      try { r = await api(`/api/batches/${t.dataset.reload}/reload`, { method: 'POST', json: {} }); }
      catch (err) {
        if (!/尚未寫入/.test(err.message) || !confirm(err.message + '\n\n仍要以 Excel 內容覆蓋嗎？')) throw err;
        r = await api(`/api/batches/${t.dataset.reload}/reload`, { method: 'POST', json: { force: true } });
      }
      extNotified.delete(+t.dataset.reload);
      toast(`已從 Excel 重新載入：${r.rows} 筆，其中 ${r.changed} 筆有變更`, 4000);
      await load(); pollSync();
      if (!$('#viewer').hidden && P.cur) { applyItem(await api('/api/media/' + P.cur.id)); renderDetails(); }
    } else if (t.dataset.syncnow) {
      await api('/api/sync', { method: 'POST' }); pollSync(true);
    }
  } catch (err) { toast(err.message, 5000); }
});

/* ---- 標記點 ---- */
async function addMarker() {
  if (!P.cur || !V.duration) return;
  const body = P.A != null && P.B != null ? { t: P.A, t_out: P.B, label: '' } : { t: V.currentTime, label: '' };
  const m = await api(`/api/media/${P.cur.id}/markers`, { method: 'POST', json: body });
  P.cur.markers = m.markers; S.byId.get(P.cur.id).marker_count = m.markers.length;
  renderMarks(); showTab('marks');
  osd('🔖 已新增標記點 ' + fmtT(body.t));
  const inputs = $$('#paneMarks .mk input');
  const newest = m.markers.reduce((a, b) => (b.id > a.id ? b : a));
  const el = $(`#paneMarks .mk[data-id="${newest.id}"] input`);
  (el || inputs[inputs.length - 1])?.focus();
}
$('#cMark').onclick = addMarker;
function renderMarks() {
  const m = P.cur; if (!m) return;
  const mk = m.markers || [];
  $('#markCount').textContent = mk.length || '';
  $('#paneMarks').innerHTML = `
    <p class="muted" style="margin-top:0;font-size:12px">按 <kbd>X</kbd> 於目前時間新增標記點；設定 A/B 區段後按 <kbd>X</kbd> 會記錄入點→出點。標記點會隨「匯出」寫入 Excel。</p>
    <div class="mk-list">${mk.map(x => `
      <div class="mk" data-id="${x.id}">
        <span class="tc" data-seek="${x.t}" title="跳到此處">${fmtT(x.t)}${x.t_out != null ? ' → ' + fmtT(x.t_out) : ''}</span>
        <input value="${esc(x.label)}" placeholder="說明（例如：開場、精華、NG）" data-label="${x.id}">
        <button data-del="${x.id}" title="刪除">✕</button>
      </div>`).join('') || '<div class="muted">尚無標記點</div>'}</div>
    <p><button class="btn sm" id="mkAdd">＋ 在目前時間新增</button></p>`;
  $('#mkAdd').onclick = addMarker;
  renderSeekMarkers();
}
$('#paneMarks').addEventListener('click', async e => {
  const s = e.target.closest('[data-seek]');
  if (s) {
    const mk = P.cur.markers.find(x => x.id === +s.parentElement.dataset.id);
    V.currentTime = +s.dataset.seek;
    if (mk?.t_out != null) { P.A = mk.t; P.B = mk.t_out; updateAB(); }
    return;
  }
  const d = e.target.closest('[data-del]');
  if (d) {
    await api('/api/markers/' + d.dataset.del, { method: 'DELETE' });
    P.cur.markers = P.cur.markers.filter(x => x.id !== +d.dataset.del);
    S.byId.get(P.cur.id).marker_count = P.cur.markers.length;
    renderMarks();
  }
});
$('#paneMarks').addEventListener('input', debounce(async e => {
  const id = e.target.dataset.label; if (!id) return;
  await api('/api/markers/' + id, { method: 'PATCH', json: { label: e.target.value } });
  const mk = P.cur.markers.find(x => x.id === +id); if (mk) mk.label = e.target.value;
  renderSeekMarkers();
}, 500));
function renderSeekMarkers() {
  const d = V.duration, el = $('#seekMarkers');
  if (!d || !P.cur) { el.innerHTML = ''; return; }
  el.innerHTML = (P.cur.markers || []).map(x =>
    (x.t_out != null ? `<i class="range" style="left:${x.t / d * 100}%;width:${(x.t_out - x.t) / d * 100}%"></i>` : '') +
    `<i style="left:${x.t / d * 100}%" data-t="${x.t}" title="${esc(fmtT(x.t) + ' ' + (x.label || ''))}"></i>`).join('');
}
$('#seekMarkers').addEventListener('pointerdown', e => {
  const i = e.target.closest('i[data-t]'); if (!i) return;
  e.stopPropagation(); V.currentTime = +i.dataset.t;
});

/* ---- Markdown ---- */
async function loadMd() {
  const pane = $('#paneMd'), m = P.cur;
  if (!m || pane.dataset.loaded == String(m.id)) return;
  pane.dataset.loaded = m.id;
  if (!m.md_path) { pane.innerHTML = '<div class="muted">此筆沒有 Markdown 路徑</div>'; return; }
  pane.innerHTML = '<div class="muted">讀取中…</div>';
  try {
    const r = await fetch('/api/markdown/' + m.id);
    if (!r.ok) throw new Error((await r.json()).detail);
    pane.innerHTML = `<div class="md-body">${mdToHtml(await r.text())}</div>`;
  } catch (e) { pane.innerHTML = `<div class="muted">${esc(e.message)}<br><code>${esc(m.md_path)}</code></div>`; }
}
function mdToHtml(src) {
  const lines = src.replace(/\r/g, '').split('\n'); const out = []; let inCode = false, list = null, para = [];
  const inline = s => esc(s).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>').replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '[$1]').replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  const flush = () => { if (para.length) { out.push('<p>' + para.map(inline).join('<br>') + '</p>'); para = []; } if (list) { out.push(`</${list}>`); list = null; } };
  for (const l of lines) {
    if (/^```/.test(l)) { flush(); out.push(inCode ? '</code></pre>' : '<pre><code>'); inCode = !inCode; continue; }
    if (inCode) { out.push(esc(l) + '\n'); continue; }
    let mm;
    if ((mm = l.match(/^(#{1,6})\s+(.*)/))) { flush(); out.push(`<h${mm[1].length}>${inline(mm[2])}</h${mm[1].length}>`); continue; }
    if ((mm = l.match(/^\s*[-*+]\s+(.*)/)) || (mm = l.match(/^\s*\d+\.\s+(.*)/))) {
      const t = /^\s*\d+\./.test(l) ? 'ol' : 'ul';
      if (para.length) { out.push('<p>' + para.map(inline).join('<br>') + '</p>'); para = []; }
      if (list !== t) { if (list) out.push(`</${list}>`); out.push(`<${t}>`); list = t; }
      out.push(`<li>${inline(mm[1])}</li>`); continue;
    }
    if (/^\|.*\|\s*$/.test(l)) {
      if (/^\|[\s:|-]+\|\s*$/.test(l)) continue;
      flush(); out.push('<table><tr>' + l.trim().slice(1, -1).split('|').map(c => `<td>${inline(c.trim())}</td>`).join('') + '</tr></table>'); continue;
    }
    if (/^\s*$/.test(l)) { flush(); continue; }
    if (/^>\s?/.test(l)) { flush(); out.push(`<blockquote class="muted">${inline(l.replace(/^>\s?/, ''))}</blockquote>`); continue; }
    if (list) { out.push(`</${list}>`); list = null; }
    para.push(l);
  }
  flush(); if (inCode) out.push('</code></pre>');
  return out.join('\n').replace(/<\/table>\n<table>/g, '');
}

/* ---------------- 啟動 ---------------- */
(async () => {
  try { await load(); } catch (e) { toast('無法連線到後端：' + e.message, 8000); return; }
  pollSync();
  const h = location.hash.match(/m=(\d+)/);
  if (h && S.byId.has(+h[1])) openViewer(+h[1]);
  // 背景技術資訊（時長、解析度）讀取完成前，定期更新
  let tries = 0;
  const poll = async () => {
    const st = await api('/api/status').catch(() => null);
    if (st?.probing && tries++ < 60) { setTimeout(poll, 3000); }
    else if (tries) { if ($('#viewer').hidden) load(); }
  };
  setTimeout(poll, 2000);
})();
window.addEventListener('beforeunload', savePos);
