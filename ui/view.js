// ===== Keymap presets (VS Code / IntelliJ IDEA) =====
// The registry's own keys are the VS Code set (plus IntelliJ keys that do not
// clash); a preset overrides keys / bindings per command. capture: the key must
// beat Monaco (e.g. Ctrl+F12 is Monaco's "go to implementation").
const KEYMAPS = {
  vscode: { label: 'VS Code', over: {} },
  intellij: { label: 'IntelliJ IDEA', over: {
    'file.new': { keys: 'Alt+Insert', bind: ['Alt+Insert'] },
    'go.symbolFolder': { keys: 'Ctrl+N', bind: ['Ctrl+N', 'Ctrl+Shift+Alt+N', 'Ctrl+T'] },
    'go.file': { keys: 'Ctrl+Shift+N', bind: ['Ctrl+Shift+N', 'Ctrl+P'] },
    'go.symbolFile': { keys: 'Ctrl+F12', bind: ['Ctrl+F12', 'Ctrl+Shift+O'], capture: true },
    'go.definition': { keys: 'Ctrl+B', bind: ['Ctrl+B', 'F12'] },
    'go.peek': { keys: 'Ctrl+Shift+I', bind: ['Ctrl+Shift+I', 'Alt+F12'], capture: true },
    'go.usages': { keys: 'Alt+F7', bind: ['Alt+F7', 'Shift+F12'] },
    'go.back': { keys: 'Ctrl+Alt+←', bind: ['Ctrl+Alt+ArrowLeft', 'Alt+ArrowLeft'] },
    'go.forward': { keys: 'Ctrl+Alt+→', bind: ['Ctrl+Alt+ArrowRight', 'Alt+ArrowRight'] },
    'pane.left': { keys: '', bind: [] }, 'pane.right': { keys: '', bind: [] },
    'edit.replaceInFiles': { keys: 'Ctrl+Shift+R', bind: ['Ctrl+Shift+R', 'Ctrl+Shift+H'] },
    'view.commands': { keys: 'Ctrl+Shift+A', bind: ['Ctrl+Shift+A', 'Ctrl+Shift+P'] },
    'file.closeTab': { keys: 'Ctrl+F4', bind: ['Ctrl+F4', 'Ctrl+W'] },
    'file.settings': { keys: 'Ctrl+Alt+S', bind: ['Ctrl+Alt+S'] },
    'file.rename': { keys: 'Shift+F6', bind: ['Shift+F6'] },
    'file.recent': { keys: 'Ctrl+E', bind: ['Ctrl+E'] },
  } },
};
function applyKeymap(name) {
  const km = KEYMAPS[name] ? name : 'vscode';
  for (const c of COMMANDS) {
    if (!('_defBind' in c)) { c._defKeys = c.keys; c._defBind = c.bind; c._defCapture = !!c.capture; }
    const o = KEYMAPS[km].over[c.id];
    c.keys = o ? o.keys : c._defKeys;
    c.bind = o ? o.bind : c._defBind;
    c.capture = o && 'capture' in o ? o.capture : c._defCapture;
  }
  rebuildBinds();
  STATE.keymap = km;
  return km;
}
// combos bound to more than one command in a preset ([] when clean)
function keymapConflicts(name) {
  const over = (KEYMAPS[name] || KEYMAPS.vscode).over;
  const seen = new Map();
  for (const c of COMMANDS) {
    const bind = over[c.id] ? over[c.id].bind : ('_defBind' in c ? c._defBind : c.bind);
    for (const b of bind || []) seen.set(b, (seen.get(b) || []).concat(c.id));
  }
  return [...seen].filter(([, ids]) => ids.length > 1).map(([combo, ids]) => ({ combo, ids }));
}
function setKeymap(name) {
  applyKeymap(name);
  saveState();
  renderToolbarTitles();
  renderShortcutList();
  showToast(`keymap: ${KEYMAPS[STATE.keymap].label}`);
}
// the settings help: every command with its key in the current keymap
function renderShortcutList() {
  const box = document.getElementById('kbdGenerated');
  if (!box) return;
  const rows = COMMANDS.filter(c => c.keys && (!c.desktop || isDesktop()))
    .map(c => `<div class="kbd-row"><kbd>${escapeHtml(c.keys)}</kbd> <span>${escapeHtml(c.cat + ': ' + c.title)}</span></div>`);
  box.innerHTML = `<div class="kbd-h">${escapeHtml(KEYMAPS[STATE.keymap || 'vscode'].label)} keymap</div>` + rows.join('');
}

