// === Panes & Tabs (split view) ===
// Each pane: { tabs: Map<key, {viewState, mdSource}>, currentPath, tabsEl, editorEl, previewEl, mdBtn, editor, paneEl }
const panes = [];
let activePaneIdx = 0;

function currentPane() { return panes[activePaneIdx]; }
Object.defineProperty(window, 'currentPath', {
  get() { const p = currentPane(); return p ? p.currentPath : null; },
});
Object.defineProperty(window, 'editor', {
  get() { const p = currentPane(); return p ? p.editor : null; },
});

// A pane's DOM + editor, not yet placed in the layout.
function makePane() {
  const paneEl = document.createElement('div');
  paneEl.className = 'pane';
  const tabsEl = document.createElement('div');
  tabsEl.className = 'tabs';
  const editorEl = document.createElement('div');
  editorEl.className = 'pane-editor';
  const previewEl = document.createElement('div');
  previewEl.className = 'pane-preview md-body';
  previewEl.style.display = 'none';
  const bannerEl = document.createElement('div');
  bannerEl.className = 'pane-banner';
  bannerEl.style.display = 'none';
  const mdBtn = document.createElement('button');
  mdBtn.className = 'pane-md';
  mdBtn.style.display = 'none';
  mdBtn.title = 'markdown: source / preview';
  const emptyEl = document.createElement('div');
  emptyEl.className = 'pane-empty';
  emptyEl.textContent = 'empty pane — Ctrl+P opens a file here, or drag a tab in';
  paneEl.appendChild(tabsEl);
  paneEl.appendChild(bannerEl);
  paneEl.appendChild(editorEl);
  paneEl.appendChild(previewEl);
  paneEl.appendChild(emptyEl);
  paneEl.appendChild(mdBtn);
  document.getElementById('paneRoot').appendChild(paneEl);  // placed for real by renderLayout

  const editorInst = monaco.editor.create(editorEl, {
    value: '', language: 'plaintext',
    readOnly: true, automaticLayout: true,
    minimap: { enabled: !!STATE.minimap },
    fontFamily: '"D2Coding", "D2Coding ligature", ui-monospace, "JetBrains Mono", Consolas, monospace',
    fontSize: STATE.fontSize || 13, lineNumbers: 'on',
    renderWhitespace: STATE.whitespace ? 'all' : 'selection', scrollBeyondLastLine: false,
    wordWrap: STATE.wordWrap ? 'on' : 'off',
    dropIntoEditor: { enabled: false },  // dropped files open as tabs instead
    theme: getTheme() === 'dark' ? 'one-dark' : 'one-light',
  });

  const pane = { tabs: new Map(), currentPath: null, tabsEl, bannerEl, editorEl, previewEl, mdBtn, emptyEl,
                 editor: editorInst, paneEl };
  mdBtn.onclick = () => toggleMarkdownSource(panes.indexOf(pane));
  previewEl.addEventListener('click', e => onPreviewClick(pane, e));
  // focus pane on editor click (capture phase to beat Monaco internals)
  // skip when click is in the tabs bar — tab click handlers re-render and would lose the click
  const activate = e => {
    if (e && e.target && e.target.closest && e.target.closest('.tabs')) return;
    setActivePane(panes.indexOf(pane));
  };
  paneEl.addEventListener('mousedown', activate, true);
  // also when editor gains focus internally
  editorInst.onDidFocusEditorWidget(activate);
  editorInst.onDidChangeCursorSelection(() => {
    if (pane === currentPane()) updateStatus();
    saveState();
  });
  let lastPos = null;
  editorInst.onDidChangeModel(() => { lastPos = null; });
  attachComponentMouse(pane);
  attachTabDrop(pane);
  editorInst.onDidChangeCursorPosition(e => {
    if (e.source === 'code.jump' && lastPos && !_navSuppress && pane.currentPath) {
      _nav.back.push({ key: pane.currentPath, line: lastPos.lineNumber, col: lastPos.column, pane });
      if (_nav.back.length > 50) _nav.back.shift();
      _nav.fwd = [];
    }
    lastPos = e.position;
  });
  applyEditorMode(pane);
  return pane;
}

