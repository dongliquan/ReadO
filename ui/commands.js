// ===== Commands: one registry for the menu bar, the palette (Ctrl+Shift+P) and the keys =====
// keys: shown in menus / the palette; bind: key combos (see keyCombo) that run it.
// capture: handled before Monaco sees the key (pane keys, palettes); when(): false
// lets the key through (e.g. Ctrl+Alt+↑ adds a cursor when no pane is above).
const isDesktop = () => !!(window.pywebview && window.pywebview.api && window.pywebview.api.win_state);
const edAction = id => () => runEditorAction(id);
const COMMANDS = [
  // File
  { id: 'file.new', cat: 'File', title: 'New File…', keys: 'Ctrl+N', bind: ['Ctrl+N', 'Alt+Insert'], run: () => newFileDialog() },
  { id: 'file.open', cat: 'File', title: 'Open File…', keys: 'Ctrl+O', bind: ['Ctrl+O'], run: () => openDialog() },
  { id: 'file.openFolder', cat: 'File', title: 'Open Folder…', run: () => openFolderDialog() },
  { id: 'file.recent', cat: 'File', title: 'Recent Files…', keys: 'Ctrl+E', bind: ['Ctrl+E'], run: () => openQO('') },
  { id: 'file.save', cat: 'File', title: 'Save', keys: 'Ctrl+S', bind: ['Ctrl+S'], run: () => saveCurrent() },
  { id: 'file.saveAll', cat: 'File', title: 'Save All', run: () => saveAll(), enabled: () => dirtyDocs().length > 0 },
  { id: 'file.closeTab', cat: 'File', title: 'Close Tab', keys: 'Ctrl+W', bind: ['Ctrl+W'], run: () => currentPath && closeTab(currentPath) },
  { id: 'file.newFolder', cat: 'File', title: 'New Folder…', run: () => newFolderDialog() },
  { id: 'file.rename', cat: 'File', title: 'Rename…', keys: 'F2', bind: ['F2'], when: () => treeHasFocus(), run: () => renameEntry() },
  { id: 'file.delete', cat: 'File', title: 'Delete', keys: 'Delete', bind: ['Delete'], when: () => treeHasFocus(), run: () => deleteEntry() },
  { id: 'file.copyPath', cat: 'File', title: 'Copy Path', run: () => { const t = fileTarget(); if (t) copyText(fullPathOf(t.path)); } },
  { id: 'file.copyRelPath', cat: 'File', title: 'Copy Relative Path', run: () => { const t = fileTarget(); if (t) copyText(t.path, 'relative path'); } },
  { id: 'file.reveal', cat: 'File', title: 'Reveal in Explorer', desktop: true, run: () => { const t = fileTarget(); revealInExplorer(t ? t.path : currentPath); } },
  { id: 'file.reopenEncoding', cat: 'File', title: 'Reopen with Encoding…', run: () => reopenWithEncoding(), enabled: () => !!currentDoc() },
  { id: 'file.compareSaved', cat: 'File', title: 'Compare with Saved', run: () => compareWithSaved(), enabled: () => !!currentDoc() },
  { id: 'file.compareHead', cat: 'File', title: 'Compare with Git HEAD', run: () => compareWithHead(), enabled: () => !!currentDoc() },
  { id: 'file.compareFile', cat: 'File', title: 'Compare with File…', run: () => compareWithFile(), enabled: () => !!currentDoc() },
  { id: 'file.settings', cat: 'File', title: 'Settings…', run: () => openSettings() },
  { id: 'pref.keymapVSCode', cat: 'Preferences', title: 'Keymap: VS Code', run: () => setKeymap('vscode'), checked: () => (STATE.keymap || 'vscode') === 'vscode' },
  { id: 'pref.keymapIntelliJ', cat: 'Preferences', title: 'Keymap: IntelliJ IDEA', run: () => setKeymap('intellij'), checked: () => STATE.keymap === 'intellij' },
  { id: 'pref.gitignore', cat: 'Preferences', title: 'Hide .gitignore\'d Files', run: () => toggleGitignore(), checked: () => !!_settings.respect_gitignore },
  { id: 'file.assocOn', cat: 'File', title: 'Add ReadO to Windows "Open with"', desktop: true, run: () => setAssoc(true) },
  { id: 'file.assocOff', cat: 'File', title: 'Remove ReadO from Windows "Open with"', desktop: true, run: () => setAssoc(false) },
  { id: 'file.reload', cat: 'File', title: 'Reload Window', run: () => reloadWindow() },
  { id: 'file.exit', cat: 'File', title: 'Exit', keys: 'Alt+F4', desktop: true, run: () => winApi('win_close') },
  // Edit (Monaco's own keys; the menu / palette run the same editor commands)
  { id: 'edit.undo', cat: 'Edit', title: 'Undo', keys: 'Ctrl+Z', run: edAction('undo') },
  { id: 'edit.redo', cat: 'Edit', title: 'Redo', keys: 'Ctrl+Y', run: edAction('redo') },
  { id: 'edit.cut', cat: 'Edit', title: 'Cut', keys: 'Ctrl+X', run: edAction('editor.action.clipboardCutAction') },
  { id: 'edit.copy', cat: 'Edit', title: 'Copy', keys: 'Ctrl+C', run: edAction('editor.action.clipboardCopyAction') },
  { id: 'edit.paste', cat: 'Edit', title: 'Paste', keys: 'Ctrl+V', run: edAction('editor.action.clipboardPasteAction') },
  { id: 'edit.selectAll', cat: 'Edit', title: 'Select All', keys: 'Ctrl+A', run: edAction('editor.action.selectAll') },
  { id: 'edit.find', cat: 'Edit', title: 'Find', keys: 'Ctrl+F', run: edAction('actions.find') },
  { id: 'edit.replace', cat: 'Edit', title: 'Replace', keys: 'Ctrl+H', run: edAction('editor.action.startFindReplaceAction') },
  { id: 'edit.findInFiles', cat: 'Edit', title: 'Find in Files', keys: 'Ctrl+Shift+F', bind: ['Ctrl+Shift+F'], run: () => qoIsOpen() ? fdSwitch('text', fdTerm()) : openFIF() },
  { id: 'edit.replaceInFiles', cat: 'Edit', title: 'Replace in Files', keys: 'Ctrl+Shift+H', bind: ['Ctrl+Shift+H'],
    run: () => { openFIF(); if (!document.getElementById('fifReplToggle').classList.contains('on')) toggleFIFReplace(); document.getElementById('fifRepl').focus(); } },
  { id: 'edit.comment', cat: 'Edit', title: 'Toggle Line Comment', keys: 'Ctrl+/', run: edAction('editor.action.commentLine') },
  { id: 'edit.toggleEditing', cat: 'Edit', title: 'Editing', keys: 'Ctrl+Shift+E', bind: ['Ctrl+Shift+E'],
    run: () => toggleEditMode(), checked: () => !!STATE.editMode },
  // View
  { id: 'view.commands', cat: 'View', title: 'Command Palette…', keys: 'Ctrl+Shift+P', bind: ['Ctrl+Shift+P'], capture: true, global: true,
    run: () => openQO('>') },
  { id: 'view.files', cat: 'View', title: 'Files', keys: 'Alt+1', bind: ['Alt+1'], capture: true, global: true,
    run: () => toggleSideTool('files'), checked: () => !STATE.sideCollapsed && _sideTab === 'files' },
  { id: 'view.sidebar', cat: 'View', title: 'Sidebar', run: () => setSidebarOpen(!!STATE.sideCollapsed), checked: () => !STATE.sideCollapsed },
  { id: 'view.collapseAll', cat: 'View', title: 'Collapse All Folders', run: () => collapseAll() },
  { id: 'view.minimap', cat: 'View', title: 'Minimap', run: () => toggleMinimap(), checked: () => !!STATE.minimap },
  { id: 'view.whitespace', cat: 'View', title: 'Show Whitespace', run: () => toggleWhitespace(), checked: () => !!STATE.whitespace },
  { id: 'view.outline', cat: 'View', title: 'Outline', keys: 'Alt+2', bind: ['Alt+2'], capture: true, global: true,
    run: () => toggleSideTool('outline'), checked: () => !STATE.sideCollapsed && _sideTab === 'outline' },
  ...Object.entries(LAYOUT_PRESETS).map(([name, p]) => ({ id: 'layout.' + name, cat: 'Layout', title: p.label[0].toUpperCase() + p.label.slice(1),
    run: () => applyLayoutPreset(name) })),
  { id: 'layout.splitRight', cat: 'Layout', title: 'Split Right', keys: 'Ctrl+\\', bind: ['Ctrl+\\'], capture: true,
    run: () => splitActive('row'), enabled: () => panes.length < MAX_PANES },
  { id: 'layout.splitDown', cat: 'Layout', title: 'Split Down', keys: 'Ctrl+Alt+\\', bind: ['Ctrl+Alt+\\'], capture: true,
    run: () => splitActive('col'), enabled: () => panes.length < MAX_PANES },
  { id: 'layout.closePane', cat: 'Layout', title: 'Close Pane', run: () => closePane(activePaneIdx), enabled: () => panes.length > 1 },
  ...[1, 2, 3, 4].map(n => ({ id: 'pane.focus' + n, cat: 'Pane', title: `Focus Pane ${n}`, keys: `Ctrl+${n}`, bind: [`Ctrl+${n}`], capture: true,
    run: () => focusPane(n - 1), enabled: () => panes.length >= n })),
  ...['left', 'right', 'up', 'down'].map(d => ({ id: 'pane.' + d, cat: 'Pane', title: `Focus Pane ${d[0].toUpperCase() + d.slice(1)}`,
    keys: 'Ctrl+Alt+' + { left: '←', right: '→', up: '↑', down: '↓' }[d],
    bind: ['Ctrl+Alt+Arrow' + d[0].toUpperCase() + d.slice(1)], capture: true,
    when: () => paneInDirection(activePaneIdx, d) >= 0, run: () => focusPane(paneInDirection(activePaneIdx, d)) })),
  { id: 'pane.moveNext', cat: 'Pane', title: 'Move Tab to Next Pane', keys: 'Ctrl+Alt+PgDn', bind: ['Ctrl+Alt+PageDown'], capture: true,
    run: () => sendTabToPane(1) },
  { id: 'pane.movePrev', cat: 'Pane', title: 'Move Tab to Previous Pane', keys: 'Ctrl+Alt+PgUp', bind: ['Ctrl+Alt+PageUp'], capture: true,
    run: () => sendTabToPane(-1) },
  { id: 'view.nextTab', cat: 'View', title: 'Next Tab', keys: 'Ctrl+Tab', bind: ['Ctrl+Tab'], run: () => cycleTab(1) },
  { id: 'view.prevTab', cat: 'View', title: 'Previous Tab', keys: 'Ctrl+Shift+Tab', bind: ['Ctrl+Shift+Tab'], run: () => cycleTab(-1) },
  { id: 'view.wrap', cat: 'View', title: 'Word Wrap', keys: 'Alt+Z', bind: ['Alt+Z'], run: () => toggleWrap(), checked: () => !!STATE.wordWrap },
  { id: 'view.markdown', cat: 'View', title: 'Markdown: Source / Preview', run: () => toggleMarkdownSource(activePaneIdx),
    enabled: () => { const d = currentDoc(); return !!(d && d.isMarkdown); } },
  { id: 'view.zoomIn', cat: 'View', title: 'Font Size Bigger', keys: 'Ctrl+=', bind: ['Ctrl+=', 'Ctrl++', 'Ctrl+Shift++', 'Ctrl+Shift+='], run: () => zoomFont(1) },
  { id: 'view.zoomOut', cat: 'View', title: 'Font Size Smaller', keys: 'Ctrl+-', bind: ['Ctrl+-'], run: () => zoomFont(-1) },
  { id: 'view.zoomReset', cat: 'View', title: 'Font Size Reset', keys: 'Ctrl+0', bind: ['Ctrl+0'], run: () => zoomFont(0) },
  { id: 'view.theme', cat: 'View', title: 'Dark Theme', run: () => toggleTheme(), checked: () => getTheme() === 'dark' },
  { id: 'view.themeLight', cat: 'View', title: 'Theme: Light', menuTitle: 'Light', run: () => setThemeMode('light'), checked: () => getThemeMode() === 'light' },
  { id: 'view.themeDark', cat: 'View', title: 'Theme: Dark', menuTitle: 'Dark', run: () => setThemeMode('dark'), checked: () => getThemeMode() === 'dark' },
  { id: 'view.themeSystem', cat: 'View', title: 'Theme: System', menuTitle: 'System', run: () => setThemeMode('system'), checked: () => getThemeMode() === 'system' },
  { id: 'view.themeCycle', cat: 'View', title: 'Switch Theme (Light → Dark → System)', run: () => cycleTheme() },
  // Go
  { id: 'go.file', cat: 'Go', title: 'Go to File…', keys: 'Ctrl+P', bind: ['Ctrl+P', 'Ctrl+Shift+N'], capture: true, global: true, run: () => fifIsOpen() ? fdSwitch('files', fdTerm()) : openQO('') },
  { id: 'go.symbolFolder', cat: 'Go', title: 'Go to Symbol in Folder…', keys: 'Ctrl+T', bind: ['Ctrl+T', 'Ctrl+Shift+Alt+N'], run: () => openQO('#') },
  { id: 'go.symbolFile', cat: 'Go', title: 'Go to Symbol in File…', keys: 'Ctrl+Shift+O', bind: ['Ctrl+Shift+O'], run: () => openQO('@') },
  { id: 'go.line', cat: 'Go', title: 'Go to Line…', keys: 'Ctrl+G', bind: ['Ctrl+G'], run: () => openQO(':') },
  { id: 'go.definition', cat: 'Go', title: 'Go to Definition', keys: 'F12', bind: ['F12', 'Ctrl+B'],
    run: () => { _explicitNavAt = Date.now(); runEditorAction('editor.action.revealDefinition'); } },
  { id: 'go.definitionHere', cat: 'Go', title: 'Go to Definition in This Pane', keys: 'Ctrl+Alt+F12', bind: ['Ctrl+Alt+F12'],
    run: () => { _explicitNavAt = Date.now(); componentSamePaneOnce(); runEditorAction('editor.action.revealDefinition'); } },
  { id: 'go.peek', cat: 'Go', title: 'Peek Definition', keys: 'Alt+F12', bind: ['Alt+F12'], run: edAction('editor.action.peekDefinition') },
  { id: 'go.usages', cat: 'Go', title: 'Find Usages', keys: 'Shift+F12', bind: ['Shift+F12', 'Alt+F7'], run: edAction('editor.action.goToReferences') },
  { id: 'go.back', cat: 'Go', title: 'Back', keys: 'Alt+←', bind: ['Alt+ArrowLeft'], run: () => navGo(-1) },
  { id: 'go.forward', cat: 'Go', title: 'Forward', keys: 'Alt+→', bind: ['Alt+ArrowRight'], run: () => navGo(1) },
  // Window (desktop app)
  { id: 'win.minimize', cat: 'Window', title: 'Minimize', desktop: true, run: () => winApi('win_minimize') },
  { id: 'win.maximize', cat: 'Window', title: 'Maximize / Restore', desktop: true, run: () => winApi('win_toggle_maximize') },
  // Help
  { id: 'help.keys', cat: 'Help', title: 'Keyboard Shortcuts', run: () => showShortcuts() },
  { id: 'help.about', cat: 'Help', title: 'About ReadO', run: () => askChoice('ReadO ' + (_settings.version || ''),
    'Lightweight source viewer & editor — Monaco, ripgrep and Universal Ctags, offline.', [{ label: 'ok', value: 'ok', primary: true }]) },
];
const CMD = new Map(COMMANDS.map(c => [c.id, c]));
const cmdEnabled = c => (!c.desktop || isDesktop()) && (!c.enabled || c.enabled());
function runCommand(id) {
  const c = CMD.get(id);
  if (!c || !cmdEnabled(c)) return false;
  if (!c.capture || !c.global) {  // opening a palette is not worth remembering
    STATE.recentCommands = [id].concat((STATE.recentCommands || []).filter(x => x !== id)).slice(0, 8);
    saveState();
  }
  c.run();
  return true;
}
async function saveAll() {
  for (const d of dirtyDocs()) await saveDoc(d);
}
function cycleTab(step) {
  const p = currentPane(); if (!p) return;
  const keys = Array.from(p.tabs.keys());
  if (keys.length < 2) return;
  const idx = keys.indexOf(p.currentPath);
  switchTabIn(activePaneIdx, keys[(idx + step + keys.length) % keys.length]);
}
async function reloadWindow() {
  if (dirtyDocs().length) {
    const c = await askChoice('reload', `${dirtyDocs().length} file(s) have unsaved changes — they are lost on reload.`,
      [{ label: 'cancel', value: 'cancel', primary: true }, { label: 'reload anyway', value: 'reload' }]);
    if (c !== 'reload') return;
  }
  flushState();
  location.reload();
}
function showShortcuts() {
  openSettings();
  setTimeout(() => { const k = document.querySelector('#settingsBg .kbd-row'); if (k) k.scrollIntoView({ block: 'start' }); }, 50);
}
function winApi(name, ...args) {
  const api = window.pywebview && window.pywebview.api;
  if (api && api[name]) return api[name](...args);
}

