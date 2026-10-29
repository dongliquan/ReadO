// === Save / reload / conflicts ===
async function saveDoc(doc, force) {
  if (!doc) return false;
  if (doc.readonly) { showToast('read-only: ' + doc.readonly, true); return false; }
  if (doc.gone) { showToast('cannot save: file was deleted on disk', true); return false; }
  const alt = doc.model.getAlternativeVersionId();
  let r, data = {};
  doc.saving = true;
  try {
    r = await fetch('/api/save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: doc.key, text: doc.model.getValue(), mtime_ns: force ? null : doc.mtime,
        encoding: doc.encoding, bom: doc.bom,
      }),
    });
    data = await r.json().catch(() => ({}));
  } catch (e) {
    showToast('save failed: ' + e.message, true);
    return false;
  } finally {
    doc.saving = false;
  }
  if (r.status === 409) {
    const choice = await askChoice('file changed on disk',
      `${baseName(doc.key)} was changed by another program after it was opened here.\n` +
      'Overwrite it with your version, or reload it and discard your changes?',
      [{ label: 'overwrite', value: 'overwrite' },
       { label: 'reload (discard mine)', value: 'reload' },
       { label: 'cancel', value: 'cancel', primary: true }]);
    if (choice === 'overwrite') return saveDoc(doc, true);
    if (choice === 'reload') await reloadDoc(doc);
    return false;
  }
  if (!r.ok) {
    showToast('save failed: ' + (data.error || 'HTTP ' + r.status), true);
    return false;
  }
  doc.mtime = data.mtime_ns;
  doc.savedAlt = alt;
  scheduleGit(doc, 200);
  doc.metaDirty = false;
  doc.diskChanged = false;
  updateDirty(doc);
  renderAllTabs();
  // our own temp-file + rename touches the folder; don't treat it as a tree change
  _treeSkip.add(isAbsKey(doc.key) ? '' : doc.key.split('/').slice(0, -1).join('/'));
  showToast('saved ' + baseName(doc.key));
  return true;
}
async function saveCurrent() {
  const doc = currentDoc();
  if (!doc) return;
  if (!doc.dirty) { showToast('no changes to save'); return; }
  await saveDoc(doc);
}

// Replace a model's text with the disk version, keeping undo history and each
// pane's scroll/cursor.
async function reloadDoc(doc) {
  let data;
  try {
    const r = await fetch('/api/file?path=' + encodeURIComponent(doc.key) + (doc.forceEncoding ? '&encoding=' + doc.forceEncoding : ''));
    if (!r.ok) throw new Error('HTTP ' + r.status);
    data = await r.json();
  } catch (e) {
    showToast('reload failed: ' + e.message, true);
    return false;
  }
  if (!docs.has(doc.key)) return false;  // closed meanwhile
  const model = doc.model;
  const eol = /\r\n/.test(data.text) ? monaco.editor.EndOfLineSequence.CRLF
                                     : monaco.editor.EndOfLineSequence.LF;
  const views = panes.filter(p => p.editor.getModel() === model).map(p => [p, p.editor.saveViewState()]);
  if (model.getValue(monaco.editor.EndOfLinePreference.LF) !== data.text.replace(/\r\n?/g, '\n')) {
    model.pushEditOperations([], [{ range: model.getFullModelRange(), text: data.text }], () => null);
  }
  if (model.getEndOfLineSequence() !== eol) model.pushEOL(eol);
  views.forEach(([p, vs]) => p.editor.restoreViewState(vs));
  Object.assign(doc, {
    mtime: data.mtime_ns, encoding: data.encoding, bom: !!data.bom, readonly: data.readonly || null,
    truncated: !!data.truncated,
    savedAlt: model.getAlternativeVersionId(), metaDirty: false, diskChanged: false, gone: false,
  });
  updateDirty(doc);
  renderAllTabs();
  panes.forEach(p => { if (p.currentPath === doc.key) { showPaneView(p); applyEditorMode(p); } });
  updateStatus();
  return true;
}

