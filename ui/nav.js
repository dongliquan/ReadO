// ===== Component navigation: Monaco providers =====
// Every open file's model has the URI reado:/<key>, so Monaco's own UI —
// F12 / Ctrl+click (go to definition), Alt+F12 (peek), Shift+F12 (references),
// Ctrl+Shift+O (quick outline) — can point at other files. Files a peek or
// reference list shows but that are not open as tabs get a read-only "peek
// model" (small LRU); opening one as a tab adopts that model.
const _uriKeys = new Map();  // uri string -> file key
function uriFor(key) {
  const uri = monaco.Uri.from({ scheme: 'reado', path: '/' + key.replace(/\\/g, '/') });
  _uriKeys.set(uri.toString(), key);
  return uri;
}
function keyForUri(uri) { return _uriKeys.get(uri.toString()) || null; }
const _peekModels = new Map();  // key -> model (not open as a tab)
const PEEK_MODELS_MAX = 60;
function createDocModel(key, text) {
  const uri = uriFor(key);
  const existing = monaco.editor.getModel(uri);
  if (existing) {  // adopt a peek model
    _peekModels.delete(key);
    if (existing.getValue() !== text) existing.setValue(text);
    monaco.editor.setModelLanguage(existing, langFor(key));
    return existing;
  }
  return monaco.editor.createModel(text, langFor(key), uri);
}
async function ensureModel(key) {
  if (docs.has(key)) return docs.get(key).model;
  if (_peekModels.has(key)) {
    const m = _peekModels.get(key);
    _peekModels.delete(key);
    _peekModels.set(key, m);  // LRU touch
    return m;
  }
  const r = await fetch('/api/file?path=' + encodeURIComponent(key));
  if (!r.ok) return null;
  const data = await r.json();
  if (docs.has(key)) return docs.get(key).model;
  const model = monaco.editor.getModel(uriFor(key)) || monaco.editor.createModel(data.text, langFor(key), uriFor(key));
  _peekModels.set(key, model);
  while (_peekModels.size > PEEK_MODELS_MAX) {
    const [oldKey, old] = _peekModels.entries().next().value;
    _peekModels.delete(oldKey);
    if (!panes.some(p => p.editor.getModel() === old)) old.dispose();
  }
  return model;
}

const _gotoCache = new Map();  // Ctrl+hover asks for the definition repeatedly
function fetchGoto(symbol, fromKey) {
  const k = symbol + '\u0000' + fromKey;
  const hit = _gotoCache.get(k);
  if (hit && Date.now() - hit.t < 10000) return hit.p;
  const p = fetch(`/api/goto?symbol=${encodeURIComponent(symbol)}&from=${encodeURIComponent(fromKey)}`)
    .then(r => r.ok ? r.json() : { results: [] }).catch(() => ({ results: [] }));
  _gotoCache.set(k, { t: Date.now(), p });
  if (_gotoCache.size > 200) _gotoCache.delete(_gotoCache.keys().next().value);
  return p;
}
async function locationsFor(hits, symbol, maxFiles) {
  const files = [...new Set(hits.map(h => h.path))].slice(0, maxFiles);
  const models = new Map();
  await Promise.all(files.map(async f => {
    try { models.set(f, await ensureModel(f)); } catch (e) {}
  }));
  const out = [];
  for (const h of hits) {
    const m = models.get(h.path);
    if (!m) continue;
    const line = Math.min(h.line, m.getLineCount());
    const col = h.col || 1;
    out.push({ uri: m.uri, range: new monaco.Range(line, col, line, col + (h.col ? symbol.length : 0)) });
  }
  return { locations: out, files: files.length, allFiles: new Set(hits.map(h => h.path)).size };
}
const definitionProvider = {
  async provideDefinition(model, position) {
    const word = model.getWordAtPosition(position);
    const key = keyForUri(model.uri);
    if (!key) return null;
    const tag = componentTagAt(model, position);
    if (tag) {  // <ItemTop>: the component's file, opened in the other pane
      let hits = await fetchComponent(tag.name, key);
      if (!hits.length && /^[A-Z]/.test(tag.name)) {
        const g = await fetchGoto(tag.name, isAbsKey(key) ? '' : key);
        if (g.declarations) hits = g.results.filter(h => h.kind === 'type' || h.kind === 'function');
      }
      return (await locationsFor(hits.slice(0, 30), tag.name, 30)).locations;
    }
    // import paths / imported names: the server reads the imports of this buffer
    const link = await fetchLink(model, position);
    if (link.results && link.results.length) {
      return (await locationsFor(link.results.slice(0, 40), link.name || '', 40)).locations;
    }
    if (link.kind === 'external' || link.kind === 'missing') {
      if (explicitNavRecent()) showToast(linkFailText(link), true);
      return [];
    }
    if (!word || word.word.length < 2) return null;
    const data = await fetchGoto(word.word, isAbsKey(key) ? '' : key);
    if (!data.declarations) return [];
    // jumping to the line we are on is not a definition jump
    const hits = data.results.filter(h => !(h.path === key && h.line === position.lineNumber)).slice(0, 30);
    return (await locationsFor(hits.length ? hits : data.results.slice(0, 1), word.word, 30)).locations;
  },
};
const referenceProvider = {
  async provideReferences(model, position, context) {
    const word = model.getWordAtPosition(position);
    const key = keyForUri(model.uri);
    if (!word || !key) return [];
    let data;
    try {
      const r = await fetch(`/api/refs?symbol=${encodeURIComponent(word.word)}&from=${encodeURIComponent(isAbsKey(key) ? '' : key)}`);
      data = await r.json();
    } catch (e) { return []; }
    let hits = data.results || [];
    if (context && context.includeDeclaration === false) hits = hits.filter(h => !h.decl);
    const res = await locationsFor(hits, word.word, 60);
    if (res.allFiles > res.files || data.truncated) {
      showToast(`references: showing ${res.files} of ${res.allFiles}${data.truncated ? '+' : ''} files — use Find in Files for all`, true);
    }
    return res.locations;
  },
};
const documentSymbolProvider = {
  displayName: 'ReadO',
  async provideDocumentSymbols(model) {
    const key = keyForUri(model.uri);
    const syms = await outlineFor(model, key || 'file.' + model.getLanguageId());
    return syms.map(s => ({
      name: s.name, detail: s.detail || '', kind: symbolKind(s.kind), tags: [],
      range: new monaco.Range(s.line, 1, s.endLine || s.line, model.getLineMaxColumn(Math.min(s.endLine || s.line, model.getLineCount()))),
      selectionRange: new monaco.Range(s.line, s.col || 1, s.line, (s.col || 1) + s.name.length),
    }));
  },
};
function symbolKind(kind) {
  const K = monaco.languages.SymbolKind;
  const map = {
    class: K.Class, interface: K.Interface, enum: K.Enum, struct: K.Struct, record: K.Class, trait: K.Interface,
    type: K.TypeParameter, typedef: K.TypeParameter, union: K.Struct, object: K.Object, annotation: K.Interface,
    method: K.Method, function: K.Function, func: K.Function, fn: K.Function, def: K.Function, constructor: K.Constructor,
    macro: K.Function, procedure: K.Function, subroutine: K.Function, trigger: K.Event,
    field: K.Field, member: K.Field, property: K.Property, variable: K.Variable, var: K.Variable, const: K.Constant,
    constant: K.Constant, enumerator: K.EnumMember, module: K.Module, namespace: K.Namespace, package: K.Package,
    table: K.Struct, view: K.Struct, rule: K.Key, heading: K.String, symbol: K.Variable,
  };
  return map[kind] != null ? map[kind] : K.Variable;
}