// === Pane layout: a small split tree, at most MAX_PANES panes ===
// node = { pane } (leaf) | { dir: 'row' | 'col', kids: [node], sizes: [fractions] }
// `panes` always lists the leaves in reading order (left→right, top→bottom), so
// pane indices, Ctrl+1..4 and "next pane" follow what is on screen.
const MAX_PANES = 4;
let _layout = null;
const LAYOUT_PRESETS = {
  single: { label: 'single', n: 1, build: L => L[0] },
  cols2: { label: 'two columns', n: 2, build: L => splitNode('row', L.slice(0, 2)) },
  cols3: { label: 'three columns', n: 3, build: L => splitNode('row', L.slice(0, 3)) },
  rows2: { label: 'two rows', n: 2, build: L => splitNode('col', L.slice(0, 2)) },
  grid: { label: 'grid 2 × 2', n: 4, build: L => splitNode('col', [splitNode('row', L.slice(0, 2)), splitNode('row', L.slice(2, 4))]) },
};
function splitNode(dir, kids) { return { dir, kids, sizes: kids.map(() => 1 / kids.length) }; }
function leaf(pane) { return { pane }; }
function layoutLeaves(n, out) {
  out = out || [];
  if (!n) return out;
  if (n.pane) out.push(n.pane);
  else n.kids.forEach(k => layoutLeaves(k, out));
  return out;
}
function findParent(n, pane) {  // -> {parent, index} of the leaf holding pane (parent null = root)
  if (!n || n.pane) return null;
  for (let i = 0; i < n.kids.length; i++) {
    const k = n.kids[i];
    if (k.pane === pane) return { parent: n, index: i };
    const r = findParent(k, pane);
    if (r) return r;
  }
  return null;
}
// a node with one child is replaced by that child; a child split in the same
// direction as its parent is merged into it
function normalizeLayout(n) {
  if (!n || n.pane) return n;
  n.kids = n.kids.map(normalizeLayout);
  const kids = [], sizes = [];
  n.kids.forEach((k, i) => {
    if (!k.pane && k.dir === n.dir) k.kids.forEach((g, j) => { kids.push(g); sizes.push(n.sizes[i] * k.sizes[j]); });
    else { kids.push(k); sizes.push(n.sizes[i]); }
  });
  const sum = sizes.reduce((a, b) => a + b, 0) || 1;
  n.kids = kids; n.sizes = sizes.map(s => s / sum);
  return n.kids.length === 1 ? n.kids[0] : n;
}
function renderLayout() {
  const root = document.getElementById('paneRoot');
  const active = panes[activePaneIdx];
  _layout = normalizeLayout(_layout);
  const build = (n, size) => {
    let el;
    if (n.pane) {
      el = n.pane.paneEl;
    } else {
      el = document.createElement('div');
      el.className = 'split ' + n.dir;
      n._els = [];
      n.kids.forEach((k, i) => {
        if (i) {
          const sash = document.createElement('div');
          sash.className = 'sash';
          sash.addEventListener('mousedown', e => startSashDrag(e, n, i - 1, el));
          el.appendChild(sash);
        }
        const kel = build(k, n.sizes[i]);
        n._els.push(kel);
        el.appendChild(kel);
      });
    }
    el.style.flex = `${size} 1 0`;
    return el;
  };
  const top = build(_layout, 1);
  root.replaceChildren(top);
  panes.splice(0, panes.length, ...layoutLeaves(_layout));
  activePaneIdx = Math.max(0, panes.indexOf(active));
  try { refreshToolbar(); } catch (e) {}
  setActivePane(activePaneIdx);
  renderAllTabs();
  saveState();
}
function serializeLayout(n) {
  if (!n) return null;
  if (n.pane) return panes.indexOf(n.pane);
  return { d: n.dir, k: n.kids.map(serializeLayout), s: n.sizes.map(x => Math.round(x * 1000) / 1000) };
}
// saved tree -> node over the given panes (indices must cover 0..n-1 once each)
function deserializeLayout(s, list) {
  const seen = new Set();
  const walk = x => {
    if (typeof x === 'number') {
      if (!list[x] || seen.has(x)) throw new Error('bad leaf');
      seen.add(x);
      return leaf(list[x]);
    }
    if (!x || (x.d !== 'row' && x.d !== 'col') || !Array.isArray(x.k) || x.k.length < 2) throw new Error('bad node');
    const kids = x.k.map(walk);
    const sizes = Array.isArray(x.s) && x.s.length === kids.length && x.s.every(v => v > 0.02) ? x.s.slice() : kids.map(() => 1 / kids.length);
    return { dir: x.d, kids, sizes };
  };
  const n = walk(s);
  if (seen.size !== list.length) throw new Error('missing leaves');
  return n;
}
let _sashDrag = null;
function startSashDrag(e, node, i, el) {
  e.preventDefault();
  const sum = node.sizes[i] + node.sizes[i + 1];
  const before = node.sizes.slice(0, i).reduce((a, b) => a + b, 0);
  _sashDrag = { node, i, el, sum, before, sash: e.target };
  e.target.classList.add('drag');
  document.body.style.cursor = node.dir === 'row' ? 'col-resize' : 'row-resize';
}
window.addEventListener('mousemove', e => {
  const d = _sashDrag;
  if (!d) return;
  const r = d.el.getBoundingClientRect();
  const total = d.node.sizes.reduce((a, b) => a + b, 0);
  const pos = d.node.dir === 'row' ? (e.clientX - r.left) / r.width : (e.clientY - r.top) / r.height;
  const min = 0.08 * total;
  const a = Math.max(min, Math.min(d.sum - min, pos * total - d.before));
  d.node.sizes[d.i] = a;
  d.node.sizes[d.i + 1] = d.sum - a;
  d.node._els[d.i].style.flex = `${a} 1 0`;
  d.node._els[d.i + 1].style.flex = `${d.sum - a} 1 0`;
});
window.addEventListener('mouseup', () => {
  if (!_sashDrag) return;
  _sashDrag.sash.classList.remove('drag');
  _sashDrag = null;
  document.body.style.cursor = '';
  saveState();
});