// === Dialog (choice buttons) ===
let _dlgResolve = null;
let _dlgFocus = null;  // element to give focus back to (usually the editor)
// opts.input: show a text box with this initial value; the promise then
// resolves to {value, text}.
function askChoice(title, message, buttons, opts) {
  if (_dlgResolve) closeDialog('cancel');
  return new Promise(resolve => {
    const withInput = !!opts && typeof opts.input === 'string';
    const inp = document.getElementById('dlgInput');
    inp.style.display = withInput ? '' : 'none';
    inp.value = withInput ? opts.input : '';
    _dlgResolve = withInput ? v => resolve({ value: v, text: inp.value }) : resolve;
    _dlgFocus = document.activeElement;
    document.getElementById('dlgTitle').textContent = title;
    document.getElementById('dlgMsg').textContent = message;
    const row = document.getElementById('dlgBtns');
    row.innerHTML = '';
    for (const b of buttons) {
      const el = document.createElement('button');
      el.textContent = b.label;
      el.dataset.value = b.value;
      if (b.primary) el.className = 'primary';
      el.onclick = () => closeDialog(b.value);
      row.appendChild(el);
    }
    document.getElementById('dlgBg').classList.add('show');
    if (withInput) {
      inp.focus();
      // rename: the name without its extension is selected, as in Explorer / VS Code
      const dot = opts.selectStem ? inp.value.lastIndexOf('.') : -1;
      if (opts.selectStem) inp.setSelectionRange(0, dot > 0 ? dot : inp.value.length);
      else inp.setSelectionRange(inp.value.length, inp.value.length);
    }
    else (row.querySelector('.primary') || row.firstChild).focus();
  });
}
document.getElementById('dlgInput').addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  e.preventDefault();
  const primary = document.querySelector('#dlgBtns .primary');
  closeDialog(primary ? primary.dataset.value : 'ok');
});

