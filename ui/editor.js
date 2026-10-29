// marked preserves raw HTML and does not sanitize its output. Markdown files
// are project data, so rebuild the parsed tree from a small safe element and
// attribute allowlist before it reaches innerHTML. Nodes are built in the parsed
// (inert) document, so an <img> does not start loading before it is shown.
function sanitizeMarkdown(html) {
  const allowed = new Set([
    'A','BLOCKQUOTE','BR','CODE','DEL','EM','H1','H2','H3','H4','H5','H6',
    'HR','IMG','LI','OL','P','PRE','S','STRONG','TABLE','TBODY','TD','TH',
    'THEAD','TR','UL'
  ]);
  const drop = new Set(['SCRIPT','STYLE','IFRAME','OBJECT','EMBED','SVG','MATH',
    'FORM','INPUT','BUTTON','VIDEO','AUDIO','SOURCE']);
  const doc = new DOMParser().parseFromString(String(html), 'text/html');
  const clean = node => {
    const out = doc.createDocumentFragment();
    for (const child of [...node.childNodes]) {
      if (child.nodeType === Node.TEXT_NODE) {
        out.appendChild(doc.createTextNode(child.nodeValue));
        continue;
      }
      if (child.nodeType !== Node.ELEMENT_NODE) continue;
      const tag = child.tagName;
      if (drop.has(tag)) continue;
      const children = clean(child);
      if (!allowed.has(tag)) { out.appendChild(children); continue; }
      const el = doc.createElement(tag.toLowerCase());
      if (tag === 'A' || tag === 'IMG') {
        const raw = child.getAttribute(tag === 'A' ? 'href' : 'src') || '';
        try {
          const url = new URL(raw, location.href);
          const local = url.origin === location.origin && !raw.startsWith('//');
          const allowedProtocol = tag === 'A' && url.protocol === 'mailto:';
          if (local || allowedProtocol) el.setAttribute(tag === 'A' ? 'href' : 'src', raw);
        } catch (_) {}
        for (const attr of tag === 'A' ? ['title'] : ['alt','title']) {
          if (child.hasAttribute(attr)) el.setAttribute(attr, child.getAttribute(attr));
        }
      } else if (tag === 'CODE') {
        const cls = child.getAttribute('class') || '';
        const language = cls.match(/(?:^|\s)language-[\w+-]+(?:\s|$)/);
        if (language) el.className = language[0].trim();
      }
      el.appendChild(children);
      out.appendChild(el);
    }
    return out;
  };
  const fragment = clean(doc.body);
  const container = doc.createElement('div');
  container.appendChild(fragment);
  return container.innerHTML;
}

let _monacoReady;
const monacoReady = new Promise(resolve => { _monacoReady = resolve; });
require.config({ paths: { vs: '/vendor/monaco/vs' } });
require(['vs/editor/editor.main'], () => {
  // Atom One Light theme
  monaco.editor.defineTheme('one-light', {
    base: 'vs',
    inherit: true,
    rules: [
      { token: '', foreground: '383a42', background: 'fafafa' },
      { token: 'comment', foreground: 'a0a1a7', fontStyle: 'italic' },
      { token: 'keyword', foreground: 'a626a4' },
      { token: 'string', foreground: '50a14f' },
      { token: 'number', foreground: '986801' },
      { token: 'type', foreground: 'c18401' },
      { token: 'type.identifier', foreground: 'c18401' },
      { token: 'identifier', foreground: '383a42' },
      { token: 'delimiter', foreground: '383a42' },
      { token: 'tag', foreground: 'e45649' },
      { token: 'attribute.name', foreground: 'b76b01' },
      { token: 'attribute.value', foreground: '50a14f' },
    ],
    colors: {
      'editor.background': '#fafafa',
      'editor.foreground': '#383a42',
      'editor.lineHighlightBackground': '#f0f0f1',
      'editorLineNumber.foreground': '#a0a1a7',
      'editorLineNumber.activeForeground': '#383a42',
      'editorCursor.foreground': '#526fff',
      'editor.selectionBackground': '#e5e5e6',
      'editor.inactiveSelectionBackground': '#f0f0f1',
    },
  });
  // Atom One Dark theme
  monaco.editor.defineTheme('one-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: '', foreground: 'abb2bf', background: '282c34' },
      { token: 'comment', foreground: '5c6370', fontStyle: 'italic' },
      { token: 'keyword', foreground: 'c678dd' },
      { token: 'string', foreground: '98c379' },
      { token: 'number', foreground: 'd19a66' },
      { token: 'type', foreground: 'e5c07b' },
      { token: 'type.identifier', foreground: 'e5c07b' },
      { token: 'identifier', foreground: 'abb2bf' },
      { token: 'delimiter', foreground: 'abb2bf' },
      { token: 'tag', foreground: 'e06c75' },
      { token: 'attribute.name', foreground: 'd19a66' },
      { token: 'attribute.value', foreground: '98c379' },
    ],
    colors: {
      'editor.background': '#282c34',
      'editor.foreground': '#abb2bf',
      'editor.lineHighlightBackground': '#2c313a',
      'editorLineNumber.foreground': '#5c6370',
      'editorLineNumber.activeForeground': '#abb2bf',
      'editorCursor.foreground': '#528bff',
      'editor.selectionBackground': '#3e4451',
      'editor.inactiveSelectionBackground': '#363c46',
    },
  });

  applyLangDiagnostics();
  // Create the first pane (single-view default)
  createPane();
  registerNavProviders();
  _monacoReady();
});

