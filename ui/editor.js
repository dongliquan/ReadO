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
  defineReadoThemes(monaco);  // One Light / One Dark (ui/themes.js)

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

function getTheme() {
  return STATE.theme === 'dark' ? 'dark' : 'light';
}
function applyTheme(theme) {
  STATE.theme = theme;  // first: refreshToolbar draws the toolbar icon from it
  document.body.classList.remove('theme-light', 'theme-dark');
  document.body.classList.add('theme-' + theme);
  try { refreshToolbar(); } catch (e) {}  // the toolbar code may not be loaded yet at the first call
  if (typeof monaco !== 'undefined' && monaco.editor) {
    monaco.editor.setTheme(theme === 'dark' ? 'one-dark' : 'one-light');
  }
  syncWindowBackground();
}
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
applyTheme(getTheme());
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