// === New file ===
// dir: folder relative to base_dir to prefill (tree right-click), else the
// folder of the active file.
async function newFileDialog(dir) {
  if (dir === undefined) {
    const cur = currentPath;
    dir = cur && !isAbsKey(cur) ? cur.split('/').slice(0, -1).join('/') : '';
  }
  const res = await askChoice('new file',
    'Path relative to the base directory. The folder must exist; an existing file is never replaced.',
    [{ label: 'create', value: 'ok', primary: true }, { label: 'cancel', value: 'cancel' }],
    { input: dir ? dir + '/' : '' });
  const path = res.text.trim().replace(/\\/g, '/').replace(/^\/+/, '');
  if (res.value !== 'ok' || !path) return;
  let r, data = {};
  try {
    r = await fetch('/api/create', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
    data = await r.json().catch(() => ({}));
  } catch (e) {
    showToast('create failed: ' + e.message, true);
    return;
  }
  if (!r.ok) { showToast('create failed: ' + (data.error || 'HTTP ' + r.status), true); return; }
  const parent = data.path.split('/').slice(0, -1).join('/');
  _treeSkip.add(parent);
  await refreshTreeDir(parent).catch(() => {});
  await openFile(data.path);
  showToast('created ' + data.path);
}

// === Replace in files (preview → pick files → confirm → apply) ===
let _rplReq = null;    // the query the shown preview was computed for
let _rplFiles = [];
function replaceRequest() {
  return {
    q: document.getElementById('fifQ').value.trim(),
    replace: document.getElementById('fifRepl').value,
    case: document.getElementById('fifCase').checked,
    word: document.getElementById('fifWord').checked,
    regex: document.getElementById('fifRegex').checked,
    scope: fifScopeValue(),
    glob: document.getElementById('fifGlob').value.trim(),
    exclude: document.getElementById('fifExcl').value.trim(),
    default_excludes: false,  // the exclude box holds the defaults itself (fifDefaultExcludes)
  };
}
async function previewReplace() {
  const req = replaceRequest();
  if (!req.q) { showToast('type what to find first', true); return; }
  document.getElementById('rplBg').classList.add('show');
  document.getElementById('rplTitle').textContent = `replace "${req.q}" → "${req.replace}"`;
  document.getElementById('rplSummary').textContent = 'computing preview...';
  document.getElementById('rplApply').disabled = true;
  document.getElementById('rplList').innerHTML = '';
  let data;
  try {
    const r = await fetch('/api/replace-preview', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(req),
    });
    data = await r.json();
    if (!r.ok) throw new Error(data.error || 'HTTP ' + r.status);
  } catch (e) {
    document.getElementById('rplSummary').textContent = '✗ ' + e.message;
    return;
  }
  _rplReq = req;
  _rplFiles = data.files || [];
  renderReplacePreview(data);
}
function renderReplacePreview(data) {
  const list = document.getElementById('rplList');
  list.innerHTML = '';
  if (!_rplFiles.length) list.innerHTML = '<div class="qo-empty">no matches</div>';
  _rplFiles.forEach((f, i) => {
    const doc = docs.get(f.path);
    // unsaved edits in the editor would be overwritten on disk / lost on reload
    f.blocked = f.readonly || (doc && doc.dirty ? 'unsaved changes in the editor — save or discard first' : null);
    const row = document.createElement('div');
    row.className = 'rpl-file' + (f.blocked ? ' off' : '');
    row.dataset.idx = i;
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.className = 'rpl-cb';
    cb.checked = !f.blocked;
    cb.disabled = !!f.blocked;
    cb.onchange = updateReplaceSummary;
    const path = document.createElement('span');
    path.className = 'rpl-path';
    path.textContent = f.path;
    const meta = document.createElement('span');
    meta.className = 'rpl-meta';
    meta.textContent = f.blocked ? 'skipped: ' + f.blocked : `${f.count} match${f.count === 1 ? '' : 'es'}`;
    const res = document.createElement('span');
    res.className = 'rpl-res';
    row.append(cb, path, meta, res);
    list.appendChild(row);
    for (const sm of f.samples || []) {
      for (const [cls, text] of [['del', '- ' + sm.before], ['add', '+ ' + sm.after]]) {
        const ln = document.createElement('div');
        ln.className = 'rpl-line ' + cls;
        ln.textContent = `${String(sm.line).padStart(5)} ${text}`;
        list.appendChild(ln);
      }
    }
  });
  if (data && data.truncated) {
    const more = document.createElement('div');
    more.className = 'qo-empty';
    more.textContent = 'only the first 1000 files are shown — narrow the search (scope / extensions) for the rest';
    list.appendChild(more);
  }
  document.getElementById('rplAll').checked = true;
  updateReplaceSummary();
}
function checkedReplaceFiles() {
  return [...document.querySelectorAll('#rplList .rpl-cb')]
    .filter(cb => cb.checked && !cb.disabled)
    .map(cb => _rplFiles[+cb.parentElement.dataset.idx]);
}
function updateReplaceSummary() {
  const sel = checkedReplaceFiles();
  const n = sel.reduce((a, f) => a + f.count, 0);
  document.getElementById('rplSummary').textContent =
    `${n} replacement${n === 1 ? '' : 's'} in ${sel.length} of ${_rplFiles.length} file${_rplFiles.length === 1 ? '' : 's'} selected`;
  document.getElementById('rplApply').disabled = !sel.length;
}
function toggleReplaceAll(on) {
  document.querySelectorAll('#rplList .rpl-cb').forEach(cb => { if (!cb.disabled) cb.checked = on; });
  updateReplaceSummary();
}
function closeReplace() { document.getElementById('rplBg').classList.remove('show'); }
async function applyReplace() {
  // re-check: a file may have been edited while the preview was open
  const sel = checkedReplaceFiles().filter(f => !(docs.get(f.path) && docs.get(f.path).dirty));
  if (!sel.length || !_rplReq) return;
  const n = sel.reduce((a, f) => a + f.count, 0);
  const ok = await askChoice('replace in files',
    `Replace ${n} occurrence${n === 1 ? '' : 's'} in ${sel.length} file${sel.length === 1 ? '' : 's'}?\n` +
    'The files are written to disk right away and Ctrl+Z cannot undo it.',
    [{ label: 'replace', value: 'apply' }, { label: 'cancel', value: 'cancel', primary: true }]);
  if (ok !== 'apply') return;
  document.getElementById('rplApply').disabled = true;
  let data;
  try {
    const r = await fetch('/api/replace-apply', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.assign({}, _rplReq, { files: sel.map(f => ({ path: f.path, mtime_ns: f.mtime_ns })) })),
    });
    data = await r.json();
    if (!r.ok) throw new Error(data.error || 'HTTP ' + r.status);
  } catch (e) {
    showToast('replace failed: ' + e.message, true);
    updateReplaceSummary();
    return;
  }
  const byPath = new Map(data.results.map(x => [x.path, x]));
  document.querySelectorAll('#rplList .rpl-file').forEach(row => {
    const res = byPath.get(_rplFiles[+row.dataset.idx].path);
    if (!res) return;
    const el = row.querySelector('.rpl-res');
    el.className = 'rpl-res ' + (res.error ? 'err' : 'ok');
    el.textContent = res.error ? '✗ ' + res.error : `✓ ${res.count} replaced`;
    const cb = row.querySelector('.rpl-cb');
    cb.checked = false;
    cb.disabled = true;
  });
  const failed = data.results.filter(x => x.error).length;
  document.getElementById('rplSummary').textContent =
    `done: ${data.count} replacement${data.count === 1 ? '' : 's'} in ${data.files} file${data.files === 1 ? '' : 's'}` +
    (failed ? ` · ${failed} skipped (see list)` : '');
  showToast(`replaced in ${data.files} file${data.files === 1 ? '' : 's'}` + (failed ? `, ${failed} skipped` : ''), !!failed);
  // open, unmodified tabs pick up the new text now rather than at the next poll
  for (const x of data.results) {
    const doc = !x.error && docs.get(x.path);
    if (doc && !doc.dirty) await reloadDoc(doc);
  }
  runFIF();
}