// First pane, or (from older callers) one more pane to the right of the last one.
function createPane() {
  if (!_layout) {
    const p = makePane();
    _layout = leaf(p);
    renderLayout();
    return p;
  }
  return splitPane(panes.length - 1, 'row');
}
// Split pane idx to the right ('row') or downwards ('col'); the new pane gets
// key (if given) and focus. Null when the layout is full.
function splitPane(idx, dir, key) {
  if (panes.length >= MAX_PANES) { showToast(`at most ${MAX_PANES} panes — close one or pick a layout`, true); return null; }
  const src = panes[idx] || panes[activePaneIdx];
  const p = makePane();
  const at = findParent(_layout, src);
  if (!at) {
    _layout = splitNode(dir, [_layout, leaf(p)]);
  } else if (at.parent.dir === dir) {  // share the source pane's space
    const half = at.parent.sizes[at.index] / 2;
    at.parent.kids.splice(at.index + 1, 0, leaf(p));
    at.parent.sizes.splice(at.index, 1, half, half);
  } else {
    at.parent.kids[at.index] = splitNode(dir, [leaf(src), leaf(p)]);
  }
  renderLayout();
  setActivePane(panes.indexOf(p));
  if (key) openFileInPane(panes.indexOf(p), key);
  return p;
}
// Split the active pane, showing its file on both sides (Ctrl+\ / Ctrl+Alt+\).
function splitActive(dir) {
  const p = currentPane();
  return splitPane(activePaneIdx, dir, p && p.currentPath);
}
function toggleSplit() { splitActive('row'); }

function applyLayoutPreset(name) {
  const preset = LAYOUT_PRESETS[name];
  if (!preset) return;
  while (panes.length > preset.n) closePane(panes.length - 1);
  const list = panes.slice();
  while (list.length < preset.n) list.push(makePane());
  _layout = preset.build(list.map(leaf));
  renderLayout();
}

function applyEditorMode(p) {
  const doc = p.currentPath ? docs.get(p.currentPath) : null;
  const msg = !doc ? 'no file open'
    : doc.readonly ? 'Read-only: ' + doc.readonly
    : 'Read-only mode — press Ctrl+Shift+E or the EDIT button to edit';
  p.editor.updateOptions({ readOnly: !canEdit(doc), readOnlyMessage: { value: msg } });
}

function setActivePane(idx) {
  if (idx < 0 || idx >= panes.length) return;
  const same = activePaneIdx === idx;
  activePaneIdx = idx;
  panes.forEach((p, i) => p.paneEl.classList.toggle('active', i === idx));
  if (!same) renderAllTabs();
  const p = currentPane();
  document.getElementById('crumbs').innerHTML =
    p && p.currentPath ? renderCrumbs(p.currentPath) : 'no file open';
  if (p && p.currentPath) revealInTree(p.currentPath);
  updateStatus();
}
// Ctrl+1..4, Ctrl+Alt+arrows: focus a pane (its editor, or its preview)
function focusPane(idx) {
  const p = panes[idx];
  if (!p) return false;
  setActivePane(idx);
  if (p.editorEl.style.display !== 'none') p.editor.focus();
  else p.previewEl.focus();
  return true;
}
// nearest pane in a direction ('left' | 'right' | 'up' | 'down'), by geometry
function paneInDirection(idx, dir) {
  const a = panes[idx] && panes[idx].paneEl.getBoundingClientRect();
  if (!a) return -1;
  let best = -1, bestScore = Infinity;
  panes.forEach((p, i) => {
    if (i === idx) return;
    const b = p.paneEl.getBoundingClientRect();
    const horiz = dir === 'left' || dir === 'right';
    const gap = dir === 'right' ? b.left - a.right : dir === 'left' ? a.left - b.right
      : dir === 'down' ? b.top - a.bottom : a.top - b.bottom;
    if (gap < -8) return;  // not on that side
    const overlap = horiz ? Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
                          : Math.min(a.right, b.right) - Math.max(a.left, b.left);
    if (overlap <= 0) return;
    const score = gap * 1000 - overlap;
    if (score < bestScore) { bestScore = score; best = i; }
  });
  return best;
}