// "Ctrl+Shift+Alt+K" for a key event (letters upper-case, digits / backslash by key position)
function keyCombo(e) {
  let k = e.key;
  if (/^Digit\d$/.test(e.code)) k = e.code.slice(5);
  else if (e.code === 'Backslash') k = '\\';
  else if (k.length === 1) k = k.toUpperCase();
  return (e.ctrlKey || e.metaKey ? 'Ctrl+' : '') + (e.shiftKey ? 'Shift+' : '') + (e.altKey ? 'Alt+' : '') + k;
}
const _binds = { capture: new Map(), bubble: new Map() };
function rebuildBinds() {
  _binds.capture.clear(); _binds.bubble.clear();
  for (const c of COMMANDS) for (const b of c.bind || []) _binds[c.capture ? 'capture' : 'bubble'].set(b, c);
}
rebuildBinds();
function dispatchKey(e, phase) {
  const c = _binds[phase].get(keyCombo(e));
  if (!c || (c.when && !c.when()) || !cmdEnabled(c)) return false;
  e.preventDefault();
  e.stopPropagation();
  runCommand(c.id);
  return true;
}
// capture phase: before Monaco (pane keys, Ctrl+P / Ctrl+Shift+P); with a modal open only the palettes
window.addEventListener('keydown', e => {
  if (e.key === 'Escape' && document.getElementById('diffBg').classList.contains('show') && !document.querySelector('.qo-bg.show, .modal-bg.show')) {
    e.preventDefault(); e.stopPropagation(); closeDiff(); return;
  }
  if (e.key === 'Escape' && _menuOpen != null) { e.preventDefault(); e.stopPropagation(); closeMenuBar(); return; }
  if (e.repeat && !/Arrow|Page/.test(e.key)) return;
  const modal = _dlgResolve || document.querySelector('.modal-bg.show, .qo-bg.show');
  const c = _binds.capture.get(keyCombo(e));
  if (!c || (modal && !c.global) || _dlgResolve) return;
  dispatchKey(e, 'capture');
}, true);
// browser shortcuts that would reload, print or open dev tools inside the app
const BROWSER_KEYS = new Set(['F5', 'Ctrl+F5', 'Ctrl+R', 'Ctrl+Shift+R', 'Ctrl+U', 'Ctrl+J', 'Ctrl+Shift+I', 'Ctrl+Shift+J',
  'Ctrl+Shift+C', 'Ctrl+Shift+Delete', 'Ctrl+Shift+B']);