// ===== View toggles: minimap, whitespace =====
function toggleMinimap() {
  STATE.minimap = !STATE.minimap;
  panes.forEach(p => p.editor.updateOptions({ minimap: { enabled: !!STATE.minimap } }));
  saveState();
}
function toggleWhitespace() {
  STATE.whitespace = !STATE.whitespace;
  panes.forEach(p => p.editor.updateOptions({ renderWhitespace: STATE.whitespace ? 'all' : 'selection' }));
  saveState();
}

// ===== Reopen with another encoding =====
async function reopenWithEncoding() {
  const doc = currentDoc();
  if (!doc) return;
  if (doc.dirty) return showToast('save or undo the changes first', true);
  const v = await askChoice('reopen with encoding', `${baseName(doc.key)} was read as ${String(doc.encoding).toUpperCase()}. Read it as:`,
    [{ label: 'UTF-8', value: 'utf-8' }, { label: 'CP949 / EUC-KR', value: 'cp949' }, { label: 'UTF-16 LE', value: 'utf-16-le' },
     { label: 'Latin-1', value: 'latin-1' }, { label: 'auto-detect', value: '' }, { label: 'cancel', value: 'cancel', primary: true }]);
  if (v === 'cancel') return;
  doc.forceEncoding = v || null;
  if (await reloadDoc(doc)) showToast(`reopened as ${String(doc.encoding).toUpperCase()}`);
}

// ===== Diff: compare with saved, with git HEAD, with another file =====
let _diff = null;
function openDiff(title, originalText, doc, lang) {
  closeDiff();
  const bg = document.getElementById('diffBg');
  document.getElementById('diffTitle').textContent = title;
  bg.querySelector('.diff-hint').textContent = "left: original · right: the editor's text (edits go to the file)";
  bg.classList.add('show');
  const original = monaco.editor.createModel(originalText, lang || doc.model.getLanguageId());
  const ed = monaco.editor.createDiffEditor(document.getElementById('diffBox'), {
    automaticLayout: true, readOnly: !canEdit(doc), originalEditable: false, renderSideBySide: true,
    fontSize: STATE.fontSize || 13, theme: getTheme() === 'dark' ? 'one-dark' : 'one-light',
  });
  ed.setModel({ original, modified: doc.model });
  _diff = { ed, original };
  setTimeout(() => ed.getModifiedEditor().focus(), 50);
}
function closeDiff() {
  if (!_diff) return;
  _diff.ed.setModel(null);
  _diff.ed.dispose();
  _diff.original.dispose();
  if (_diff.extra) _diff.extra.dispose();  // git views: both sides are their own models
  _diff = null;
  document.getElementById('diffBg').classList.remove('show');
}
async function compareWithSaved() {
  const doc = currentDoc();
  if (!doc) return;
  const r = await fetch('/api/file?path=' + encodeURIComponent(doc.key) + (doc.forceEncoding ? '&encoding=' + doc.forceEncoding : ''));
  if (!r.ok) return showToast('could not read the saved file', true);
  openDiff(`${baseName(doc.key)}: saved ↔ editor`, (await r.json()).text, doc);
}
async function compareWithHead() {
  const doc = currentDoc();
  if (!doc) return;
  const r = await postJson('/api/git-changes', { path: doc.key, text: doc.model.getValue(), want_head: true });
  if (!r.ok || !r.data.repo) return showToast('not in a git repository (or git is not installed)', true);
  if (r.data.head == null) return showToast('this file is not in HEAD yet', true);
  openDiff(`${baseName(doc.key)}: HEAD (${r.data.branch}) ↔ editor`, r.data.head, doc);
}
function compareWithFile() {
  const doc = currentDoc();
  if (!doc) return;
  pickAnyFile(`compare ${baseName(doc.key)} with…`, async path => {
    const r = await fetch('/api/file?path=' + encodeURIComponent(path));
    if (!r.ok) return showToast('could not read ' + path, true);
    openDiff(`${path} ↔ ${baseName(doc.key)}`, (await r.json()).text, doc);
  });
}
// Quick Open as a chooser over every file
let _qoFileHandler = null;
function pickAnyFile(title, onPick) {
  openQO('');
  _qoFileHandler = onPick;
  document.getElementById('qoInput').placeholder = title + ' — type a file name, Enter';
}