// Outline of a buffer: the server (ctags on the current text) when it can,
// else the regex patterns below. Cached per model version.
const _outlineCache = new WeakMap();
async function outlineFor(model, key) {
  const v = model.getAlternativeVersionId();
  const c = _outlineCache.get(model);
  if (c && c.v === v) return c.p;
  const p = (async () => {
    try {
      const r = await fetch('/api/outline', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: baseName(key), text: model.getValue() }),
      });
      if (r.ok) {
        const data = await r.json();
        if (data.symbols) return data.symbols;
      }
    } catch (e) {}
    return regexOutline(model, key);
  })();
  _outlineCache.set(model, { v, p });
  return p;
}
function regexOutline(model, key) {
  const patterns = symbolPatterns(model.getLanguageId() || langFor(key));
  const out = [];
  const n = model.getLineCount();
  for (let i = 1; i <= n && out.length < 5000; i++) {
    const line = model.getLineContent(i);
    for (const { re, kind } of patterns) {
      const m = line.match(re);
      if (m && m[1]) {
        out.push({ name: m[1], kind, line: i, col: line.indexOf(m[1]) + 1 });
        break;
      }
    }
  }
  return out;
}

function registerNavProviders() {
  const ids = monaco.languages.getLanguages().map(l => l.id).concat(['plaintext']);
  for (const id of ids) {
    monaco.languages.registerDefinitionProvider(id, definitionProvider);
    monaco.languages.registerReferenceProvider(id, referenceProvider);
    monaco.languages.registerDocumentSymbolProvider(id, documentSymbolProvider);
  }
  // a jump into another file opens it as a ReadO tab
  monaco.editor.registerEditorOpener({
    async openCodeEditor(source, resource, selectionOrPosition) {
      const key = keyForUri(resource);
      if (!key) return false;
      let idx = panes.findIndex(p => p.editor === source);
      if (idx < 0) idx = activePaneIdx;
      pushNav();
      // every jump into another file (definition, import, component, a pick
      // from a peek / reference list) opens in the next pane, unless
      // Ctrl+Alt was held or the setting is off
      const samePane = takeComponentSamePane();
      if (STATE.componentBeside !== false && !samePane) {
        const sel = !selectionOrPosition ? null : monaco.Range.isIRange(selectionOrPosition) ? selectionOrPosition
          : new monaco.Range(selectionOrPosition.lineNumber, selectionOrPosition.column,
                             selectionOrPosition.lineNumber, selectionOrPosition.column);
        return openInOtherPane(key, idx, true, sel);
      }
      _navSuppress = true;
      try {
        if (!(await openFileInPane(idx, key))) return false;
        const ed = panes[idx].editor;
        if (selectionOrPosition) {
          const sel = monaco.Range.isIRange(selectionOrPosition)
            ? selectionOrPosition
            : new monaco.Range(selectionOrPosition.lineNumber, selectionOrPosition.column,
                               selectionOrPosition.lineNumber, selectionOrPosition.column);
          ed.setSelection(sel);
          ed.revealRangeInCenterIfOutsideViewport(sel);
        }
        ed.focus();
      } finally {
        _navSuppress = false;
      }
      return true;
    },
  });
  // IntelliJ keys next to the VS Code ones Monaco already has
  monaco.editor.addKeybindingRules([
    { keybinding: monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyB, command: 'editor.action.revealDefinition' },
    { keybinding: monaco.KeyMod.Alt | monaco.KeyCode.F7, command: 'editor.action.goToReferences' },
  ]);
}
// Run a Monaco action on the active editor (used when the editor is not focused).
function runEditorAction(id) {
  const ed = editor;
  if (!ed || !ed.getModel()) return;
  ed.focus();
  // goto / peek / references are Action2 commands: getAction() does not see them
  const action = ed.getAction(id);
  if (action) action.run();
  else ed.trigger('keyboard', id, null);
}

