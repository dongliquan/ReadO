let _settings = {};

// === Saved UI state ===
// Kept by the server (state.json), not localStorage: pywebview runs WebView2 in
// private mode by default, which wipes localStorage on every exit.
const STATE = Object.assign({
  theme: null, fifRecent: null, recent: [], panes: null,
  wordWrap: false, fontSize: 13, sidebarWidth: null,
}, window.READO_STATE || {});
// Editing is on at every start, whatever an older state.json saved; the
// toggle (Ctrl+Shift+E / ✎) only lasts for the session.
STATE.editMode = true;
try {  // one-off: carry over what older builds kept in localStorage
  if (!STATE.theme) STATE.theme = localStorage.getItem('reado-theme');
  if (!Array.isArray(STATE.fifRecent))
    STATE.fifRecent = JSON.parse(localStorage.getItem('reado-fif-recent') || '[]');
} catch (e) {}
if (!Array.isArray(STATE.fifRecent)) STATE.fifRecent = [];
if (!Array.isArray(STATE.recent)) STATE.recent = [];

let _stateTimer = null;
let _stateReady = false;  // saved tabs are only overwritten once they were restored
function saveState() {
  clearTimeout(_stateTimer);
  _stateTimer = setTimeout(flushState, 800);
}
function snapshotPanes() {
  return panes.map(p => {
    const cur = p.currentPath && p.tabs.get(p.currentPath);
    if (cur && p.editorEl.style.display !== 'none') cur.viewState = p.editor.saveViewState();
    return {
      tabs: [...p.tabs.entries()].map(([key, t]) => ({ key, vs: t.viewState || null, md: !!t.mdSource })),
      active: p.currentPath,
    };
  });
}
function flushState(keepalive) {
  clearTimeout(_stateTimer);
  if (_stateReady) { STATE.panes = snapshotPanes(); STATE.layout = serializeLayout(_layout); }
  return fetch('/api/state', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ui: STATE }), keepalive: !!keepalive,
  }).catch(() => {});
}
function addRecent(key) {
  STATE.recent = [key].concat(STATE.recent.filter(k => k !== key)).slice(0, 30);
  saveState();
}

// === Documents: one Monaco model per file, shared by both panes ===
// doc: { key, model, isMarkdown, mtime, encoding, bom, readonly (reason|null),
//        savedAlt, metaDirty, dirty, refs, diskChanged, gone, saving, html, htmlAlt }
// Keys are paths relative to base_dir, or absolute paths for files the user
// opened from outside it (open dialog, command line, drag and drop).
const docs = new Map();
const isAbsKey = k => /^([A-Za-z]:[\\/]|\\\\|\/\/)/.test(k);
const baseName = k => k.split(/[\\/]/).pop();

async function loadDoc(key) {
  if (docs.has(key)) return docs.get(key);
  const r = await fetch('/api/file?path=' + encodeURIComponent(key));
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    const size = err.size != null ? ` (${fmtSize(err.size)})` : '';
    throw new Error(`${baseName(key)}: ${err.error || 'HTTP ' + r.status}${size}`);
  }
  const data = await r.json();
  if (docs.has(key)) return docs.get(key);  // loaded meanwhile by another call
  if (data.truncated) showToast('read-only — ' + data.readonly, true);
  const model = createDocModel(key, data.text);
  const doc = {
    key, model, isMarkdown: /\.(md|markdown)$/i.test(key) && typeof marked !== 'undefined',
    mtime: data.mtime_ns, encoding: data.encoding, bom: !!data.bom, truncated: !!data.truncated,
    readonly: data.readonly || null, savedAlt: model.getAlternativeVersionId(),
    metaDirty: false, dirty: false, refs: 0, diskChanged: false, gone: false, saving: false,
  };
  model.onDidChangeContent(() => { updateDirty(doc); if (doc === currentDoc()) scheduleOutline(); scheduleGit(doc); });
  docs.set(key, doc);
  scheduleGit(doc, 300);
  return doc;
}
function releaseDoc(doc) {
  if (--doc.refs > 0) return;
  docs.delete(doc.key);
  doc.model.dispose();
  reportDirty();
}
function updateDirty(doc) {
  const d = doc.metaDirty || doc.model.getAlternativeVersionId() !== doc.savedAlt;
  if (d !== doc.dirty) {
    doc.dirty = d;
    renderAllTabs();
    reportDirty();
  }
  if (doc === currentDoc()) updateStatus();
}
function dirtyDocs() { return [...docs.values()].filter(d => d.dirty); }
function reportDirty() {
  const n = dirtyDocs().length;
  document.title = (n ? '● ' : '') + 'ReadO';
  // the desktop shell asks before quitting while n > 0
  try { if (window.pywebview && window.pywebview.api) window.pywebview.api.set_dirty(n); } catch (e) {}
}
function canEdit(doc) { return !!doc && STATE.editMode && !doc.readonly; }
function currentDoc() {
  const p = currentPane();
  return p && p.currentPath ? docs.get(p.currentPath) : null;
}