window.addEventListener('keydown', e => { if (BROWSER_KEYS.has(keyCombo(e))) e.preventDefault(); }, true);
window.print = () => {};
document.addEventListener('keydown', e => {
  // a choice dialog is open: only Esc (cancel); buttons take Enter/Space themselves
  if (_dlgResolve) {
    if (e.key === 'Escape') { e.preventDefault(); closeDialog('cancel'); }
    return;
  }
  if (e.key === 'Escape' && document.getElementById('ctxMenu')) { closeMenu(); return; }
  // navigation keys (F12 …) reach here only when the editor did not take them
  if (dispatchKey(e, 'bubble')) return;
  if (e.key === 'Escape') {
    if (document.getElementById('rplBg').classList.contains('show')) { closeReplace(); return; }
    closeSettings();
  }
});

// ===== Menu bar (title bar) — menus are lists of command ids =====
const MENUS = [
  { label: 'File', items: ['file.new', 'file.newFolder', 'file.open', 'file.openFolder', 'file.recent', '-', 'file.save', 'file.saveAll', '-',
    'file.rename', 'file.delete', 'file.copyPath', 'file.copyRelPath', 'file.reveal', '-',
    { label: 'Compare', items: ['file.compareSaved', 'file.compareHead', 'file.compareFile'] }, 'file.reopenEncoding', '-',
    'file.closeTab', 'layout.closePane', '-', 'file.settings',
    { label: 'Preferences', items: ['pref.keymapVSCode', 'pref.keymapIntelliJ', '-', 'pref.gitignore', '-', 'file.assocOn', 'file.assocOff'] },
    '-', 'file.reload', 'file.exit'] },
  { label: 'Edit', items: ['edit.undo', 'edit.redo', '-', 'edit.cut', 'edit.copy', 'edit.paste', 'edit.selectAll', '-',
    'edit.find', 'edit.replace', 'edit.findInFiles', 'edit.replaceInFiles', '-', 'edit.comment', 'edit.toggleEditing'] },
  { label: 'View', items: ['view.commands', '-', 'view.files', 'view.outline', 'view.sidebar', '-',
    { label: 'Layout', items: ['layout.single', 'layout.cols2', 'layout.cols3', 'layout.rows2', 'layout.grid', '-',
      'layout.splitRight', 'layout.splitDown', 'layout.closePane'] },
    { label: 'Pane', items: ['pane.focus1', 'pane.focus2', 'pane.focus3', 'pane.focus4', '-', 'pane.left', 'pane.right', 'pane.up', 'pane.down', '-',
      'pane.moveNext', 'pane.movePrev'] },
    '-', 'view.collapseAll', '-', 'view.wrap', 'view.minimap', 'view.whitespace', 'view.markdown',
    { label: 'Theme', items: ['view.themeLight', 'view.themeDark', 'view.themeSystem'] }, '-',
    'view.zoomIn', 'view.zoomOut', 'view.zoomReset'] },
  { label: 'Go', items: ['go.file', 'go.symbolFolder', 'go.symbolFile', 'go.line', '-', 'go.definition', 'go.definitionHere', 'go.peek',
    'go.usages', '-', 'go.back', 'go.forward', '-', 'view.nextTab', 'view.prevTab'] },
  { label: 'Window', desktop: true, items: ['win.minimize', 'win.maximize', '-', 'file.exit'] },
  { label: 'Help', items: ['view.commands', 'help.keys', '-', 'help.about'] },
];
let _menuOpen = null;
function renderMenuBar() {
  const nav = document.getElementById('menubar');
  nav.innerHTML = '';
  MENUS.forEach((m, i) => {
    if (m.desktop && !isDesktop()) return;
    const b = document.createElement('button');
    b.className = 'menubar-item' + (_menuOpen === i ? ' open' : '');
    b.textContent = m.label;
    b.dataset.menu = m.label;
    b.addEventListener('mousedown', e => {
      e.preventDefault();
      if (_menuOpen === i) closeMenuBar(); else openMenuBar(i, b);
    });
    b.addEventListener('mouseenter', () => { if (_menuOpen != null && _menuOpen !== i) openMenuBar(i, b); });
    nav.appendChild(b);
  });
}
function openMenuBar(i, btn) {
  closeMenu();
  _menuOpen = i;
  document.querySelectorAll('.menubar-item').forEach(x => x.classList.toggle('open', x === btn));
  const r = btn.getBoundingClientRect();
  document.querySelectorAll('.menu-dropdown').forEach(d => d.remove());
  menuDropdown(MENUS[i].items, r.left, r.bottom + 2, 0);
}
function closeMenuBar() {
  _menuOpen = null;
  document.querySelectorAll('.menu-dropdown').forEach(d => d.remove());
  document.querySelectorAll('.menubar-item.open').forEach(x => x.classList.remove('open'));
}
function menuDropdown(items, x, y, level) {
  document.querySelectorAll('.menu-dropdown').forEach(d => { if (+d.dataset.level >= level) d.remove(); });
  const box = document.createElement('div');
  box.className = 'menu-dropdown';
  box.dataset.level = level;
  box.addEventListener('mousedown', e => e.preventDefault());  // keep the editor's focus and selection
  for (const it of items) {
    if (it === '-') { box.appendChild(Object.assign(document.createElement('div'), { className: 'menu-sep' })); continue; }
    const row = document.createElement('button');
    row.className = 'menu-row';
    if (typeof it === 'object') {  // submenu
      row.innerHTML = `<span class="menu-label">${escapeHtml(it.label)}</span><span class="menu-arrow">›</span>`;
      row.addEventListener('mouseenter', () => {
        const r = row.getBoundingClientRect();
        box.querySelectorAll('.menu-row.open').forEach(o => o.classList.remove('open'));
        row.classList.add('open');
        menuDropdown(it.items, r.right - 2, r.top - 4, level + 1);
      });
    } else {
      const c = CMD.get(it);
      if (!c || (c.desktop && !isDesktop())) continue;
      row.dataset.cmd = c.id;
      row.disabled = !cmdEnabled(c);
      row.innerHTML = `<span class="menu-label">${escapeHtml(c.menuTitle || c.title)}</span>`
        + (c.checked && c.checked() ? '<span class="menu-check">✓</span>' : '')
        + (c.keys ? `<span class="menu-acc">${escapeHtml(c.keys)}</span>` : '');
      row.addEventListener('mouseenter', () => menuDropdownClose(level + 1, box));
      row.addEventListener('click', () => { closeMenuBar(); runCommand(c.id); });
    }
    box.appendChild(row);
  }
  document.body.appendChild(box);
  const r = box.getBoundingClientRect();
  box.style.left = Math.max(4, Math.min(x, window.innerWidth - r.width - 4)) + 'px';
  box.style.top = Math.max(4, Math.min(y, window.innerHeight - r.height - 4)) + 'px';
}
function menuDropdownClose(level, parent) {
  document.querySelectorAll('.menu-dropdown').forEach(d => { if (+d.dataset.level >= level) d.remove(); });
  parent.querySelectorAll('.menu-row.open').forEach(o => o.classList.remove('open'));
}
window.addEventListener('mousedown', e => {
  if (_menuOpen == null) return;
  if (e.target.closest && (e.target.closest('.menu-dropdown') || e.target.closest('#menubar'))) return;
  closeMenuBar();
}, true);
window.addEventListener('blur', () => closeMenuBar());