// Close a pane: its tabs close, except unsaved ones only it holds — those move
// to the neighbouring pane. The rest of the layout takes the space.
function closePane(idx) {
  if (panes.length <= 1) return;
  const p = panes[idx];
  if (!p) return;
  const other = panes[idx > 0 ? idx - 1 : 1];
  for (const [key, t] of p.tabs) {
    const doc = docs.get(key);
    if (!doc) continue;
    if (doc.dirty && doc.refs === 1 && !other.tabs.has(key)) {
      other.tabs.set(key, t);  // keep unsaved work: move the tab instead of dropping it
    } else {
      releaseDoc(doc);
    }
  }
  const at = findParent(_layout, p);
  at.parent.kids.splice(at.index, 1);
  at.parent.sizes.splice(at.index, 1);
  p.editor.dispose();
  p.paneEl.remove();
  const wasActive = idx === activePaneIdx;
  if (wasActive) activePaneIdx = panes.indexOf(other);
  renderLayout();
  if (!other.currentPath && other.tabs.size) switchTabIn(panes.indexOf(other), [...other.tabs.keys()].pop());
}

// === Moving tabs between panes ===
// Insert key into pane p's tab list before `beforeKey` (end when null).
function placeTab(p, key, tab, beforeKey) {
  const entries = [...p.tabs.entries()].filter(([k]) => k !== key);
  const at = beforeKey && beforeKey !== key ? entries.findIndex(([k]) => k === beforeKey) : -1;
  entries.splice(at < 0 ? entries.length : at, 0, [key, tab]);
  p.tabs.clear();
  for (const [k, v] of entries) p.tabs.set(k, v);
}
// Move (or with copy, duplicate) a tab to another pane; within one pane it reorders.
async function moveTab(fromIdx, key, toIdx, copy, beforeKey) {
  const src = panes[fromIdx], dst = panes[toIdx];
  if (!src || !dst || !src.tabs.has(key)) return false;
  const t = src.tabs.get(key);
  if (src === dst) {
    placeTab(src, key, t, beforeKey);
    renderTabsFor(fromIdx);
    saveState();
    return true;
  }
  const doc = docs.get(key);
  if (!doc) return false;
  if (!dst.tabs.has(key)) {
    const live = src.currentPath === key && src.editorEl.style.display !== 'none';
    doc.refs++;
    placeTab(dst, key, { viewState: live ? src.editor.saveViewState() : t.viewState, mdSource: t.mdSource }, beforeKey);
  } else if (beforeKey) {
    placeTab(dst, key, dst.tabs.get(key), beforeKey);
  }
  if (!copy) await closeTabIn(fromIdx, key, true);  // the doc is still held by dst
  const to = panes.indexOf(dst);
  setActivePane(to);
  switchTabIn(to, key);
  if (dst.editorEl.style.display !== 'none') dst.editor.focus();
  saveState();
  return true;
}
// Ctrl+Alt+PageDown / PageUp: send the active tab to the next / previous pane
// (a single pane is split to the right first).
async function sendTabToPane(step) {
  const from = activePaneIdx;
  const p = panes[from];
  if (!p || !p.currentPath) return false;
  const key = p.currentPath;
  if (panes.length < 2) {
    const np = splitPane(from, 'row');
    if (!np) return false;
    return moveTab(panes.indexOf(p), key, panes.indexOf(np), false);
  }
  const to = (from + step + panes.length) % panes.length;
  return moveTab(from, key, to, false);
}