// ===== Component tags: <ItemTop> / <item-top> -> its file, opened beside =====
// In .vue / .jsx / .tsx / .svelte / .astro (and .js for React) a PascalCase or
// kebab-case tag name is a component. F12 / Ctrl+B / Ctrl+click go through
// the normal definition provider (so peek lists several candidates); the
// target opens in the *other* split pane (created if needed). With the
// "click a component tag" option a plain click on the tag name does the same
// but leaves the cursor and focus where they are, so editing is not disturbed.
const COMPONENT_FILE_RE = /\.(vue|jsx|tsx|svelte|astro|mdx|js)$/i;
// Vue / router / Nuxt built-ins and hyphenated SVG / HTML elements: never files
const BUILTIN_TAGS = new Set(['component', 'transition', 'transitiongroup', 'keepalive', 'slot', 'template',
  'teleport', 'suspense', 'routerview', 'routerlink', 'nuxtlink', 'nuxtpage', 'nuxtlayout', 'nuxtchild',
  'clientonly', 'nuxtloadingindicator', 'nuxterrorboundary', 'fragment', 'strictmode', 'profiler',
  'fontface', 'fontfacesrc', 'fontfaceuri', 'fontfaceformat', 'fontfacename', 'missingglyph',
  'colorprofile', 'annotationxml']);