// === Windows "Open with" (settings) ===
async function refreshAssoc() {
  const api = window.pywebview && window.pywebview.api;
  const field = document.getElementById('assocField');
  if (!api || !api.assoc_status) { field.style.display = 'none'; return; }
  field.style.display = '';
  const st = await api.assoc_status();
  document.getElementById('assocStatus').textContent = !st.supported ? 'Windows only'
    : st.registered ? `registered for ${st.extensions.length} extensions` + (st.current ? '' : ' (other exe path — register again)')
    : 'not registered';
}
async function setAssoc(on) {
  const api = window.pywebview && window.pywebview.api;
  if (!api) return;
  try {
    await (on ? api.assoc_register() : api.assoc_unregister());
    showToast(on ? 'ReadO added to "Open with"' : 'ReadO removed from "Open with"');
  } catch (e) {
    showToast('failed: ' + e.message, true);
  }
  refreshAssoc();
}
function closeDialog(value) {
  document.getElementById('dlgBg').classList.remove('show');
  const r = _dlgResolve;
  _dlgResolve = null;
  if (_dlgFocus && _dlgFocus.isConnected && _dlgFocus.focus) _dlgFocus.focus();
  _dlgFocus = null;
  if (r) r(value);
}

// === External changes: poll open files and expanded folders ===
const _treeMtimes = new Map();
const _treeSkip = new Set();
let _polling = false;
let _pollCount = 0;
function expandedTreeDirs() {
  const out = [''];
  document.querySelectorAll('#tree .children').forEach(c => {
    if (c.style.display === 'block' && c.dataset.loaded) out.push(c.previousElementSibling.dataset.path);
  });
  return out;
}
async function pollChanges() {
  if (_polling || document.hidden) return;
  _polling = true;
  try {
    const r = await fetch('/api/stat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files: [...docs.keys()], dirs: expandedTreeDirs() }),
    });
    if (!r.ok) return;
    const data = await r.json();
    for (const [key, m] of Object.entries(data.files || {})) {
      const doc = docs.get(key);
      if (!doc || doc.saving) continue;
      if (m === null) {
        if (!doc.gone) {
          doc.gone = true;
          renderAllTabs();
          showToast('deleted on disk: ' + baseName(key), true);
        }
        continue;
      }
      if (doc.gone) { doc.gone = false; renderAllTabs(); }
      if (m === doc.mtime) continue;
      if (!doc.dirty) {
        if (await reloadDoc(doc)) showToast('reloaded (changed on disk): ' + baseName(key));
      } else if (!doc.diskChanged) {
        doc.diskChanged = true;
        renderAllTabs();
        showToast('changed on disk: ' + baseName(key) + ' — saving will ask', true);
      }
    }
    for (const [rel, m] of Object.entries(data.dirs || {})) {
      const prev = _treeMtimes.get(rel);
      _treeMtimes.set(rel, m);
      if (prev === undefined || prev === m || m === null) continue;
      if (_treeSkip.delete(rel)) continue;
      await refreshTreeDir(rel);
    }
    for (const key of data.open || []) await openFile(key);
    if ((++_pollCount % 4) === 1) refreshIndexStatus();
  } catch (e) {
  } finally {
    _polling = false;
  }
}
window.readoPollNow = pollChanges;  // reado.py calls this after a drop