// drag a tab onto another pane (Ctrl: copy) or onto another tab (insert before it)
let _dragTab = null;  // {pane, key}
const isTabDrag = e => e.dataTransfer && [...e.dataTransfer.types].includes('application/x-reado-tab');
function attachTabDrop(pane) {
  const el = pane.paneEl;
  const clear = () => {
    el.classList.remove('drop-target');
    el.querySelectorAll('.tab-item.drop-before').forEach(x => x.classList.remove('drop-before'));
  };
  el.addEventListener('dragover', e => {
    if (!isTabDrag(e) || !_dragTab) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = e.ctrlKey ? 'copy' : 'move';
    el.classList.add('drop-target');
    const over = e.target.closest && e.target.closest('.tab-item');
    el.querySelectorAll('.tab-item.drop-before').forEach(x => { if (x !== over) x.classList.remove('drop-before'); });
    if (over) over.classList.add('drop-before');
  }, true);
  el.addEventListener('dragleave', e => { if (!el.contains(e.relatedTarget)) clear(); }, true);
  el.addEventListener('drop', e => {
    if (!isTabDrag(e) || !_dragTab) return;
    e.preventDefault();
    e.stopPropagation();
    const over = e.target.closest && e.target.closest('.tab-item');
    const before = over ? over.dataset.key : null;
    const d = _dragTab;
    _dragTab = null;
    clear();
    moveTab(panes.indexOf(d.pane), d.key, panes.indexOf(pane), e.ctrlKey, before);
  }, true);
}

// === Small context menu (tabs, layout button) ===
// items: [{label, hint, run, disabled}] or 'sep'
function showMenu(x, y, items) {
  closeMenu();
  const m = document.createElement('div');
  m.className = 'ctx-menu';
  m.id = 'ctxMenu';
  for (const it of items) {
    if (it === 'sep') { m.appendChild(Object.assign(document.createElement('div'), { className: 'ctx-sep' })); continue; }
    const row = document.createElement('div');
    row.className = 'ctx-item' + (it.disabled ? ' disabled' : '') + (it.checked ? ' checked' : '');
    row.dataset.label = it.label;
    row.innerHTML = `<span>${escapeHtml(it.label)}</span><span class="ctx-hint">${escapeHtml(it.hint || '')}</span>`;
    row.addEventListener('mousedown', e => e.preventDefault());
    row.addEventListener('click', () => { closeMenu(); if (!it.disabled) it.run(); });
    m.appendChild(row);
  }
  document.body.appendChild(m);
  const r = m.getBoundingClientRect();
  m.style.left = Math.max(4, Math.min(x, window.innerWidth - r.width - 4)) + 'px';
  m.style.top = Math.max(4, Math.min(y, window.innerHeight - r.height - 4)) + 'px';
}
function closeMenu() { const m = document.getElementById('ctxMenu'); if (m) m.remove(); }
window.addEventListener('mousedown', e => { if (!(e.target.closest && e.target.closest('#ctxMenu'))) closeMenu(); }, true);
window.addEventListener('blur', closeMenu);

function tabMenu(e, paneIdx, key) {
  e.preventDefault();
  const full = panes.length >= MAX_PANES;
  const items = [
    { label: 'split right', hint: 'Ctrl+\\', disabled: full, run: () => splitPane(paneIdx, 'row', key) },
    { label: 'split down', hint: 'Ctrl+Alt+\\', disabled: full, run: () => splitPane(paneIdx, 'col', key) },
    'sep',
  ];
  panes.forEach((_, i) => {
    if (i !== paneIdx) items.push({ label: `move to pane ${i + 1}`, hint: i === (paneIdx + 1) % panes.length ? 'Ctrl+Alt+PgDn' : '',
                                     run: () => moveTab(paneIdx, key, i, false) });
  });
  panes.forEach((_, i) => {
    if (i !== paneIdx) items.push({ label: `copy to pane ${i + 1}`, hint: 'Ctrl+drag', run: () => moveTab(paneIdx, key, i, true) });
  });
  if (panes.length > 1) items.push('sep');
  const p = panes[paneIdx];
  const keys = [...p.tabs.keys()];
  const closeMany = async list => { for (const k of list) if (!(await closeTabIn(panes.indexOf(p), k))) break; };
  items.push({ label: 'close', hint: CMD.get('file.closeTab').keys, run: () => closeTabIn(paneIdx, key) },
    { label: 'close others', disabled: keys.length < 2, run: () => closeMany(keys.filter(k => k !== key)) },
    { label: 'close to the right', disabled: keys.indexOf(key) === keys.length - 1, run: () => closeMany(keys.slice(keys.indexOf(key) + 1)) },
    { label: 'close all', run: () => closeMany(keys) },
    'sep',
    { label: 'copy path', run: () => copyText(fullPathOf(key)) },
    { label: 'copy relative path', disabled: isAbsKey(key), run: () => copyText(key, 'relative path') },
    { label: 'reveal in tree', disabled: isAbsKey(key), run: () => { setSideTab('files'); revealInTree(key).then(() => treeSelect(key)); } },
    { label: 'reveal in Explorer', disabled: !isDesktop(), run: () => revealInExplorer(key) },
    { label: 'compare with saved', run: () => { switchTabIn(paneIdx, key); compareWithSaved(); } });
  showMenu(e.clientX, e.clientY, items);
}
function layoutMenu(e) {
  const r = e.currentTarget.getBoundingClientRect();
  const full = panes.length >= MAX_PANES;
  const items = Object.entries(LAYOUT_PRESETS).map(([name, p]) => ({ label: p.label, run: () => applyLayoutPreset(name) }));
  items.push('sep',
    { label: 'split right', hint: 'Ctrl+\\', disabled: full, run: () => splitActive('row') },
    { label: 'split down', hint: 'Ctrl+Alt+\\', disabled: full, run: () => splitActive('col') },
    { label: 'close this pane', disabled: panes.length < 2, run: () => closePane(activePaneIdx) });
  showMenu(r.left, r.bottom + 2, items);
}