// ===== Title bar: drag, double-click, window buttons, edge resize (desktop app) =====
// The window has no native caption (reado.py); dragging the bar or an edge asks
// Windows to run its own move / size loop, so Aero Snap and Win+arrows work.
function initTitleBar() {
  const bar = document.getElementById('titlebar');
  renderMenuBar();
  let down = null;
  bar.addEventListener('mousedown', e => {
    if (e.button !== 0 || e.target.closest('button, .menubar, .tb-search')) return;
    down = { x: e.screenX, y: e.screenY };
  });
  window.addEventListener('mousemove', e => {
    if (!down || !(e.buttons & 1)) { down = null; return; }
    if (Math.abs(e.screenX - down.x) + Math.abs(e.screenY - down.y) < 4) return;
    down = null;
    window._tbDragStarts = (window._tbDragStarts || 0) + 1;
    winApi('win_drag');
  });
  window.addEventListener('mouseup', () => { down = null; });
  bar.addEventListener('dblclick', e => {
    if (e.target.closest('button, .menubar, .tb-search')) return;
    winApi('win_toggle_maximize');
  });
  document.querySelectorAll('.rz').forEach(z => z.addEventListener('mousedown', e => {
    if (e.button === 0) { e.preventDefault(); winApi('win_resize', z.dataset.edge); }
  }));
  const syncState = async () => {
    const api = window.pywebview && window.pywebview.api;
    if (!api || !api.win_state) return;
    const st = await api.win_state();
    document.body.classList.toggle('desktop', !!st.frame);  // our caption buttons only without the native caption
    document.body.classList.toggle('maximized', !!st.maximized);
    document.getElementById('winMax').title = st.maximized ? 'restore' : 'maximize';
  };
  window.readoWinSync = syncState;  // reado.py calls it once the frame is in place
  let t = null;
  window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(syncState, 80); });
  const desktop = () => {
    renderMenuBar();
    syncState();
  };
  window.addEventListener('pywebviewready', desktop);
  if (isDesktop()) desktop();
}
// ===== File-type badges (tree, tabs): small coloured letters, no images =====
const FILE_BADGES = [
  [/\.(java)$/i, 'J', '#b07219'], [/\.(kt|kts)$/i, 'K', '#a97bff'], [/\.(scala|sc)$/i, 'SC', '#c22d40'], [/\.(groovy|gradle)$/i, 'G', '#4298b8'],
  [/\.(tsx)$/i, 'TSX', '#3178c6'], [/\.(ts|mts|cts)$/i, 'TS', '#3178c6'], [/\.(jsx)$/i, 'JSX', '#d4a72c'], [/\.(js|mjs|cjs)$/i, 'JS', '#d4a72c'],
  [/\.(vue)$/i, 'V', '#41b883'], [/\.(svelte)$/i, 'S', '#ff3e00'], [/\.(astro)$/i, 'A', '#ff5d01'],
  [/\.(py|pyi)$/i, 'PY', '#3572a5'], [/\.(go)$/i, 'GO', '#00add8'], [/\.(rs)$/i, 'RS', '#dea584'], [/\.(rb|rake)$/i, 'RB', '#cc342d'],
  [/\.(php)$/i, 'PHP', '#4f5d95'], [/\.(cs)$/i, 'C#', '#178600'], [/\.(c)$/i, 'C', '#555d6b'], [/\.(cpp|cc|cxx|hpp|hh|hxx)$/i, 'C++', '#f34b7d'],
  [/\.(h)$/i, 'H', '#6c7a89'], [/\.(swift)$/i, 'SW', '#f05138'], [/\.(dart)$/i, 'DT', '#00b4ab'],
  [/\.(html?|xhtml|jsp)$/i, '<>', '#e34c26'], [/\.(xml|xsd|xsl|svg)$/i, '<>', '#0060ac'], [/\.(css)$/i, '#', '#563d7c'],
  [/\.(scss|sass)$/i, '#', '#c6538c'], [/\.(less)$/i, '#', '#1d365d'],
  [/\.(json|jsonc)$/i, '{}', '#c9a227'], [/\.(ya?ml)$/i, 'Y', '#cb171e'], [/\.(toml|ini|cfg|conf|properties|env)$/i, 'CF', '#6d8086'],
  [/\.(md|markdown|mdx)$/i, 'M', '#519aba'], [/\.(sql)$/i, 'DB', '#e38c00'], [/\.(sh|bash|zsh)$/i, '$', '#4eaa25'],
  [/\.(bat|cmd|ps1|psm1)$/i, '>', '#3f8bd1'], [/\.(log)$/i, 'LG', '#8b949e'], [/\.(txt|text)$/i, 'TX', '#8b949e'],
  [/\.(csv|tsv)$/i, 'CS', '#2ea043'], [/\.(lock)$/i, 'LK', '#8b949e'], [/(^|\/)dockerfile$/i, 'DK', '#2496ed'],
  [/(^|\/)(makefile|cmakelists\.txt)$/i, 'MK', '#6d8086'], [/(^|\/)\.git(ignore|attributes|modules)$/i, 'GT', '#f14e32'],
  [/\.(png|jpe?g|gif|bmp|ico|webp)$/i, 'IM', '#a074c4'], [/\.(pdf|zip|jar|war|exe|dll|class|so)$/i, 'BN', '#8b949e'],
];
function fileBadge(name) {
  for (const [re, label, color] of FILE_BADGES) {
    if (re.test(name)) return `<span class="fbadge" style="--c:${color}">${escapeHtml(label)}</span>`;
  }
  return '<span class="fbadge plain" style="--c:#8b949e">·</span>';
}
const FOLDER_SVG = '<svg class="fold" viewBox="0 0 16 16" width="15" height="15"><path d="M1.5 3.5h4.2l1.4 1.5h7.4v8.5h-13z" fill="#e8b04a" stroke="#c9902a" stroke-width=".8"/></svg>';
function iconFor(name) { return fileBadge(name); }