// Monaco's TypeScript / JavaScript checker sees one file without its project (no
// tsconfig, node_modules or "@/" aliases), so "Cannot find module" / "Cannot find
// name" squiggles are noise here: off unless Settings → "Show language diagnostics".
function applyLangDiagnostics() {
  const ts = monaco.languages.typescript;
  if (!ts) return;
  const off = !STATE.langDiagnostics;
  const opts = { noSemanticValidation: off, noSyntaxValidation: off, noSuggestionDiagnostics: off };
  ts.typescriptDefaults.setDiagnosticsOptions(opts);
  ts.javascriptDefaults.setDiagnosticsOptions(opts);
  if (off) monaco.editor.getModels().forEach(m => ['typescript', 'javascript'].forEach(o => monaco.editor.setModelMarkers(m, o, [])));
}

// Theme (xO common spec, ch. 3): STATE.theme is the chosen mode — light, dark or
// system (default; follows the OS live). body.theme-light / theme-dark carry the
// resolved one, which getTheme() returns.
const THEME_MODES = ['light', 'dark', 'system'];
const THEME_LABEL = { light: 'Light', dark: 'Dark', system: 'System' };
const _darkMQ = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
function getThemeMode() {
  return THEME_MODES.includes(STATE.theme) ? STATE.theme : 'system';
}
function getTheme() {
  const m = getThemeMode();
  return m === 'dark' || (m === 'system' && _darkMQ && _darkMQ.matches) ? 'dark' : 'light';
}
// mode: light / dark / system (anything else counts as system)
function applyTheme(mode) {
  STATE.theme = THEME_MODES.includes(mode) ? mode : 'system';
  const theme = getTheme();
  document.body.classList.remove('theme-light', 'theme-dark');
  document.body.classList.add('theme-' + theme);
  try { refreshToolbar(); } catch (e) {}  // the toolbar code may not be loaded yet at the first call
  if (typeof monaco !== 'undefined' && monaco.editor) {
    monaco.editor.setTheme(theme === 'dark' ? 'one-dark' : 'one-light');
  }
  syncWindowBackground();
}
function setThemeMode(mode) {
  applyTheme(mode);
  saveState();
}
// toolbar button: Light → Dark → System
function cycleTheme() {
  setThemeMode(THEME_MODES[(THEME_MODES.indexOf(getThemeMode()) + 1) % THEME_MODES.length]);
}
if (_darkMQ) _darkMQ.addEventListener('change', () => { if (getThemeMode() === 'system') applyTheme('system'); });
// the window behind the page takes the theme color: maximizing / resizing shows it until the page repaints
function syncWindowBackground() {
  const api = window.pywebview && window.pywebview.api;
  if (api && api.win_background) {
    try { api.win_background(getTheme() === 'dark' ? '#282c34' : '#ffffff'); } catch (e) {}
  }
}
window.addEventListener('pywebviewready', syncWindowBackground);
function toggleTheme() {
  applyTheme(getTheme() === 'dark' ? 'light' : 'dark');
  saveState();
}
// Apply saved UI state immediately (before Monaco loads)
applyTheme(getThemeMode());
applyEditButton();
if (STATE.sidebarWidth) document.getElementById('sidebar').style.width = STATE.sidebarWidth + 'px';
if (STATE.sideCollapsed) document.body.classList.add('side-collapsed');

function showToast(msg, isErr) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.toggle('err', !!isErr);
  t.classList.add('show');
  clearTimeout(t._tm);
  t._tm = setTimeout(() => t.classList.remove('show'), 2200);
}

// Language for a file: a few explicit overrides, then whatever Monaco's own
// language registry declares for the extension / file name (~80 languages).
let _langIndex = null;
function monacoLangIndex() {
  if (_langIndex || typeof monaco === 'undefined') return _langIndex;
  const byExt = {}, byName = {};
  for (const l of monaco.languages.getLanguages()) {
    for (const e of l.extensions || []) byExt[e.toLowerCase()] = byExt[e.toLowerCase()] || l.id;
    for (const f of l.filenames || []) byName[f.toLowerCase()] = l.id;
  }
  return (_langIndex = { byExt, byName });
}
function langFor(name) {
  name = baseName(name);
  if (/^dockerfile$/i.test(name)) return 'dockerfile';
  const ext = name.split('.').pop().toLowerCase();
  const idx = monacoLangIndex();
  const map = {
    java:'java', kt:'kotlin', kts:'kotlin',
    js:'javascript', mjs:'javascript', cjs:'javascript', jsx:'javascript',
    ts:'typescript', tsx:'typescript',
    vue:'html', svelte:'html', html:'html', htm:'html',
    css:'css', scss:'scss', less:'less',
    json:'json', yaml:'yaml', yml:'yaml', toml:'plaintext',
    xml:'xml', md:'markdown', py:'python', go:'go', rs:'rust', rb:'ruby',
    php:'php', c:'c', cpp:'cpp', h:'cpp', hpp:'cpp', cs:'csharp',
    sh:'shell', bash:'shell', bat:'bat', ps1:'powershell',
    sql:'sql', gradle:'groovy', groovy:'groovy', properties:'ini', ini:'ini',
  };
  if (map[ext] && name.includes('.')) return map[ext];
  if (idx) {
    const lower = name.toLowerCase();
    if (idx.byName[lower]) return idx.byName[lower];
    if (lower.includes('.') && idx.byExt['.' + ext]) return idx.byExt['.' + ext];
  }
  return 'plaintext';
}

