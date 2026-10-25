// ===== Settings =====
async function loadSettings() {
  try {
    const r = await fetch('/api/settings');
    _settings = await r.json();
  } catch (e) {}
  updateFolderButton();
  if (_settings.base_dir_exists && !(STATE.recentFolders || []).includes(_settings.base_dir)) {
    STATE.recentFolders = [_settings.base_dir].concat(STATE.recentFolders || []).slice(0, 10);
  }
}
function fmtSize(n) {
  return n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : n >= 1024 ? Math.round(n / 1024) + ' KB' : n + ' B';
}
function showKeymapConflicts() {
  const el = document.getElementById('keymapConflicts');
  const name = document.getElementById('setKeymap').value;
  const c = keymapConflicts(name);
  el.textContent = c.length ? 'conflicts: ' + c.map(x => `${x.combo} (${x.ids.join(', ')})`).join('; ') : 'no key conflicts';
  el.classList.toggle('err', c.length > 0);
}
document.getElementById('setKeymap').addEventListener('change', showKeymapConflicts);
async function openSettings() {
  closeQO();
  closeFIF();
  // always fetch latest from server so the modal reflects current state
  try {
    const r = await fetch('/api/settings', { cache: 'no-store' });
    if (r.ok) _settings = await r.json();
  } catch (e) {}
  document.getElementById('setBaseDir').value = _settings.base_dir || '';
  document.getElementById('setIgnored').value = (_settings.ignored || []).join(', ');
  document.getElementById('setSearchIgnored').value = (_settings.search_ignored || []).join(', ');
  document.getElementById('setComponentClick').checked = STATE.componentClick !== false;
  document.getElementById('setComponentBeside').checked = STATE.componentBeside !== false;
  document.getElementById('setLineBlame').checked = !!(STATE.git && STATE.git.lineBlame);
  document.getElementById('setLangDiagnostics').checked = !!STATE.langDiagnostics;
  document.getElementById('setKeymap').value = STATE.keymap || 'vscode';
  document.getElementById('setGitignore').checked = !!_settings.respect_gitignore;
  document.getElementById('setMaxMb').value = Math.round((_settings.max_file_bytes || 2000000) / 1000000);
  document.getElementById('setMaxResults').value = _settings.search_max_results || 500;
  showKeymapConflicts();
  renderShortcutList();
  document.getElementById('settingsBg').classList.add('show');
  refreshAssoc().catch(() => {});
}
function closeSettings() { document.getElementById('settingsBg').classList.remove('show'); }
async function pickDir() {
  if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_dir) {
    const d = await window.pywebview.api.pick_dir(document.getElementById('setBaseDir').value);
    if (d) document.getElementById('setBaseDir').value = d;
  } else {
    showToast('browser mode — type manually', true);
  }
}
async function saveSettings() {
  const list = id => document.getElementById(id).value.split(/[,\n]/).map(s => s.trim()).filter(Boolean);
  const newDir = document.getElementById('setBaseDir').value.trim();
  const payload = { ignored: list('setIgnored'), search_ignored: list('setSearchIgnored'),
    respect_gitignore: document.getElementById('setGitignore').checked,
    max_file_bytes: Math.max(1, Math.min(50, +document.getElementById('setMaxMb').value || 2)) * 1000000,
    search_max_results: Math.max(50, Math.min(20000, +document.getElementById('setMaxResults').value || 500)) };
  const km = document.getElementById('setKeymap').value;
  if (km !== (STATE.keymap || 'vscode')) setKeymap(km);
  STATE.componentClick = document.getElementById('setComponentClick').checked;
  STATE.componentBeside = document.getElementById('setComponentBeside').checked;
  if (window.GitUI) GitUI.toggleLineBlame(document.getElementById('setLineBlame').checked);
  const diag = document.getElementById('setLangDiagnostics').checked;
  if (diag !== !!STATE.langDiagnostics) { STATE.langDiagnostics = diag; applyLangDiagnostics(); }
  saveState();
  try {
    const r = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error('save failed');
    _settings = await r.json();
    showToast('settings saved');
    closeSettings();
    if (newDir && newDir !== _settings.base_dir) {
      await openFolder(newDir);
    } else {
      loadTree('', document.getElementById('tree'));
      loadProjects();
    }
  } catch (e) {
    showToast('save failed: ' + e.message, true);
  }
}

// ===== Splitter =====
const splitter = document.getElementById('splitter');
const sidebar = document.getElementById('sidebar');
let dragging = false;
splitter.addEventListener('mousedown', () => { dragging = true; document.body.style.cursor = 'col-resize'; });
window.addEventListener('mouseup', () => {
  if (!dragging) return;
  dragging = false;
  document.body.style.cursor = '';
  STATE.sidebarWidth = parseInt(sidebar.style.width) || null;
  saveState();
});
window.addEventListener('mousemove', e => {
  if (!dragging) return;
  const w = Math.max(180, Math.min(600, e.clientX));
  sidebar.style.width = w + 'px';
});

