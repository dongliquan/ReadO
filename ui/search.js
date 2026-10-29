// ===== Find in Files (modal, IntelliJ-style) =====
let _fifResults = [];     // flat list of {file, line, ...}
let _fifSel = -1;         // index into _fifResults
let _fifTerm = '';
let _fifFind = null;      // {term, regex, caseS, word} of the shown results

let _fifMax = 0;           // 0: the settings' cap; "show more" raises it
const FIF_OPT_IDS = { caseS: 'fifCase', word: 'fifWord', regex: 'fifRegex', glob: 'fifGlob', exclude: 'fifExcl', ctx: 'fifCtx', scope: 'fifScope' };
// The exclude box is the whole exclude list: it starts with the default patterns
// (Settings' search-ignored folders + the built-in noise list, from /api/settings)
// and is edited freely; Defaults puts them back. Kept in state.json (ui.fifOpts).
function fifDefaultExcludes() {
  return (_settings.search_default_excludes || []).join(', ');
}
function fifResetExcludes() {
  document.getElementById('fifExcl').value = fifDefaultExcludes();
  _fifMax = 0;
  saveFIFOpts();
  runFIF();
}
// File mask and exclude are edited in their own dialog (#fifPatBg); the option
// bar shows a summary button. The applied values live in the hidden #fifGlob /
// #fifExcl, comma-separated, so saving and the search request are unchanged.
function fifPatList(s) { return String(s || '').split(/[,\n]/).map(x => x.trim()).filter(Boolean); }
function updateFIFPatButton() {
  const mask = fifPatList(document.getElementById('fifGlob').value);
  const excl = fifPatList(document.getElementById('fifExcl').value);
  const b = document.getElementById('fifPatBtn');
  const m = mask.length ? mask.join(', ') : 'all files';
  b.textContent = `mask: ${m.length > 28 ? m.slice(0, 27) + '…' : m} · exclude: ${excl.length}`;
  b.title = 'file mask & exclude patterns — click to edit\nmask: ' + (mask.join(', ') || '(every text file)') +
    '\nexclude: ' + (excl.join(', ') || '(nothing)');
}
function fifPatIsOpen() { return document.getElementById('fifPatBg').classList.contains('show'); }
function openFIFPatterns() {
  document.getElementById('fifPatMask').value = fifPatList(document.getElementById('fifGlob').value).join('\n');
  document.getElementById('fifPatExcl').value = fifPatList(document.getElementById('fifExcl').value).join('\n');
  document.getElementById('fifPatBg').classList.add('show');
  document.getElementById('fifPatExcl').focus();
}
function closeFIFPatterns() {
  if (!fifPatIsOpen()) return;
  document.getElementById('fifPatBg').classList.remove('show');
  if (fifIsOpen()) document.getElementById('fifQ').focus();
}
function fifPatDefaults() {
  const t = document.getElementById('fifPatExcl');
  t.value = (_settings.search_default_excludes || []).join('\n');
  t.focus();
}
function applyFIFPatterns() {
  document.getElementById('fifGlob').value = fifPatList(document.getElementById('fifPatMask').value).join(', ');
  document.getElementById('fifExcl').value = fifPatList(document.getElementById('fifPatExcl').value).join(', ');
  closeFIFPatterns();
  _fifMax = 0;
  saveFIFOpts();
  runFIF();
}
document.getElementById('fifPatBg').addEventListener('keydown', e => {
  if (e.key === 'Escape') { e.preventDefault(); closeFIFPatterns(); }
  else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); applyFIFPatterns(); }
  else if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA' && e.target.tagName !== 'BUTTON') { e.preventDefault(); applyFIFPatterns(); }
  e.stopPropagation();  // keys typed here are not editor / app shortcuts
});
function restoreFIFOpts() {  // STATE.fifOpts: the option bar as it was last left
  const o = Object.assign({}, STATE.fifOpts && typeof STATE.fifOpts === 'object' ? STATE.fifOpts : {});
  if (o.exclV !== 2) {  // never saved, or saved by a build with the Defaults on/off toggle
    const own = String(o.exclude || '').split(',').map(s => s.trim()).filter(Boolean);
    const defs = o.defExcl === false ? [] : (_settings.search_default_excludes || []);
    o.exclude = [...new Set(defs.concat(own))].join(', ');
  }
  for (const [k, id] of Object.entries(FIF_OPT_IDS)) {
    if (!(k in o)) continue;
    const e = document.getElementById(id);
    if (e.type === 'checkbox') e.checked = !!o[k];
    else if (e.tagName === 'SELECT') { if ([...e.options].some(x => x.value === o[k])) e.value = o[k]; }
    else e.value = o[k];
  }
  updateFIFPatButton();
}
function saveFIFOpts() {
  const o = {};
  for (const [k, id] of Object.entries(FIF_OPT_IDS)) { const e = document.getElementById(id); o[k] = e.type === 'checkbox' ? e.checked : e.value; }
  o.exclV = 2;
  STATE.fifOpts = o;
  saveState();
  updateFIFPatButton();
}
function openFIF(prefill) {
  closeQO();
  closeSettings();
  restoreFIFOpts();
  toggleFIFReplace(!!STATE.fifReplace);
  document.getElementById('fifBg').classList.add('show');
  const inp = document.getElementById('fifQ');
  if (prefill !== undefined) inp.value = prefill;
  inp.focus();
  inp.select();
  if (!inp.value.trim()) loadFIFRecent();
  else if (prefill !== undefined) runFIF();
}
function fifIsOpen() { return document.getElementById('fifBg').classList.contains('show'); }
function qoIsOpen() { return document.getElementById('qoBg').classList.contains('show'); }
// the two dialogs swap in place (tabs, Tab, Ctrl+P / Ctrl+Shift+F); what was typed comes along
function fdSwitch(to, term) {
  term = (term || '').replace(/^[>%#@:]/, '');
  if (to === 'text') return openFIF(term);
  closeFIF();
  openQO((to === 'cmd' ? '>' : to === 'sym' ? '#' : '') + term);
}
function fdTerm() {
  if (fifIsOpen()) return document.getElementById('fifQ').value;
  if (qoIsOpen()) return document.getElementById('qoInput').value.replace(/^[>%#@:]/, '');
  return '';
}
document.querySelectorAll('.fd-tabs').forEach(t => t.addEventListener('mousedown', e => {
  const tab = e.target.closest('.fd-tab');
  if (!tab) return;
  e.preventDefault();
  fdSwitch(tab.dataset.fd, fdTerm());
}));
function toggleFIFReplace(force) {
  const row = document.getElementById('fifReplRow');
  const on = force != null ? force : row.style.display === 'none';
  row.style.display = on ? '' : 'none';
  document.getElementById('fifReplToggle').classList.toggle('on', on);
  if (force == null) {
    STATE.fifReplace = on;
    saveState();
    if (on) document.getElementById('fifRepl').focus();
  }
}
function closeFIF() {
  document.getElementById('fifPatBg').classList.remove('show');
  document.getElementById('fifBg').classList.remove('show');
}
// ✕, Esc, a click outside (and Ctrl+Shift+F again in Find in Files): close the
// dialog and give the keyboard back to the active pane
function dismissFD() {
  if (!fifIsOpen() && !qoIsOpen()) return;
  closeFIF();
  closeQO();
  focusPane(activePaneIdx);
}
document.getElementById('fifBg').addEventListener('keydown', e => {
  if (e.defaultPrevented) return;
  const c = _binds.bubble.get(keyCombo(e)) || _binds.capture.get(keyCombo(e));
  if (e.key === 'Escape' || (c && c.id === 'edit.findInFiles')) { e.preventDefault(); e.stopPropagation(); dismissFD(); }
});

let _fifTimer = null;
let _fifAbort = null;
let _fifReqSeq = 0;
async function runFIF() {
  const q = document.getElementById('fifQ').value.trim();
  const summary = document.getElementById('fifSummary');
  const resultsEl = document.getElementById('fifResults');
  const previewEl = document.getElementById('fifPreview');
  // cancel any in-flight request
  if (_fifAbort) _fifAbort.abort();
  if (!q) {
    summary.textContent = '';
    previewEl.innerHTML = '<div class="qo-empty">select a result for preview</div>';
    _fifResults = []; _fifSel = -1; _fifTerm = '';
    loadFIFRecent();
    return;
  }
  const caseS = document.getElementById('fifCase').checked ? 1 : 0;
  const regex = document.getElementById('fifRegex').checked ? 1 : 0;
  const word = document.getElementById('fifWord').checked ? 1 : 0;
  const glob = document.getElementById('fifGlob').value.trim();
  const exclude = document.getElementById('fifExcl').value.trim();
  const scope = fifScopeValue();
  const ctx = parseInt(document.getElementById('fifCtx').value) || 0;
  const find = { term: q, regex: !!regex, caseS: !!caseS, word: !!word };
  const url = `/api/search?q=${encodeURIComponent(q)}&case=${caseS}&regex=${regex}&word=${word}&glob=${encodeURIComponent(glob)}&scope=${encodeURIComponent(scope)}&ctx=${ctx}` +
    `&exclude=${encodeURIComponent(exclude)}&defexcl=0` + (_fifMax ? `&max=${_fifMax}` : '');
  summary.textContent = 'searching...';
  if (!_fifMax) resultsEl.innerHTML = '';  // "show more" keeps the list until the longer one arrives
  previewEl.innerHTML = '<div class="qo-empty">searching...</div>';
  const seq = ++_fifReqSeq;
  _fifAbort = new AbortController();
  try {
    const r = await fetch(url, { signal: _fifAbort.signal });
    const data = await r.json();
    if (seq !== _fifReqSeq) return; // stale response — newer search in progress
    if (data.error) {
      summary.textContent = '✗ ' + data.error;
      resultsEl.innerHTML = '';
      previewEl.innerHTML = '';
      return;
    }
    _fifTerm = q;
    _fifFind = find;
    renderFIFResults(data, q);
    saveFIFRecent(q);
  } catch (e) {
    if (e.name === 'AbortError') return;
    if (seq !== _fifReqSeq) return;
    summary.textContent = '✗ ' + e.message;
  }
}

function renderFIFResults(data, term) {
  const c = document.getElementById('fifResults');
  const summary = document.getElementById('fifSummary');
  c.innerHTML = '';
  summary.textContent =
    `${data.total} match${data.total !== 1 ? 'es' : ''}` +
    (data.truncated ? ' (truncated)' : '') +
    ` · ${data.files} files`;
  _fifResults = data.results || [];
  _fifSel = _fifResults.length ? 0 : -1;
  if (!_fifResults.length) {
    c.innerHTML = '<div class="qo-empty">no matches</div>';
    document.getElementById('fifPreview').innerHTML = '<div class="qo-empty">no preview</div>';
    return;
  }
  // group by file
  const byFile = {};
  _fifResults.forEach((r, idx) => {
    r._idx = idx;
    (byFile[r.path] = byFile[r.path] || []).push(r);
  });
  for (const file of Object.keys(byFile)) {
    // file group: badge · name · folder (dim) · count — the same look as a Find File row
    const fh = document.createElement('div');
    fh.className = 'res-file';
    const cut = file.lastIndexOf('/');
    fh.innerHTML = fileBadge(file) + `<span class="qo-name">${escapeHtml(file.slice(cut + 1))}</span>` +
      (cut > 0 ? `<span class="qo-dir">${escapeHtml(file.slice(0, cut))}</span>` : '') + `<span class="cnt">${byFile[file].length}</span>` +
      (cut > 0 ? `<span class="fd-excl" title="exclude this folder from the search (/${escapeHtml(file.slice(0, cut))}/**)">⊘ folder</span>` : '');
    fh.title = file;
    fh.onclick = e => {
      if (e.target.closest('.fd-excl')) addFIFExclude('/' + file.slice(0, cut) + '/**');
      else openFIFHit(byFile[file][0], e.ctrlKey || e.metaKey);
    };
    c.appendChild(fh);
    for (const r of byFile[file]) {
      const row = document.createElement('div');
      row.className = 'res-line';
      row.dataset.idx = r._idx;
      const ln = document.createElement('span'); ln.className = 'ln'; ln.textContent = r.line;
      const tx = document.createElement('span'); tx.className = 'tx';
      tx.innerHTML = highlight(String(r.text).replace(/^\s+/, ''), term);
      row.appendChild(ln); row.appendChild(tx);
      row.onclick = e => openFIFHit(r, e.ctrlKey || e.metaKey);
      row.addEventListener('mouseenter', () => {
        _fifSel = r._idx;
        updateFIFSelection();
      });
      c.appendChild(row);
    }
  }
  if (data.truncated && (_fifMax || _settings.search_max_results || 500) < 20000) {
    const more = document.createElement('div');
    more.className = 'res-line fd-more-row';
    more.textContent = `show more (first ${_fifResults.length} shown)`;
    more.onclick = () => { _fifMax = Math.min(20000, (_fifMax || _settings.search_max_results || 500) * 4); runFIF(); };
    c.appendChild(more);
  }
  updateFIFSelection();
}
// a result file's "⊘ folder": add its folder to the exclude patterns and search again
function addFIFExclude(pat) {
  const e = document.getElementById('fifExcl');
  const cur = e.value.split(',').map(s => s.trim()).filter(Boolean);
  if (!cur.includes(pat)) cur.push(pat);
  e.value = cur.join(', ');
  _fifMax = 0;
  saveFIFOpts();
  runFIF();
  document.getElementById('fifQ').focus();
}
// Enter / click: open the hit; Ctrl+Enter / Ctrl+click: in the other split pane
function openFIFHit(r, beside) {
  if (!r) return;
  closeFIF();
  if (beside) openInOtherPane(r.path, activePaneIdx, true, null, r.line, _fifFind);
  else openFile(r.path, r.line, _fifFind);
}

function updateFIFSelection() {
  document.querySelectorAll('#fifResults .res-line.sel').forEach(el => el.classList.remove('sel'));
  if (_fifSel < 0 || _fifSel >= _fifResults.length) return;
  const el = document.querySelector(`#fifResults .res-line[data-idx="${_fifSel}"]`);
  if (el) {
    el.classList.add('sel');
    el.scrollIntoView({ block: 'nearest' });
  }
  renderFIFPreview(_fifResults[_fifSel]);
}

function renderFIFPreview(r) {
  const p = document.getElementById('fifPreview');
  if (!r) { p.innerHTML = '<div class="qo-empty">no preview</div>'; return; }
  const before = r.before || [];
  const after = r.after || [];
  const startLine = r.before_start || (r.line - before.length);
  const out = [];
  out.push(`<div class="pv-head">${escapeHtml(r.path)}</div>`);
  before.forEach((line, i) => {
    out.push(`<div class="pv-line"><span class="ln">${startLine + i}</span><span>${escapeHtml(line)}</span></div>`);
  });
  out.push(`<div class="pv-line hit"><span class="ln">${r.line}</span><span>${highlight(r.text, _fifTerm)}</span></div>`);
  after.forEach((line, i) => {
    out.push(`<div class="pv-line"><span class="ln">${r.line + 1 + i}</span><span>${escapeHtml(line)}</span></div>`);
  });
  p.innerHTML = out.join('');
  // scroll hit line into view
  const hit = p.querySelector('.pv-line.hit');
  if (hit) hit.scrollIntoView({ block: 'center' });
}

// ===== Recent searches (saved UI state) =====
// empty query: recent searches (click = search again), like Find File's recent files
function loadFIFRecent() {
  const c = document.getElementById('fifResults');
  if (!c || document.getElementById('fifQ').value.trim()) return;
  const rec = STATE.fifRecent.slice(0, 15);
  c.innerHTML = rec.length ? '<div class="fd-recent-h">recent searches</div>' + rec.map((s, i) =>
    `<div class="res-line fd-recent" data-q="${escapeHtml(String(s))}"><span class="ln">↺</span><span class="tx">${escapeHtml(String(s))}</span></div>`).join('')
    : '<div class="qo-empty">type to search text in every file of the folder</div>';
  c.querySelectorAll('.fd-recent').forEach(r => r.onclick = () => {
    const inp = document.getElementById('fifQ');
    inp.value = r.dataset.q;
    inp.focus();
    runFIF();
  });
}
function saveFIFRecent(q) {
  if (!q) return;
  STATE.fifRecent = [q].concat(STATE.fifRecent.filter(s => s !== q)).slice(0, 15);
  saveState();
}

// ===== Wiring =====
document.getElementById('fifQ').addEventListener('input', () => {
  if (_fifTimer) clearTimeout(_fifTimer);
  _fifMax = 0;
  _fifTimer = setTimeout(runFIF, 200);
});
document.getElementById('fifQ').addEventListener('keydown', e => {
  if (e.key === 'Tab' && !e.shiftKey && !e.ctrlKey && !e.altKey) {
    e.preventDefault();
    fdSwitch('files', e.target.value);
  } else if (e.altKey && /^[cwx]$/i.test(e.key)) {  // option toggles, as in IntelliJ
    e.preventDefault();
    const box = document.getElementById({ c: 'fifCase', w: 'fifWord', x: 'fifRegex' }[e.key.toLowerCase()]);
    box.checked = !box.checked;
    box.dispatchEvent(new Event('change'));
  } else if (e.key === 'Enter') {
    e.preventDefault();
    if (_fifSel >= 0 && _fifResults.length) openFIFHit(_fifResults[_fifSel], e.ctrlKey || e.metaKey);
    else runFIF();
  } else if (e.key === 'Escape') {
    e.preventDefault(); dismissFD();
  } else if (e.key === 'ArrowDown') {
    if (_fifResults.length) {
      e.preventDefault();
      _fifSel = Math.min(_fifResults.length - 1, _fifSel + 1);
      updateFIFSelection();
    }
  } else if (e.key === 'ArrowUp') {
    if (_fifResults.length) {
      e.preventDefault();
      _fifSel = Math.max(0, _fifSel - 1);
      updateFIFSelection();
    }
  }
});
['fifCase','fifWord','fifRegex','fifScope','fifCtx'].forEach(id => {
  document.getElementById(id).addEventListener('change', () => { _fifMax = 0; saveFIFOpts(); runFIF(); });
});

function highlight(text, term) {
  const esc = escapeHtml;
  if (!term) return esc(text);
  const lo = text.toLowerCase();
  const tl = term.toLowerCase();
  let out = '', i = 0;
  while (i < text.length) {
    const idx = lo.indexOf(tl, i);
    if (idx < 0) { out += esc(text.slice(i)); break; }
    out += esc(text.slice(i, idx));
    out += '<mark>' + esc(text.slice(idx, idx + tl.length)) + '</mark>';
    i = idx + tl.length;
  }
  return out;
}