// Re-list a folder, keeping its expanded sub-folders open.
async function refreshTreeDir(rel) {
  const node = rel ? document.querySelector(`#tree .node[data-path="${cssEscape(rel)}"]`) : null;
  const container = rel ? node && node.nextElementSibling : document.getElementById('tree');
  if (!container) return;
  const open = [...container.querySelectorAll('.children')]
    .filter(c => c.style.display === 'block' && c.dataset.loaded)
    .map(c => c.previousElementSibling.dataset.path);
  await loadTree(rel, container);
  for (const path of open) {  // document order: parents before children
    const n = container.querySelector(`.node[data-path="${cssEscape(path)}"]`);
    const kids = n && n.nextElementSibling;
    if (!kids || !kids.classList.contains('children')) continue;
    kids.style.display = 'block';
    n.querySelector('.caret').textContent = '▾';
    await loadTree(path, kids);
    kids.dataset.loaded = '1';
  }
  if (currentPath) revealInTree(currentPath);
}

// === Session restore ===
async function restoreSession() {
  const saved = (Array.isArray(STATE.panes) ? STATE.panes : []).slice(0, MAX_PANES);
  try {
    // the saved split tree; older state (no layout) only had a right pane, kept when it had tabs
    let restored = false;
    if (STATE.layout && typeof STATE.layout === 'object' && saved.length > 1 && panes.length === 1) {
      const list = [panes[0]];
      try {
        while (list.length < saved.length) list.push(makePane());
        _layout = deserializeLayout(STATE.layout, list);
        renderLayout();
        restored = true;
      } catch (e) {
        for (const p of list.slice(1)) { p.editor.dispose(); p.paneEl.remove(); }
        _layout = leaf(panes[0]);
      }
    }
    if (!restored && saved.length > 1 && saved[1] && (saved[1].tabs || []).length && panes.length < 2) {
      createPane();
    }
    const keys = new Set();
    saved.forEach(sp => ((sp && sp.tabs) || []).slice(0, 30).forEach(t => t && typeof t.key === 'string' && keys.add(t.key)));
    await Promise.all([...keys].map(k => loadDoc(k).catch(() => null)));  // fetch in parallel
    for (let i = 0; i < Math.min(saved.length, panes.length); i++) {
      const sp = saved[i] || {};
      for (const t of (sp.tabs || []).slice(0, 30)) {
        if (t && keys.has(t.key))
          await openFileInPane(i, t.key, null, null, { background: true, quiet: true, viewState: t.vs, mdSource: t.md });
      }
      const p = panes[i];
      const active = p.tabs.has(sp.active) ? sp.active : [...p.tabs.keys()].pop();
      if (active) switchTabIn(i, active);
    }
    for (const doc of [...docs.values()]) if (doc.refs === 0) { doc.refs = 1; releaseDoc(doc); }
    setActivePane(0);
  } finally {
    _stateReady = true;
  }
}

// === Status bar · edit mode · view options ===
function updateStatus() {
  const doc = currentDoc();
  const p = currentPane();
  const set = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
  set('sbWrap', STATE.wordWrap ? 'wrap' : 'no wrap');
  if (!doc || !p) {
    ['sbMode', 'sbPos', 'sbIndent', 'sbEnc', 'sbEol', 'sbLang'].forEach(id => set(id, ''));
    return;
  }
  set('sbMode', doc.readonly ? 'read-only: ' + doc.readonly
    : STATE.editMode ? (doc.dirty ? 'editing · unsaved' : 'editing') : 'view only');
  const pos = p.editor.getPosition();
  const sel = p.editor.getSelection();
  const selLen = sel && !sel.isEmpty() ? doc.model.getValueLengthInRange(sel) : 0;
  set('sbPos', pos ? `Ln ${pos.lineNumber}, Col ${pos.column}` + (selLen ? ` (${selLen} selected)` : '') : '');
  const o = doc.model.getOptions();
  set('sbIndent', (o.insertSpaces ? 'Spaces: ' : 'Tab: ') + o.tabSize);
  set('sbEnc', String(doc.encoding || '').toUpperCase() + (doc.bom ? ' BOM' : ''));
  set('sbEol', doc.model.getEOL() === '\r\n' ? 'CRLF' : 'LF');
  set('sbLang', doc.model.getLanguageId());
  updateBranch();
}
function applyEditButton() { refreshToolbar(); }
function toggleEditMode() {
  STATE.editMode = !STATE.editMode;
  applyEditButton();
  panes.forEach(applyEditorMode);
  updateStatus();
  saveState();
  showToast(STATE.editMode ? 'editing on — Ctrl+S saves' : 'read-only mode');
}
function editableCurrent() {
  const doc = currentDoc();
  if (!doc) return null;
  if (!canEdit(doc)) {
    showToast(doc.readonly ? 'read-only: ' + doc.readonly : 'turn on editing first (Ctrl+Shift+E)', true);
    return null;
  }
  return doc;
}
function toggleEol() {
  const doc = editableCurrent();
  if (!doc) return;
  const crlf = doc.model.getEOL() === '\r\n';
  doc.model.pushEOL(crlf ? monaco.editor.EndOfLineSequence.LF : monaco.editor.EndOfLineSequence.CRLF);
  updateStatus();
}
async function chooseEncoding() {
  const doc = editableCurrent();
  if (!doc) return;
  const cur = doc.encoding + (doc.bom ? '+bom' : '');
  const v = await askChoice('save encoding',
    `${baseName(doc.key)} is ${String(doc.encoding).toUpperCase()}${doc.bom ? ' with BOM' : ''}.\nSave it as:`,
    [{ label: 'UTF-8', value: 'utf-8' }, { label: 'UTF-8 BOM', value: 'utf-8+bom' },
     { label: 'CP949', value: 'cp949' }, { label: 'cancel', value: 'cancel', primary: true }]);
  if (v === 'cancel' || v === cur) return;
  doc.encoding = v.replace('+bom', '');
  doc.bom = v.endsWith('+bom');
  doc.metaDirty = true;
  updateDirty(doc);
}
function toggleWrap() {
  STATE.wordWrap = !STATE.wordWrap;
  panes.forEach(p => p.editor.updateOptions({ wordWrap: STATE.wordWrap ? 'on' : 'off' }));
  refreshToolbar();
  updateStatus();
  saveState();
}
function zoomFont(delta) {
  STATE.fontSize = delta === 0 ? 13 : Math.max(8, Math.min(32, (STATE.fontSize || 13) + delta));
  panes.forEach(p => p.editor.updateOptions({ fontSize: STATE.fontSize }));
  saveState();
}