function componentTagAt(model, position) {
  const key = keyForUri(model.uri) || '';
  if (!COMPONENT_FILE_RE.test(key)) return null;
  const line = model.getLineContent(position.lineNumber);
  const re = /<\/?([A-Za-z][\w-]*(?:\.[A-Za-z][\w-]*)*)/g;
  let m;
  while ((m = re.exec(line))) {
    const start = m.index + m[0].length - m[1].length + 1;  // 1-based column of the name
    const end = start + m[1].length;
    if (position.column < start || position.column > end) continue;
    // `Array<Foo>`, `ref<Item>()`: a generic (identifier right before "<"),
    // unlike `return <Foo />` or `? <Foo/> : …`
    const before = line.slice(0, m.index);
    if (/[\w$)\]]$/.test(before)) return null;
    const name = m[1];
    const isComponent = /^[A-Z]/.test(name) || name.includes('-');
    if (!isComponent || BUILTIN_TAGS.has(name.replace(/[-_.]/g, '').toLowerCase())) return null;
    return { name, range: new monaco.Range(position.lineNumber, start, position.lineNumber, end) };
  }
  return null;
}
async function fetchComponent(name, fromKey) {
  try {
    const r = await fetch(`/api/component?name=${encodeURIComponent(name)}&from=${encodeURIComponent(isAbsKey(fromKey) ? '' : fromKey)}`);
    return r.ok ? (await r.json()).results || [] : [];
  } catch (e) { return []; }
}
// ===== Links: import paths and imported names -> file + position =====
// The server reads this buffer's imports (unsaved edits count) and resolves
// paths / aliases / re-exports; see link_at in server.py. Asked lazily (Ctrl+hover,
// hover on an import line, click, F12) and cached per buffer version + token.
const _linkCache = new Map();  // uri|version|line -> [{range, res}]
async function fetchLink(model, position) {
  const key = keyForUri(model.uri);
  if (!key) return { kind: 'none' };
  const ck = `${model.uri}|${model.getAlternativeVersionId()}|${position.lineNumber}`;
  const list = _linkCache.get(ck) || [];
  const hit = list.find(x => x.range && position.column >= x.range[0] && position.column <= x.range[1]);
  if (hit) return hit.res;
  const text = model.getValueLength() < 1_500_000 ? model.getValue() : undefined;  // huge buffer: the server reads the file
  let res = { kind: 'none' };
  try {
    const r = await fetch('/api/link', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ from: key, text, line: position.lineNumber, col: position.column }),
    });
    if (r.ok) res = await r.json();
  } catch (e) {}
  if (res.range) {
    list.push({ range: res.range, res });
    _linkCache.set(ck, list);
    if (_linkCache.size > 300) _linkCache.delete(_linkCache.keys().next().value);
  }
  return res;
}
function linkFailText(link) {
  const what = link.name ? `${link.name} (${link.spec})` : link.spec || 'link';
  return link.kind === 'external' ? `${what}: a package / library outside this folder — not opened`
    : `${what}: no such file`;
}
function linkHoverText(link) {
  if (link.results && link.results.length) {
    const r = link.results[0];
    return '→ `' + r.path + (r.line > 1 ? ':' + r.line : '') + '`'
      + (link.results.length > 1 ? `  (+${link.results.length - 1} more)` : '');
  }
  return link.kind === 'external' || link.kind === 'missing' ? linkFailText(link) : '';
}
// F12 / Ctrl+B / Ctrl+click just happened (not a Ctrl+hover): failures get a toast
let _explicitNavAt = 0;
function explicitNavRecent() { return Date.now() - _explicitNavAt < 2000; }
window.addEventListener('keydown', e => {
  if (e.key === 'F12' || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b')) _explicitNavAt = Date.now();
}, true);
// Lines where a plain click (with the click option on) follows links: imports,
// includes, src= / href=. Elsewhere it takes Ctrl+click / F12, so editing is not disturbed.
const IMPORT_LINE_RE = /^\s*(?:import|\}\s*from\s*['"]|export\b.*\bfrom\b|from\s+[\w.]+\s+import|#\s*(?:include|import)|use\s|using\s|(?:pub(?:\([^)]*\))?\s+)?(?:mod|use)\s|require(?:_relative|_once)?\b|include(?:_once)?\b|load\s|@import|@use|@forward)|\brequire\s*\(|\bimport\s*\(|\burl\(|\b(?:src|href)\s*=\s*["']/;
function isLinkLine(model, pos) {
  return IMPORT_LINE_RE.test(model.getLineContent(pos.lineNumber)) || goImportBlockLine(model, pos);
}
function goImportBlockLine(model, pos) {
  if (!/\.go$/i.test(keyForUri(model.uri) || '') || !/^\s*(\w+\s+)?"[^"]*"\s*$/.test(model.getLineContent(pos.lineNumber))) return false;
  for (let l = pos.lineNumber - 1; l >= 1 && l > pos.lineNumber - 200; l--) {
    const t = model.getLineContent(l);
    if (/^\s*\)/.test(t)) return false;
    if (/^\s*import\s*\(/.test(t)) return true;
  }
  return false;
}
// Open what a link points at from a click: beside (setting on) or here; several -> chooser
async function openLinkResults(link, fromIdx, focus) {
  const res = link.results || [];
  if (!res.length) { showToast(linkFailText(link), true); return; }
  const sel = r => new monaco.Range(r.line, r.col || 1, r.line, r.col || 1);
  const open = async (r, f) => {
    if (STATE.componentBeside === false) {
      pushNav();
      if (await openFileInPane(fromIdx, r.path)) {
        const ed = panes[fromIdx].editor;
        ed.setSelection(sel(r)); ed.revealRangeInCenterIfOutsideViewport(sel(r)); ed.focus();
      }
      return;
    }
    pushNav();
    await openInOtherPane(r.path, fromIdx, f, sel(r));
  };
  if (res.length === 1) return open(res[0], focus);
  pickFile(`${res.length} files for ${link.spec || link.name}`, res.map(r => r.path),
           path => open(res.find(r => r.path === path), true));
}
// Ctrl+Alt+click / Ctrl+Alt+F12: the next component jump opens in this pane
let _componentSamePaneUntil = 0;
function componentSamePaneOnce() { _componentSamePaneUntil = Date.now() + 3000; }
function takeComponentSamePane() {
  const on = _componentSamePaneUntil > Date.now();
  _componentSamePaneUntil = 0;
  return on;
}
// Open key beside fromIdx: in another pane that already has it as a tab (that
// tab is just activated), else in the next pane (cyclic, reading order). With
// one pane, split to the right first.
// focus=false keeps the cursor and focus in the source editor.
async function openInOtherPane(key, fromIdx, focus, selection, gotoLine, find) {
  if (fromIdx == null || fromIdx < 0 || fromIdx >= panes.length) fromIdx = activePaneIdx;
  const srcPane = panes[fromIdx];
  if (panes.length < 2 && !splitPane(fromIdx, 'row')) return false;
  fromIdx = panes.indexOf(srcPane);
  let target = (fromIdx + 1) % panes.length;
  for (let s = 1; s < panes.length; s++) {
    const i = (fromIdx + s) % panes.length;
    if (panes[i].tabs.has(key)) { target = i; break; }
  }
  const srcEditor = srcPane.editor;
  const srcPos = srcEditor.getPosition();
  if (!(await openFileInPane(target, key, gotoLine, find))) return false;
  fromIdx = panes.indexOf(srcPane);
  const ed = panes[target].editor;
  if (selection) {
    ed.setSelection(selection);
    ed.revealRangeInCenterIfOutsideViewport(selection);
  }
  if (focus) {
    ed.focus();
  } else {
    setActivePane(fromIdx);
    if (srcPos) srcEditor.setPosition(srcPos);
    srcEditor.focus();
  }
  saveState();
  return true;
}
// Plain-click / picker path (not through Monaco's goto): resolves, then opens
// beside or asks which one.
async function openComponentBeside(tag, fromIdx, focus) {
  const p = panes[fromIdx];
  const key = p && p.currentPath;
  if (!key) return;
  let hits = await fetchComponent(tag.name, key);
  if (!hits.length) {  // e.g. React: export function ItemTop() in some file
    const g = await fetchGoto(tag.name, isAbsKey(key) ? '' : key);
    if (g.declarations) hits = g.results.filter(h => h.kind === 'type' || h.kind === 'function');
  }
  if (!hits.length) { showToast(`component ${tag.name} not found`, true); return; }
  // setting off: the component replaces the current file in this pane
  const open = STATE.componentBeside === false
    ? path => { pushNav(); return openFileInPane(fromIdx, path); }
    : (path, f) => openInOtherPane(path, fromIdx, f);
  if (hits.length === 1) {
    await open(hits[0].path, focus);
    return;
  }
  pickFile(`${hits.length} files for <${tag.name}>`, hits.map(h => h.path), path => open(path, true));
}
// Quick Open as a chooser for a fixed list of files
let _pickHandler = null;
let _pickAll = null;
function pickFile(title, paths, onPick) {
  openQO('');
  _qoMode = 'pick';
  _pickHandler = onPick;
  const inp = document.getElementById('qoInput');
  inp.placeholder = title + ' — ↑/↓, Enter';
  _qoItems = paths.map((p, i) => ({ label: p, path: p, meta: i === 0 ? 'nearest' : '' }));
  _qoSel = 0;
  renderQO();
}

// What a spot of the buffer navigates to, for hover links and plain clicks:
// an import path / imported name (server link), else a symbol the index knows
// a declaration for (not the declaration we are on). null: not a link.
const _navCache = new Map();  // uri|version|line|word -> result
const NOT_LINKS = new Set(('if else for while do switch case break continue return function class const let var new this super '
  + 'import export from default true false null undefined void typeof instanceof in of try catch finally throw async await '
  + 'public private protected static final abstract extends implements interface package def self None True False lambda '
  + 'and or not is pass yield with as elif int long float double boolean char byte short string String Object').split(' '));
async function resolveNavAt(model, pos) {
  const key = keyForUri(model.uri);
  if (!key) return null;
  const link = await fetchLink(model, pos);
  if (link.range && link.kind !== 'none') {
    const ok = !!(link.results && link.results.length);
    return { range: link.range, results: ok ? link.results : [], link, fail: !ok };
  }
  const w = model.getWordAtPosition(pos);
  if (!w || w.word.length < 2 || NOT_LINKS.has(w.word) || /^\d/.test(w.word)) return null;
  const ck = `${model.uri}|${model.getAlternativeVersionId()}|${pos.lineNumber}|${w.startColumn}`;
  if (_navCache.has(ck)) return _navCache.get(ck);
  let res = null;
  try {
    const r = await fetch(`/api/goto?index_only=1&symbol=${encodeURIComponent(w.word)}&from=${encodeURIComponent(isAbsKey(key) ? '' : key)}`);
    const data = r.ok ? await r.json() : null;
    const all = data && data.declarations ? data.results : [];
    // on a declaration itself: not a link (it would jump to some other `run`)
    const here = all.some(h => h.path === key && h.line === pos.lineNumber);
    const hits = here ? [] : all;
    if (hits.length) res = { range: [w.startColumn, w.endColumn], results: hits.slice(0, 30), link: { name: w.word, spec: w.word, results: hits }, fail: false };
    else if (here) res = { range: [w.startColumn, w.endColumn], decl: true, name: w.word };  // a declaration: show its usages count
  } catch (e) {}
  _navCache.set(ck, res);
  if (_navCache.size > 500) _navCache.delete(_navCache.keys().next().value);
  return res;
}

// Links without Ctrl (setting, on by default): hovering a component tag, an
// import path / name or a symbol with a known declaration underlines it (pointer
// cursor, resolved path in the tooltip); a plain click opens it beside and
// leaves the cursor and focus where they are. Alt+click just places the cursor,
// a double-click selects the word, a drag selects text. With the setting off,
// Ctrl+hover / Ctrl+click / F12 do the same.
function attachComponentMouse(pane) {
  const ed = pane.editor;
  const hoverDeco = ed.createDecorationsCollection([]);
  let pending = null, hoverTimer = null, hoverSeq = 0, decoRange = null, downAt = null;
  const setDeco = (range, msg, cls) => {
    decoRange = range;
    hoverDeco.set(range ? [{ range, options: { inlineClassName: cls || 'reado-taglink', hoverMessage: { value: msg } } }] : []);
  };
  const beside = () => STATE.componentBeside !== false;
  const linksOn = () => STATE.componentClick !== false;
  ed.onDidChangeModel(() => { clearTimeout(hoverTimer); setDeco(null); });  // a range of the previous file means nothing here
  ed.onDidChangeModelContent(() => { if (decoRange) setDeco(null); });
  ed.onMouseMove(e => {
    const pos = e.target && e.target.position;
    const model = ed.getModel();
    clearTimeout(hoverTimer);
    if (!pos || !model || e.target.type !== monaco.editor.MouseTargetType.CONTENT_TEXT || (e.event.buttons & 1)) { setDeco(null); return; }
    if (decoRange && decoRange.containsPosition(pos)) return;
    const ctrl = e.event.ctrlKey || e.event.metaKey;
    if (!ctrl && !linksOn()) { setDeco(null); return; }
    const tag = componentTagAt(model, pos);
    if (tag) {
      setDeco(tag.range, !beside() ? `open \`${tag.name}\` here`
        : `open \`${tag.name}\` beside  ·  Alt+click: put the cursor here  ·  Ctrl+Alt+click: open in this pane`);
      return;
    }
    if (decoRange) setDeco(null);
    const seq = ++hoverSeq;
    hoverTimer = setTimeout(async () => {
      const nav = await resolveNavAt(model, pos);
      if (seq !== hoverSeq || ed.getModel() !== model) return;
      if (nav && nav.decl) {  // on a declaration: how often it is used (not a link)
        const n = await usageCount(nav.name, keyForUri(model.uri));
        if (seq !== hoverSeq || ed.getModel() !== model || !n) return;
        setDeco(new monaco.Range(pos.lineNumber, nav.range[0], pos.lineNumber, nav.range[1]),
                `\`${nav.name}\`: ${n.n}${n.more ? '+' : ''} usage${n.n === 1 ? '' : 's'}  ·  Shift+F12: list them`, 'reado-decl');
        return;
      }
      if (!nav || (nav.fail && !ctrl)) { setDeco(null); return; }  // not a link: a click just moves the cursor
      const msg = linkHoverText(nav.link);
      setDeco(new monaco.Range(pos.lineNumber, nav.range[0], pos.lineNumber, nav.range[1]),
              msg + (nav.fail ? '' : !linksOn() ? '' : beside() ? '  ·  click: open beside  ·  Alt+click: put the cursor here' : '  ·  click: open'));
    }, 90);
  });
  ed.onMouseLeave(() => { clearTimeout(hoverTimer); setDeco(null); });
  ed.onMouseDown(e => {
    if (e.event.detail >= 2 && pending) { clearTimeout(pending); pending = null; }  // double-click selects a word
    if (e.event.ctrlKey || e.event.metaKey) _explicitNavAt = Date.now();
    // Ctrl+Alt+click: Monaco's goto (on mouse up) opens the target in this pane
    if (e.event.ctrlKey && e.event.altKey && e.event.leftButton) componentSamePaneOnce();
    downAt = { x: e.event.posx, y: e.event.posy, t: Date.now() };
  });
  ed.onMouseUp(e => {
    const ev = e.event;
    const down = downAt;
    downAt = null;
    if (!ev.leftButton || ev.detail !== 1 || !e.target || e.target.type !== monaco.editor.MouseTargetType.CONTENT_TEXT || !e.target.position) return;
    const model = ed.getModel();
    const pos = e.target.position;
    // Alt+click on a link: just the cursor there (not Monaco's extra cursor)
    if (ev.altKey && !ev.ctrlKey && !ev.metaKey && !ev.shiftKey && linksOn() && decoRange && decoRange.containsPosition(pos)) {
      ed.setPosition(pos);
      return;
    }
    if (!linksOn() || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) return;
    // a drag (text selection) is not a click
    if (down && (Math.abs(ev.posx - down.x) + Math.abs(ev.posy - down.y) > 4 || Date.now() - down.t > 600)) return;
    const sel = ed.getSelection();
    if (sel && !sel.isEmpty()) return;
    const tag = model && componentTagAt(model, pos);
    const idx = panes.indexOf(pane);
    clearTimeout(pending);
    pending = setTimeout(async () => {
      pending = null;
      if (tag) return openComponentBeside(tag, idx, false);
      const nav = model && await resolveNavAt(model, pos);
      if (!nav || nav.decl || ed.getModel() !== model) return;
      if (nav.fail) { if (isLinkLine(model, pos)) showToast(linkFailText(nav.link), true); return; }
      openLinkResults(nav.link.results ? { ...nav.link, results: nav.results } : nav.link, panes.indexOf(pane), false);
    }, 260);
  });
}

// ===== Outline panel (sidebar) =====
let _sideTab = 'files';
function setSideTab(tab) {
  _sideTab = tab;
  if (STATE.sideTab !== tab) { STATE.sideTab = tab; saveState(); }
  refreshToolStrip();
  document.getElementById('tree').style.display = tab === 'files' ? '' : 'none';
  document.getElementById('outline').style.display = tab === 'outline' ? '' : 'none';
  document.getElementById('sideTitle').textContent = tab === 'outline' ? 'Outline' : 'Files';
  if (tab === 'outline') renderOutline();
}
// --- tool window strip: Files / Outline (the sidebar) and Git (its tool window) ---
function setSidebarOpen(open) {
  STATE.sideCollapsed = !open;
  document.body.classList.toggle('side-collapsed', !open);
  if (open && _sideTab === 'outline') renderOutline();
  refreshToolStrip();
  saveState();
}
function toggleSideTool(tab) {  // the same tool again folds the sidebar away
  if (!STATE.sideCollapsed && _sideTab === tab) return setSidebarOpen(false);
  setSideTab(tab);
  if (STATE.sideCollapsed) setSidebarOpen(true);
}
function toggleGitTool() {  // the same command as Git → Git Tool Window / Alt+9 / Ctrl+Shift+G
  if (CMD.get('git.toolwin')) runCommand('git.toolwin');
  else if (window.GitUI) GitUI.toggleWindow();
}
// Double-click on a tab's file name or the breadcrumb's file name: the source
// fills the window (sidebar and Git tool window away); again: they come back as
// they were (the hidden sidebar keeps its width and panel; STATE.maxRestore
// remembers which of the two were open, kept like the sidebar state).
function toggleSourceMax() {
  const gitOpen = () => !!(STATE.git && STATE.git.open);
  if (STATE.sideCollapsed && !gitOpen()) {  // already full: bring back what was open
    const r = STATE.maxRestore;
    STATE.maxRestore = null;
    if (r && r.git) toggleGitTool();
    if (!r || r.side) setSidebarOpen(true);  // the same as View › Sidebar
    else saveState();
    return;
  }
  STATE.maxRestore = { side: !STATE.sideCollapsed, git: gitOpen() };
  if (gitOpen()) toggleGitTool();
  if (!STATE.sideCollapsed) setSidebarOpen(false);
  else saveState();
}
// From two presses, not 'dblclick': the first click re-renders the tab strip, so
// the browser sees two different nodes and sends no dblclick.
let _nameDown = null;
document.addEventListener('mousedown', e => {
  const hit = e.button === 0 && e.target.closest && e.target.closest('.tab-item .tab-name, #crumbs .file');
  if (!hit) { _nameDown = null; return; }
  const d = _nameDown, now = Date.now();
  if (d && now - d.t < 500 && Math.abs(e.clientX - d.x) < 5 && Math.abs(e.clientY - d.y) < 5) {
    _nameDown = null;
    e.preventDefault();  // no word selection, no tab drag
    toggleSourceMax();
    return;
  }
  _nameDown = { t: now, x: e.clientX, y: e.clientY };
}, true);
// Only a missing git dims the icon; it stays clickable like the menu (the window then says why).
// A working folder that is not itself a repository (repositories below it) is normal.
let _gitAvail = null;  // null: unknown, false: git not installed / too old
async function refreshGitAvail() {
  try {
    const d = await (await fetch('/api/git/info', { cache: 'no-store' })).json();
    _gitAvail = !!d.available;
  } catch (e) { _gitAvail = null; }
  refreshToolStrip();
}
function refreshToolStrip() {
  try { _refreshToolStrip(); } catch (e) {}  // may run while the script is still loading (CMD / _sideTab not set yet)
}
function _refreshToolStrip() {
  const strip = document.getElementById('toolStrip');
  if (!strip) return;
  strip.querySelectorAll('.tsb').forEach(b => {
    const c = CMD.get(b.dataset.cmd), tool = b.dataset.tool;
    const name = tool === 'git' ? 'Git' : tool === 'files' ? 'Files' : tool === 'settings' ? 'Settings' : 'Outline';
    b.title = name + (c && c.keys ? ` (${c.keys})` : '') +
      (tool === 'git' && _gitAvail === false ? ' — git not found' : '');
    if (tool === 'settings') return;
    b.classList.toggle('active', tool === 'git' ? !!(STATE.git && STATE.git.open) : !STATE.sideCollapsed && _sideTab === tool);
    if (tool === 'git') b.classList.toggle('dim', _gitAvail === false);
  });
  const hide = document.getElementById('sideHide');
  const fc = CMD.get('view.files');
  if (hide) hide.title = 'Hide sidebar' + (fc && fc.keys ? ` (${fc.keys} again)` : '');
}
let _outlineTimer = null;
function scheduleOutline() {
  if (_sideTab !== 'outline') return;
  clearTimeout(_outlineTimer);
  _outlineTimer = setTimeout(renderOutline, 500);
}
async function renderOutline() {
  const box = document.getElementById('outline');
  const doc = currentDoc();
  const p = currentPane();
  if (!doc || !p) { box.innerHTML = '<div class="tree-empty">no file open</div>'; return; }
  const model = doc.model;
  const syms = await outlineFor(model, doc.key);
  if (currentDoc() !== doc) return;  // switched meanwhile
  box.innerHTML = '';
  if (!syms.length) { box.innerHTML = '<div class="tree-empty">no symbols found</div>'; return; }
  const filter = document.createElement('input');
  filter.className = 'outline-filter';
  filter.placeholder = 'filter symbols';
  box.appendChild(filter);
  const list = document.createElement('div');
  box.appendChild(list);
  const draw = () => {
    const q = filter.value.trim().toLowerCase();
    list.innerHTML = '';
    for (const s of syms) {
      if (q && !s.name.toLowerCase().includes(q)) continue;
      const row = document.createElement('div');
      row.className = 'node outline-item';
      row.style.paddingLeft = (6 + 12 * (s.depth || 0)) + 'px';
      row.title = `${s.kind} · line ${s.line}` + (s.scope ? ` · ${s.scope}` : '');
      const kind = document.createElement('span');
      kind.className = 'okind okind-' + (s.kind || '').replace(/\W/g, '');
      kind.textContent = (s.kind || '?').slice(0, 1).toUpperCase();
      const name = document.createElement('span');
      name.className = 'name';
      name.textContent = s.name;
      const ln = document.createElement('span');
      ln.className = 'oline';
      ln.textContent = s.line;
      row.append(kind, name, ln);
      row.onclick = () => {
        pushNav();
        const ed = currentPane().editor;
        const r = new monaco.Range(s.line, s.col || 1, s.line, (s.col || 1) + s.name.length);
        ed.setSelection(r);
        ed.revealRangeInCenter(r);
        ed.focus();
      };
      list.appendChild(row);
    }
  };
  filter.oninput = draw;
  draw();
}


// ===== Workspace symbols (Ctrl+T, Quick Open "#") =====
let _qoSymCat = '';
let _wsymSeq = 0;
async function runWorkspaceSymbols(q) {
  const list = document.getElementById('qoList');
  const seq = ++_wsymSeq;
  if (!q.trim()) {
    _qoItems = [];
    list.innerHTML = '<div class="qo-empty">type a class, method or field name — prefix, CamelHumps (<code>OSvc</code>) or part of it</div>';
    return;
  }
  let data;
  try {
    const r = await fetch(`/api/symbols?q=${encodeURIComponent(q)}&cat=${encodeURIComponent(_qoSymCat)}&limit=100`);
    data = await r.json();
  } catch (e) { return; }
  if (seq !== _wsymSeq || _qoMode !== 'wsymbol') return;
  showIndexStatus(data);
  if (!data.available) {
    _qoItems = [];
    list.innerHTML = '<div class="qo-empty">symbol index unavailable (ctags not found) — use <code>@</code> for the current file or Find in Files</div>';
    return;
  }
  if (!data.ready) {
    _qoItems = [];
    list.innerHTML = '<div class="qo-empty">indexing symbols… results appear when it is done</div>';
    setTimeout(() => { if (_qoMode === 'wsymbol' && seq === _wsymSeq) runWorkspaceSymbols(q); }, 1000);
    return;
  }
  _qoItems = data.results.map(x => ({
    label: x.name, path: x.path, line: x.line,
    meta: `${x.kind}${x.scope ? '  ·  ' + x.scope : ''}  ·  ${x.path}:${x.line}`,
  }));
  _qoSel = 0;
  renderQO(q);
  if (data.total > data.results.length) {
    const more = document.createElement('div');
    more.className = 'qo-empty';
    more.style.textAlign = 'left';
    more.style.padding = '6px 16px';
    more.textContent = `${data.results.length} of ${data.total} — type more to narrow`;
    list.appendChild(more);
  }
}
document.querySelectorAll('#qoCats .qo-cat').forEach(el => el.addEventListener('mousedown', e => {
  e.preventDefault();  // keep focus in the input
  _qoSymCat = el.dataset.cat;
  document.querySelectorAll('#qoCats .qo-cat').forEach(c => c.classList.toggle('active', c === el));
  runQO();
}));
function updateQOChrome() {
  const v = document.getElementById('qoInput').value;
  const ws = v.startsWith('#');
  document.getElementById('qoCats').style.display = ws ? '' : 'none';
  document.getElementById('qoHint').style.display = ws ? 'none' : '';
  const tab = v.startsWith('>') ? 'cmd' : v.startsWith('#') ? 'sym' : 'files';
  document.querySelectorAll('#qoModes .fd-tab').forEach(m => m.classList.toggle('active', m.dataset.fd === tab));
}
document.getElementById('qoInput').addEventListener('input', updateQOChrome);
function showIndexStatus(st) {
  const el = document.getElementById('sbIndex');
  const idx = document.getElementById('qoIdx');
  let text = '';
  if (!st || st.available === false) text = '';
  else if (!st.ready) text = 'indexing symbols…';
  else text = `${st.symbols.toLocaleString()} symbols` + (st.building ? ' (updating)' : '');
  if (el) el.textContent = text;
  if (idx) idx.textContent = text;
}
async function refreshIndexStatus() {
  if (!_settings.base_dir_exists) { showIndexStatus(null); return; }
  try {
    const r = await fetch('/api/tags-status');
    showIndexStatus(await r.json());
  } catch (e) {}
}
function onFolderOpened() { refreshIndexStatus(); }

