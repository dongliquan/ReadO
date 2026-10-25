// ===== Tree: selection, F2 / Delete, context menu, file operations =====
let _treeSel = null;  // path of the selected tree node
function treeSelect(path) {
  _treeSel = path;
  document.querySelectorAll('#tree .node.sel').forEach(n => n.classList.remove('sel'));
  const n = path && document.querySelector(`#tree .node[data-path="${cssEscape(path)}"]`);
  if (n) { n.classList.add('sel'); n.scrollIntoView({ block: 'nearest' }); }
}
const treeHasFocus = () => !!(document.activeElement && document.activeElement.closest && document.activeElement.closest('#tree'));
const treeNode = path => document.querySelector(`#tree .node[data-path="${cssEscape(path)}"]`);
const isTreeDir = path => { const n = treeNode(path); return !!(n && n.dataset.dir === '1'); };
// what a file command acts on: the tree selection when the tree has focus, else the active file
function fileTarget(fromTree) {
  if ((fromTree || treeHasFocus()) && _treeSel) return { path: _treeSel, dir: isTreeDir(_treeSel) };
  const k = currentPath;
  return k && !isAbsKey(k) ? { path: k, dir: false } : null;
}
const parentOf = p => p.split('/').slice(0, -1).join('/');
async function postJson(url, body) {
  let r, data = {};
  try {
    r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    data = await r.json().catch(() => ({}));
  } catch (e) { return { ok: false, status: 0, data: { error: e.message } }; }
  return { ok: r.ok, status: r.status, data };
}
// open docs at or under a path
const docsUnder = (path, dir) => [...docs.values()].filter(d => d.key === path || (dir && d.key.startsWith(path + '/')));
async function renameEntry(t) {
  t = t || fileTarget();
  if (!t) return showToast('select a file or folder in the tree first', true);
  const name = t.path.split('/').pop();
  const affected = docsUnder(t.path, t.dir);
  const dirty = affected.filter(d => d.dirty);
  if (dirty.length) {
    const c = await askChoice('rename', `${dirty.length} open file(s) here have unsaved changes. Save them first?`,
      [{ label: 'save and rename', value: 'save', primary: true }, { label: 'cancel', value: 'cancel' }]);
    if (c !== 'save') return;
    for (const d of dirty) if (!(await saveDoc(d))) return;
  }
  const res = await askChoice('rename', `New name for ${t.path}`,
    [{ label: 'rename', value: 'ok', primary: true }, { label: 'cancel', value: 'cancel' }], { input: name, selectStem: !t.dir });
  const newName = (res.text || '').trim();
  if (res.value !== 'ok' || !newName || newName === name) return;
  const r = await postJson('/api/rename', { path: t.path, name: newName });
  if (!r.ok) return showToast('rename failed: ' + (r.data.error || 'HTTP ' + r.status), true);
  await remapOpenTabs(t.path, r.data.path, t.dir);
  const parent = parentOf(t.path);
  _treeSkip.add(parent);
  await refreshTreeDir(parent).catch(() => {});
  treeSelect(r.data.path);
  showToast(`renamed to ${r.data.path}`);
}
// tabs of renamed files keep their pane, position and view
async function remapOpenTabs(oldPath, newPath, dir) {
  for (const d of docsUnder(oldPath, dir)) {
    const nk = newPath + d.key.slice(oldPath.length);
    const places = [];
    panes.forEach((p, i) => {
      if (!p.tabs.has(d.key)) return;
      const keys = [...p.tabs.keys()];
      const live = p.currentPath === d.key && p.editorEl.style.display !== 'none';
      places.push({ pane: p, after: keys[keys.indexOf(d.key) + 1] || null, current: p.currentPath === d.key,
                    vs: live ? p.editor.saveViewState() : p.tabs.get(d.key).viewState, md: p.tabs.get(d.key).mdSource });
    });
    for (const pl of places) await closeTabIn(panes.indexOf(pl.pane), d.key, true);
    for (const pl of places) {
      const i = panes.indexOf(pl.pane);
      if (i < 0) continue;
      await openFileInPane(i, nk, null, null, { background: !pl.current, quiet: true, viewState: pl.vs, mdSource: pl.md });
      const tab = pl.pane.tabs.get(nk);
      if (tab) placeTab(pl.pane, nk, tab, pl.after);
      renderTabsFor(i);
    }
  }
  STATE.recent = (STATE.recent || []).map(k => k === oldPath || (dir && k.startsWith(oldPath + '/')) ? newPath + k.slice(oldPath.length) : k);
  saveState();
}
async function deleteEntry(t) {
  t = t || fileTarget();
  if (!t) return showToast('select a file or folder in the tree first', true);
  const affected = docsUnder(t.path, t.dir);
  const dirty = affected.filter(d => d.dirty).length;
  const what = t.dir ? `the folder ${t.path} and everything in it` : t.path;
  const c = await askChoice('delete', `Move ${what} to the Recycle Bin?`
    + (dirty ? `\n${dirty} open file(s) with unsaved changes will be closed and the changes lost.` : ''),
    [{ label: 'move to Recycle Bin', value: 'ok', primary: true }, { label: 'cancel', value: 'cancel' }]);
  if (c !== 'ok') return;
  let r = await postJson('/api/delete', { path: t.path });
  if (!r.ok && r.data.code === 'no_recycle') {
    const c2 = await askChoice('delete', `${t.path} cannot go to the Recycle Bin. Delete it permanently? This cannot be undone.`,
      [{ label: 'cancel', value: 'cancel', primary: true }, { label: 'delete permanently', value: 'ok' }]);
    if (c2 !== 'ok') return;
    r = await postJson('/api/delete', { path: t.path, permanent: true });
  }
  if (!r.ok) return showToast('delete failed: ' + (r.data.error || 'HTTP ' + r.status), true);
  for (const d of affected) for (let i = 0; i < panes.length; i++) if (panes[i].tabs.has(d.key)) await closeTabIn(i, d.key, true);
  STATE.recent = (STATE.recent || []).filter(k => !(k === t.path || (t.dir && k.startsWith(t.path + '/'))));
  saveState();
  const parent = parentOf(t.path);
  _treeSkip.add(parent);
  await refreshTreeDir(parent).catch(() => {});
  _treeSel = null;
  showToast(r.data.recycled ? `moved to the Recycle Bin: ${t.path}` : `deleted: ${t.path}`);
}
async function newFolderDialog(dir) {
  if (dir === undefined) { const t = fileTarget(); dir = t ? (t.dir ? t.path : parentOf(t.path)) : ''; }
  const res = await askChoice('new folder', 'Path relative to the base directory.',
    [{ label: 'create', value: 'ok', primary: true }, { label: 'cancel', value: 'cancel' }], { input: dir ? dir + '/' : '' });
  const path = (res.text || '').trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
  if (res.value !== 'ok' || !path) return;
  const r = await postJson('/api/mkdir', { path });
  if (!r.ok) return showToast('create failed: ' + (r.data.error || 'HTTP ' + r.status), true);
  _treeSkip.add(parentOf(path));
  await refreshTreeDir(parentOf(path)).catch(() => {});
  await revealInTree(path + '/x').catch(() => {});
  treeSelect(path);
  showToast('created ' + path);
}
async function copyText(text, what) {
  try { await navigator.clipboard.writeText(text); }
  catch (e) {
    const ta = Object.assign(document.createElement('textarea'), { value: text });
    document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove();
  }
  showToast('copied ' + (what || 'path') + ': ' + text);
}
const fullPathOf = key => isAbsKey(key) ? key : ((_settings.base_dir || '').replace(/[\\/]+$/, '') + '\\' + key.replace(/\//g, '\\'));
function revealInExplorer(key) {
  const api = window.pywebview && window.pywebview.api;
  if (!api || !api.reveal) return showToast('"reveal in Explorer" needs the desktop app', true);
  api.reveal(key || '');
}
function collapseAll() {
  document.querySelectorAll('#tree .children').forEach(c => { c.style.display = 'none'; });
  document.querySelectorAll('#tree .node[data-dir="1"] .caret').forEach(c => { c.textContent = '▸'; });
}
function treeMenu(e, path, dir) {
  e.preventDefault();
  treeSelect(path);
  const folder = dir ? path : parentOf(path);
  const t = { path, dir };
  showMenu(e.clientX, e.clientY, [
    ...(dir ? [] : [{ label: 'open', hint: 'Enter', run: () => openFile(path) },
                    { label: 'open beside', hint: 'Ctrl+Enter', run: () => openInOtherPane(path, activePaneIdx, true) }, 'sep']),
    { label: 'new file…', hint: CMD.get('file.new').keys, run: () => newFileDialog(folder) },
    { label: 'new folder…', run: () => newFolderDialog(folder) },
    'sep',
    { label: 'rename…', hint: CMD.get('file.rename').keys, run: () => renameEntry(t) },
    { label: 'delete', hint: CMD.get('file.delete').keys, run: () => deleteEntry(t) },
    'sep',
    { label: 'copy path', run: () => copyText(fullPathOf(path)) },
    { label: 'copy relative path', run: () => copyText(path, 'relative path') },
    { label: 'reveal in Explorer', disabled: !isDesktop(), run: () => revealInExplorer(path) },
    'sep',
    { label: 'collapse all', run: () => collapseAll() },
  ]);
}
// tree: click selects, keys act on the selection (focus stays in the tree)
(() => {
  const tree = document.getElementById('tree');
  tree.tabIndex = 0;
  tree.addEventListener('mousedown', e => { const n = e.target.closest('.node'); if (n) treeSelect(n.dataset.path); }, true);
  tree.addEventListener('contextmenu', e => {
    const n = e.target.closest('.node');
    e.preventDefault();
    e.stopImmediatePropagation();
    if (n) treeMenu(e, n.dataset.path, n.dataset.dir === '1');
    else showMenu(e.clientX, e.clientY, [{ label: 'new file…', run: () => newFileDialog('') },
      { label: 'new folder…', run: () => newFolderDialog('') }, { label: 'collapse all', run: collapseAll }]);
  }, true);
  tree.addEventListener('keydown', e => {
    if (!_treeSel || e.ctrlKey || e.altKey || e.metaKey) return;
    const nodes = [...tree.querySelectorAll('.node')].filter(n => n.offsetParent !== null);
    const i = nodes.findIndex(n => n.dataset.path === _treeSel);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const n = nodes[Math.max(0, Math.min(nodes.length - 1, i + (e.key === 'ArrowDown' ? 1 : -1)))];
      if (n) treeSelect(n.dataset.path);
    } else if (e.key === 'Enter' && i >= 0) {
      e.preventDefault();
      nodes[i].click();
    }
  });
})();