// === Navigation history (Alt+Left / Alt+Right) ===
const _nav = { back: [], fwd: [] };
let _navSuppress = false;  // set while ReadO itself moves the cursor after pushNav()
function navPoint() {
  const p = currentPane();
  if (!p || !p.currentPath) return null;
  const pos = p.editor.getPosition() || { lineNumber: 1, column: 1 };
  return { key: p.currentPath, line: pos.lineNumber, col: pos.column, pane: p };
}
function pushNav() {
  const pt = navPoint();
  if (!pt) return;
  _nav.back.push(pt);
  if (_nav.back.length > 50) _nav.back.shift();
  _nav.fwd = [];
}
async function navGo(dir) {
  const from = dir < 0 ? _nav.back : _nav.fwd;
  const to = dir < 0 ? _nav.fwd : _nav.back;
  const pt = from.pop();
  if (!pt) return;
  const cur = navPoint();
  if (cur) to.push(cur);
  // back to the pane the jump started from (a jump may have opened beside)
  const idx = pt.pane ? panes.indexOf(pt.pane) : -1;
  if (await openFileInPane(idx >= 0 ? idx : activePaneIdx, pt.key)) {
    editor.setPosition({ lineNumber: pt.line, column: pt.col });
    editor.revealPositionInCenterIfOutsideViewport({ lineNumber: pt.line, column: pt.col });
    editor.focus();
  }
}

// === Opening files from outside base_dir ===
async function openDialog() {
  const api = window.pywebview && window.pywebview.api;
  if (!api || !api.open_files) { showToast('the open dialog needs the desktop app', true); return; }
  const keys = await api.open_files();
  for (const k of keys || []) await openFile(k);
}
// Dropped files: only reado.py can see their full paths (pywebview drop
// handler on document). Re-dispatch the drop there ourselves so Monaco or any
// other element cannot swallow it.
const hasFiles = e => e.dataTransfer && [...e.dataTransfer.types].includes('Files');
window.addEventListener('dragover', e => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = 'copy';
}, true);
window.addEventListener('drop', e => {
  if (!hasFiles(e) || e._readoForwarded) return;
  e.preventDefault();
  e.stopPropagation();
  if (!window.pywebview) { showToast('drag and drop opens files in the desktop app', true); return; }
  const ev = new DragEvent('drop', { dataTransfer: e.dataTransfer, bubbles: true, cancelable: true });
  ev._readoForwarded = true;
  document.dispatchEvent(ev);
}, true);
window.addEventListener('beforeunload', e => {
  flushState(true);
  if (dirtyDocs().length) { e.preventDefault(); e.returnValue = ''; }
});
window.addEventListener('focus', () => pollChanges());