// ===== Git: changed-line markers against HEAD, branch in the status bar =====
const _gitTimers = new Map();
function scheduleGit(doc, delay) {
  if (!doc || doc.gitRepo === false) return;
  clearTimeout(_gitTimers.get(doc.key));
  _gitTimers.set(doc.key, setTimeout(() => refreshGit(doc), delay == null ? 1200 : delay));
}
async function refreshGit(doc) {
  if (!docs.has(doc.key) || doc.model.isDisposed()) return;
  const r = await postJson('/api/git-changes', { path: doc.key, text: doc.model.getValue() });
  if (!r.ok || !docs.has(doc.key) || doc.model.isDisposed()) return;
  const g = r.data;
  doc.gitRepo = !!g.repo;
  doc.gitBranch = g.branch || '';
  const decos = [];
  const add = (from, to, cls, msg) => decos.push({ range: new monaco.Range(from, 1, Math.max(from, to), 1),
    options: { isWholeLine: true, linesDecorationsClassName: cls, overviewRuler: { color: cls === 'git-add' ? '#2ea043' : cls === 'git-mod' ? '#3b82f6' : '#e5534b', position: 1 },
               linesDecorationsTooltip: msg } });
  for (const [a, b] of g.added || []) add(a, b, 'git-add', g.untracked ? 'not in git yet' : 'added since HEAD');
  for (const [a, b] of g.modified || []) add(a, b, 'git-mod', 'changed since HEAD');
  for (const l of g.deleted || []) add(Math.min(l, doc.model.getLineCount()), Math.min(l, doc.model.getLineCount()), 'git-del', 'lines deleted here');
  doc.gitDecos = doc.model.deltaDecorations(doc.gitDecos || [], decos);
  if (currentDoc() === doc) updateBranch();
}
function updateBranch() {
  const el = document.getElementById('sbBranch');
  const doc = currentDoc();
  if (el) el.textContent = doc && doc.gitRepo && doc.gitBranch ? '⎇ ' + doc.gitBranch : '';
}

// ===== Usages count on a declaration (hover) =====
const _refCount = new Map();  // symbol|file -> {t, n}
async function usageCount(symbol, key) {
  const k = symbol + '|' + key;
  const hit = _refCount.get(k);
  if (hit && Date.now() - hit.t < 30000) return hit.n;
  let n = null;
  try {
    const r = await fetch(`/api/refs?symbol=${encodeURIComponent(symbol)}&from=${encodeURIComponent(isAbsKey(key) ? '' : key)}`);
    if (r.ok) { const d = await r.json(); n = { n: (d.results || []).filter(x => !x.decl).length, more: !!d.truncated }; }
  } catch (e) {}
  _refCount.set(k, { t: Date.now(), n });
  return n;
}

