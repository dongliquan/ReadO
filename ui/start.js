// ===== Working folder & start screen =====
function fifScopeValue() {
  const v = document.getElementById('fifScope').value;
  if (v !== '@cur') return v;
  const cur = currentPath;  // the folder of the active file, if it is inside the working folder
  return cur && !isAbsKey(cur) ? cur.split('/').slice(0, -1).join('/') : '';
}
function updateFolderButton() {
  const b = document.getElementById('folderBtn');
  const dir = _settings.base_dir_exists ? _settings.base_dir : '';
  b.textContent = dir ? '📁 ' + baseName(dir.replace(/[\\/]+$/, '')) : '📁 open folder';
  b.title = dir ? dir + '\n(click to open another folder)' : 'open a folder';
}
// Shown while no folder is open, or when no file is open in any pane.
function updateStartScreen() {
  const el = document.getElementById('startScreen');
  if (!el) return;
  const noFolder = !_settings.base_dir_exists;
  const nothingOpen = panes.every(p => !p.tabs.size);
  el.style.display = noFolder || nothingOpen ? 'flex' : 'none';
  if (el.style.display === 'none') return;
  const fill = (id, items, onClick, empty) => {
    const box = document.getElementById(id);
    box.innerHTML = '';
    if (!items.length) { box.innerHTML = `<div class="none">${empty}</div>`; return; }
    for (const it of items) {
      const a = document.createElement('a');
      a.textContent = it;
      a.title = it;
      a.onclick = () => onClick(it);
      box.appendChild(a);
    }
  };
  fill('startFolders', (STATE.recentFolders || []).slice(0, 8), p => openFolder(p), 'none yet');
  fill('startFiles', noFolder ? STATE.recent.filter(isAbsKey).slice(0, 8) : STATE.recent.slice(0, 8),
       k => openFile(k), 'none yet');
}
async function openFolderDialog() {
  const api = window.pywebview && window.pywebview.api;
  if (api && api.pick_dir) {
    const d = await api.pick_dir(_settings.base_dir || '');
    if (d) await openFolder(d);
    return;
  }
  // browser mode: no native dialog
  const res = await askChoice('open folder', 'Folder path:',
    [{ label: 'open', value: 'ok', primary: true }, { label: 'cancel', value: 'cancel' }],
    { input: _settings.base_dir || '' });
  if (res.value === 'ok' && res.text.trim()) await openFolder(res.text.trim());
}
// Switch the working folder: tabs of the old folder close (asks first if any
// of them has unsaved changes); files opened from outside stay open.
async function openFolder(path) {
  path = String(path || '').trim();
  if (!path) return false;
  const relDirty = dirtyDocs().filter(d => !isAbsKey(d.key));
  if (relDirty.length && path !== _settings.base_dir) {
    const c = await askChoice('unsaved changes',
      `${relDirty.length} file(s) in the current folder have unsaved changes:\n` +
      relDirty.map(d => d.key).slice(0, 5).join('\n') + '\nDiscard them and open the other folder?',
      [{ label: 'discard and open', value: 'discard' }, { label: 'cancel', value: 'cancel', primary: true }]);
    if (c !== 'discard') return false;
  }
  const prev = _settings.base_dir;
  let data;
  try {
    const r = await fetch('/api/settings', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ base_dir: path }),
    });
    data = await r.json();
    if (!r.ok) throw new Error(data.error || 'HTTP ' + r.status);
  } catch (e) {
    showToast('open folder failed: ' + e.message, true);
    return false;
  }
  if (!data.base_dir_exists) {
    showToast('folder not found: ' + path, true);
    if (prev && prev !== path) {  // keep the previous folder
      await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ base_dir: prev }) }).catch(() => {});
    } else {
      _settings = data;
      updateFolderButton();
      updateStartScreen();
    }
    return false;
  }
  _settings = data;
  if (prev !== data.base_dir) {
    for (let i = 0; i < panes.length; i++) {
      for (const key of [...panes[i].tabs.keys()]) if (!isAbsKey(key)) await closeTabIn(i, key, true);
    }
    _treeMtimes.clear();
    _nav.back = []; _nav.fwd = [];
  }
  STATE.recentFolders = [data.base_dir].concat((STATE.recentFolders || []).filter(p => p !== data.base_dir)).slice(0, 10);
  saveState();
  updateFolderButton();
  await loadTree('', document.getElementById('tree'));
  loadProjects();
  updateStartScreen();
  if (typeof onFolderOpened === 'function') onFolderOpened();
  refreshGitAvail();
  return true;
}
document.getElementById('startPath').addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.preventDefault(); openFolder(e.target.value); }
});

// ===== Init =====
async function bootstrap() {
  initTitleBar();
  renderToolbarTitles();
  refreshToolbar();
  if (STATE.sideTab === 'outline') setSideTab('outline');
  refreshToolStrip();
  refreshGitAvail();
  const treeEl = document.getElementById('tree');
  // Fetch settings first so server's SETTINGS is hot, then load tree synchronously.
  await loadSettings();
  await loadTree('', treeEl);
  loadProjects();
  // Backup retry if tree is empty for any reason
  if (!treeEl.firstChild) {
    setTimeout(() => loadTree('', treeEl), 600);
  }
  await monacoReady;
  await restoreSession();
  updateStartScreen();
  reportDirty();
  pollChanges();  // also opens files passed on the command line
  setInterval(pollChanges, 2500);
}
bootstrap();