function renderAllTabs() { panes.forEach((_, i) => renderTabsFor(i)); updateStartScreen(); }
function renderTabsFor(paneIdx) {
  const p = panes[paneIdx];
  if (!p) return;
  const t = p.tabsEl;
  t.innerHTML = '';
  p.paneEl.classList.toggle('empty', !p.tabs.size);
  if (panes.length > 1) {  // pane number for Ctrl+1..4
    const num = document.createElement('span');
    num.className = 'pane-num';
    num.textContent = paneIdx + 1;
    num.title = `pane ${paneIdx + 1} — Ctrl+${paneIdx + 1}`;
    t.appendChild(num);
  }
  for (const path of p.tabs.keys()) {
    const doc = docs.get(path);
    const name = baseName(path);
    const isActive = path === p.currentPath;

    const tab = document.createElement('div');
    tab.className = 'tab-item' + (isActive ? ' active' : '')
      + (doc && doc.dirty ? ' dirty' : '')
      + (doc && doc.diskChanged ? ' stale' : '')
      + (doc && doc.gone ? ' gone' : '');
    tab.title = path
      + (doc && doc.readonly ? '\nread-only: ' + doc.readonly : '')
      + (doc && doc.diskChanged ? '\nchanged on disk since opened' : '')
      + (doc && doc.gone ? '\ndeleted on disk' : '')
      + '\ndouble-click the name: source full width (sidebar away) / back';

    const nameEl = document.createElement('span');
    nameEl.className = 'tab-name';
    nameEl.innerHTML = fileBadge(name) + escapeHtml(name);
    nameEl.addEventListener('click', e => {
      e.stopPropagation();
      setActivePane(paneIdx);
      switchTabIn(paneIdx, path);
    });

    const closeEl = document.createElement('span');
    closeEl.className = 'tab-close';
    closeEl.textContent = '×';
    closeEl.title = 'close';
    closeEl.addEventListener('click', e => {
      e.stopPropagation();
      e.preventDefault();
      closeTabIn(paneIdx, path);
    });

    tab.appendChild(nameEl);
    tab.appendChild(closeEl);
    // background click on the tab (non-name, non-close) also switches
    tab.addEventListener('click', () => {
      setActivePane(paneIdx);
      switchTabIn(paneIdx, path);
    });
    // middle-click closes
    tab.addEventListener('mousedown', e => {
      if (e.button === 1) { e.preventDefault(); closeTabIn(paneIdx, path); }
    });
    tab.addEventListener('contextmenu', e => tabMenu(e, panes.indexOf(p), path));
    // drag to another pane (move; Ctrl: copy) or onto a tab (reorder)
    tab.dataset.key = path;
    tab.draggable = true;
    tab.addEventListener('dragstart', e => {
      _dragTab = { pane: p, key: path };
      e.dataTransfer.setData('application/x-reado-tab', path);
      e.dataTransfer.effectAllowed = 'copyMove';
    });
    tab.addEventListener('dragend', () => { _dragTab = null; });

    t.appendChild(tab);
    if (isActive) tab.scrollIntoView({ inline: 'nearest', block: 'nearest' });
  }
  updateStartScreen();
}