// ===== Toolbar: grouped, every button is a registry command =====
function renderToolbarTitles() {
  document.querySelectorAll('#tbGroups [data-cmd]').forEach(b => {
    if (b.id === 'themeBtn') return;  // names the current mode: refreshToolbar
    const c = CMD.get(b.dataset.cmd);
    if (c) b.title = c.title.replace(/…$/, '') + (c.keys ? ` (${c.keys})` : '');
  });
  refreshToolStrip();
}
function refreshToolbar() {
  const set = (id, on) => { const b = document.getElementById(id); if (b) b.classList.toggle('active', !!on); };
  set('editBtn', STATE.editMode);
  set('wrapBtn', STATE.wordWrap);
  set('splitBtn', panes.length > 1);
  const lbl = document.querySelector('#editBtn .lbl');
  if (lbl) lbl.textContent = STATE.editMode ? 'Editing' : 'Edit';
  const tb = document.getElementById('themeBtn');
  if (tb && TB_ICONS) {
    const m = getThemeMode();
    tb.innerHTML = TB_ICONS[m] + `<span class="lbl">${THEME_LABEL[m]}</span>`;
    tb.title = `Theme: ${THEME_LABEL[m]} — click to switch (Light → Dark → System)`;
  }
}
var TB_ICONS = {  // var: refreshToolbar may run before this line (theme / edit mode at startup)
  system: '<svg viewBox="0 0 16 16" width="15" height="15"><rect x="1.5" y="2.5" width="13" height="8.5" rx="1.2" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M5.5 14h5M8 11v3" stroke="currentColor" stroke-width="1.3"/></svg>',
  light: '<svg viewBox="0 0 16 16" width="15" height="15"><circle cx="8" cy="8" r="3" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M8 1v2M8 13v2M1 8h2M13 8h2M3 3l1.4 1.4M11.6 11.6L13 13M13 3l-1.4 1.4M4.4 11.6L3 13" stroke="currentColor" stroke-width="1.3"/></svg>',
  dark: '<svg viewBox="0 0 16 16" width="15" height="15"><path d="M13 9.5A5.5 5.5 0 0 1 6.5 3a5.5 5.5 0 1 0 6.5 6.5z" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>',
};
function toolbarOverflowMenu(e) {
  const r = e.currentTarget.getBoundingClientRect();
  const hidden = [...document.querySelectorAll('#tbGroups [data-cmd], #tbGroups #splitBtn')].filter(b => b.offsetParent === null);
  const items = hidden.map(b => b.id === 'splitBtn'
    ? { label: 'Layout…', run: () => layoutMenu({ currentTarget: e.currentTarget }) }
    : { label: CMD.get(b.dataset.cmd).title, hint: CMD.get(b.dataset.cmd).keys || '', run: () => runCommand(b.dataset.cmd) });
  if (items.length) showMenu(r.left, r.bottom + 2, items);
}
// narrow window: labels go first, then the less used groups move into "…"
function fitToolbar() {
  const bar = document.querySelector('.topbar');
  if (!bar) return;
  // the breadcrumb (current file path) keeps at least ~180px before buttons fold
  const crumbs = bar.querySelector('.crumbs');
  const tight = () => bar.scrollWidth > bar.clientWidth + 1 || (crumbs && crumbs.getBoundingClientRect().width < 180);
  bar.classList.remove('compact', 'tiny');
  if (tight()) bar.classList.add('compact');
  if (tight()) bar.classList.add('tiny');
}
(() => {
  document.querySelectorAll('#tbGroups [data-cmd]').forEach(b => b.addEventListener('click', () => runCommand(b.dataset.cmd)));
  new ResizeObserver(() => fitToolbar()).observe(document.querySelector('.topbar'));
  new ResizeObserver(() => fitSearchLabel()).observe(document.querySelector('.tb-search'));
})();
// title-bar search label: the longest that fits — Find File and Find in Files go last
const SEARCH_LABELS = [
  'Search files (Ctrl+P) · Find in Files (Ctrl+Shift+F) · Commands (Ctrl+Shift+P)',
  'Search files (Ctrl+P) · Find in Files (Ctrl+Shift+F)',
  'Files Ctrl+P · In Files Ctrl+Shift+F',
  'Files · In Files',
  'Search',
];
function fitSearchLabel() {
  const el = document.getElementById('tbSearchLbl');
  if (!el) return;
  for (const t of SEARCH_LABELS) {
    el.textContent = t;
    if (el.scrollWidth <= el.clientWidth + 1) return;
  }
}
applyKeymap(STATE.keymap);
async function toggleGitignore() {
  const r = await postJson('/api/settings', { respect_gitignore: !_settings.respect_gitignore });
  if (!r.ok) return showToast('could not change the setting', true);
  _settings = r.data;
  await loadTree('', document.getElementById('tree'));
  showToast(_settings.respect_gitignore ? '.gitignore\'d files are hidden (tree, Quick Open, search)' : '.gitignore\'d files are shown again');
}

document.getElementById('fifRepl').addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.preventDefault(); previewReplace(); }
  else if (e.key === 'Escape') { e.preventDefault(); dismissFD(); }
});
async function loadProjects() {
  try {
    const r = await fetch('/api/projects');
    const data = await r.json();
    const fifSel = document.getElementById('fifScope');
    const fill = sel => {
      if (!sel) return;
      sel.innerHTML = '<option value="">whole folder</option>'
        + '<option value="@cur">folder of the current file</option>';
      for (const p of data.projects || []) {
        const opt = document.createElement('option');
        opt.value = p; opt.textContent = p + '/';
        sel.appendChild(opt);
      }
    };
    fill(fifSel);
  } catch (e) {}
}