function switchTabIn(paneIdx, path) {
  const p = panes[paneIdx];
  const doc = docs.get(path);
  if (!p || !p.tabs.has(path) || !doc) return;
  const prev = p.currentPath && p.tabs.get(p.currentPath);
  if (prev && p.currentPath !== path && p.editorEl.style.display !== 'none') {
    prev.viewState = p.editor.saveViewState();
  }
  const tab = p.tabs.get(path);
  p.currentPath = path;
  if (p.editor.getModel() !== doc.model) {
    p.editor.setModel(doc.model);
    if (tab.viewState) p.editor.restoreViewState(tab.viewState);
  }
  showPaneView(p);
  applyEditorMode(p);
  if (paneIdx === activePaneIdx) {
    document.getElementById('crumbs').innerHTML = renderCrumbs(path);
    revealInTree(path);
    updateStatus();
    scheduleOutline();
  }
  renderTabsFor(paneIdx);
  saveState();
}

// Markdown tabs show a rendered preview unless the pane's tab is in source mode.
function showPaneView(p) {
  const doc = p.currentPath ? docs.get(p.currentPath) : null;
  const tab = doc ? p.tabs.get(doc.key) : null;
  const preview = !!(doc && doc.isMarkdown && tab && !tab.mdSource);
  if (preview) {
    const alt = doc.model.getAlternativeVersionId();
    if (doc.htmlAlt !== alt || doc.htmlKey !== doc.key) {
      doc.html = mdLocalImages(sanitizeMarkdown(marked.parse(doc.model.getValue())), doc.key);
      doc.htmlAlt = alt;
      doc.htmlKey = doc.key;
    }
    const sig = doc.key + '@' + alt;
    if (p.previewSig !== sig) { p.previewEl.innerHTML = doc.html; p.previewSig = sig; mdHighlight(p, doc, alt); }
  }
  p.previewEl.style.display = preview ? 'block' : 'none';
  p.editorEl.style.display = preview ? 'none' : '';
  // large files: say plainly why typing does nothing
  p.bannerEl.style.display = doc && doc.truncated ? '' : 'none';
  if (doc && doc.truncated) p.bannerEl.textContent = '🔒 ' + doc.readonly;
  p.mdBtn.style.display = doc && doc.isMarkdown ? '' : 'none';
  p.mdBtn.textContent = preview ? '✎ source' : '👁 preview';
}
function toggleMarkdownSource(paneIdx) {
  const p = panes[paneIdx];
  const tab = p && p.currentPath && p.tabs.get(p.currentPath);
  if (!tab) return;
  tab.mdSource = !tab.mdSource;
  showPaneView(p);
  if (tab.mdSource) p.editor.focus();
  saveState();
}
// Links in a preview must not navigate the app page away (unsaved edits).
// Relative links open the target file next to the markdown file.
function onPreviewClick(pane, e) {
  const a = e.target.closest && e.target.closest('a');
  if (!a) return;
  e.preventDefault();
  const href = a.getAttribute('href') || '';
  if (!mdIsRelative(href)) return;
  const key = mdRelKey(pane.currentPath, href);
  if (key) openFileInPane(panes.indexOf(pane), key);
}
function mdIsRelative(url) {
  return !!url && !url.startsWith('#') && !url.startsWith('/') && !/^[a-z][\w+.-]*:/i.test(url);
}
// File key for a path relative to a markdown file; null when it climbs out of
// the open folder (or above the drive root for an absolute key).
function mdRelKey(fromKey, rel) {
  const abs = isAbsKey(fromKey);
  const parts = fromKey.split(/[\\/]/);
  parts.pop();
  let segs;
  try { segs = decodeURIComponent(rel.split(/[?#]/)[0]).split('/'); } catch (_) { return null; }
  for (const seg of segs) {
    if (seg === '..') {
      if (parts.length <= (abs ? 1 : 0)) return null;
      parts.pop();
    } else if (seg && seg !== '.') parts.push(seg);
  }
  return parts.length ? parts.join(abs ? '\\' : '/') : null;
}
// Relative <img src> in a preview (already sanitized) -> /api/image, which only
// serves files inside the open folder. The template keeps the images from loading here.
function mdLocalImages(html, key) {
  const box = document.createElement('template');
  box.innerHTML = html;
  for (const img of box.content.querySelectorAll('img[src]')) {
    const src = img.getAttribute('src');
    if (!mdIsRelative(src)) continue;
    const k = mdRelKey(key, src);
    if (k) img.setAttribute('src', '/api/image?path=' + encodeURIComponent(k));
    else img.removeAttribute('src');
  }
  return box.innerHTML;
}
// Fenced code blocks with a known language: coloured by Monaco's tokenizer
// (its output is escaped text in .mtkN spans, which follow the editor theme).
function mdLanguage(name) {
  name = name.toLowerCase();
  for (const l of monaco.languages.getLanguages()) {
    if (l.id === name || (l.aliases || []).some(a => a.toLowerCase() === name)
        || (l.extensions || []).includes('.' + name)) return l.id;
  }
  return null;
}
function mdHighlight(p, doc, alt) {
  if (typeof monaco === 'undefined') return;
  const jobs = [];
  for (const code of p.previewEl.querySelectorAll('pre > code[class^="language-"]:not([data-hl])')) {
    const lang = mdLanguage(code.className.slice('language-'.length));
    const text = code.textContent.replace(/\n$/, '');
    if (!lang || text.length > 200000) continue;
    jobs.push(monaco.editor.colorize(text, lang, {}).then(html => {
      code.innerHTML = html.replace(/ |&nbsp;/g, ' ');  // <pre> keeps spaces; copied code stays plain
      code.dataset.hl = '1';
    }, () => {}));
  }
  if (!jobs.length) return;
  const sig = p.previewSig;
  // keep the coloured result, so switching back to the tab does not redo it
  Promise.all(jobs).then(() => {
    if (p.previewSig === sig && doc.htmlAlt === alt) doc.html = p.previewEl.innerHTML;
  });
}

// force: close without asking about unsaved changes (folder switch already asked)
async function closeTabIn(paneIdx, path, force) {
  const p = panes[paneIdx];
  if (!p || !p.tabs.has(path)) return false;
  const doc = docs.get(path);
  if (doc && doc.dirty && doc.refs === 1 && !force) {
    const choice = await askChoice('unsaved changes',
      `${baseName(path)} has unsaved changes.`,
      [{ label: 'save', value: 'save', primary: true },
       { label: "don't save", value: 'discard' },
       { label: 'cancel', value: 'cancel' }]);
    if (choice === 'cancel') return false;
    if (choice === 'save' && !(await saveDoc(doc))) return false;
  }
  if (!p.tabs.has(path)) return false;  // closed meanwhile
  p.tabs.delete(path);
  if (p.currentPath === path) {
    const remaining = Array.from(p.tabs.keys());
    if (remaining.length) {
      switchTabIn(paneIdx, remaining[remaining.length - 1]);
    } else {
      p.currentPath = null;
      p.editor.setModel(null);
      showPaneView(p);
      applyEditorMode(p);
      if (paneIdx === activePaneIdx) {
        document.getElementById('crumbs').textContent = 'no file open';
        updateStatus();
      }
    }
  }
  if (doc) releaseDoc(doc);
  renderTabsFor(paneIdx);
  saveState();
  return true;
}

// Convenience aliases for older callers
function closeTab(path) { return closeTabIn(activePaneIdx, path); }

// gotoLine/find: jump there after opening (find = {term, regex, caseS, word}).
// opts: {background, quiet, viewState, mdSource} — used by session restore.
async function openFileInPane(paneIdx, path, gotoLine, find, opts) {
  opts = opts || {};
  const p = panes[paneIdx];
  if (!p || !path) return false;
  if (!p.tabs.has(path)) {
    let doc;
    try {
      doc = await loadDoc(path);
      // its last tab closed while we waited: the model is gone, load it again
      if (doc && doc.model.isDisposed()) doc = await loadDoc(path);
    } catch (e) {
      if (!opts.quiet) showToast(e.message, true);
      forgetIfGone(path);
      return false;
    }
    if (!doc) {
      if (!opts.quiet) showToast('file load failed: ' + baseName(path), true);
      return false;
    }
    if (!p.tabs.has(path)) {  // another call may have added it while loading
      doc.refs++;
      p.tabs.set(path, { viewState: opts.viewState || null, mdSource: !!opts.mdSource });
    }
  }
  if (opts.background) { renderTabsFor(paneIdx); return true; }
  addRecent(path);
  if (gotoLine) {
    pushNav();
    const doc = docs.get(path);
    if (doc && doc.isMarkdown) p.tabs.get(path).mdSource = true;  // show the hit, not the preview
  }
  setActivePane(paneIdx);
  switchTabIn(paneIdx, path);
  if (gotoLine) gotoInEditor(gotoLine, find);
  return true;
}

