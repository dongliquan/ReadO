// ===== Quick Open (Ctrl+P / Ctrl+Shift+N / Ctrl+G / Ctrl+Shift+O) =====
let _qoItems = [];
let _qoSel = 0;
let _qoMode = 'file'; // 'file' | 'line' | 'symbol'
let _qoQuery = '';
let _qoOffset = 0;
let _qoTotal = 0;
let _qoHasMore = false;
let _qoLoading = false;
const QO_PAGE = 50;

function openQO(prefill) {
  closeFIF();
  closeSettings();
  document.getElementById('qoInput').placeholder = 'Find File — file name  ·  >command  ·  %text in files  ·  #symbol  ·  @symbol in file  ·  :line';
  document.getElementById('qoBg').classList.add('show');
  const inp = document.getElementById('qoInput');
  inp.value = prefill || '';
  inp.focus();
  if (prefill === '#' || prefill === '@' || prefill === ':' || prefill === '>' || prefill === '%') inp.setSelectionRange(1, 1); else inp.select();
  updateQOChrome();
  runQO();
  // recent files that are gone leave the list (a deleted folder's files, …)
  pruneRecent().then(changed => { if (changed && qoIsOpen() && _qoMode === 'file') runQO(); });
}
function closeQO() {
  document.getElementById('qoBg').classList.remove('show');
  if (_qoFileHandler) setTimeout(() => { _qoFileHandler = null; }, 0);
}

async function runQO() {
  const raw = document.getElementById('qoInput').value;
  if (_qoMode === 'pick' && _pickHandler) {
    const all = _pickAll || (_pickAll = _qoItems.slice());
    _qoItems = all.filter(i => i.label.toLowerCase().includes(raw.toLowerCase()));
    _qoSel = 0;
    renderQO();
    return;
  }
  _pickAll = null;
  const list = document.getElementById('qoList');
  if (!raw) {
    _qoMode = 'file';
    _qoQuery = '';
    _qoOffset = 0;
    _qoTotal = 0;
    _qoHasMore = false;
    // empty input: recently opened files (Ctrl+E)
    _qoItems = STATE.recent.filter(k => k !== currentPath).slice(0, 30)
      .map(k => ({ label: k, path: k, meta: isAbsKey(k) ? 'recent · outside base dir' : 'recent' }));
    _qoSel = 0;
    if (_qoItems.length) { renderQO(); return; }
    list.innerHTML = '<div class="qo-empty">type a file name (use <code>*</code> wildcard), <code>:42</code>, or <code>@symbol</code></div>';
    return;
  }
  if (raw.startsWith('>')) {
    _qoMode = 'command';
    runCommandSearch(raw.slice(1).trim());
    return;
  }
  if (raw.startsWith(':')) {
    _qoMode = 'line';
    const n = parseInt(raw.slice(1));
    _qoItems = isNaN(n) ? [] : [{ label: `line ${n}`, line: n }];
    renderQO();
    return;
  }
  if (raw.startsWith('@')) {
    _qoMode = 'symbol';
    runSymbolSearch(raw.slice(1));
    return;
  }
  if (raw.startsWith('#')) {
    _qoMode = 'wsymbol';
    runWorkspaceSymbols(raw.slice(1));
    return;
  }
  if (raw.startsWith('%')) {  // Find in Files takes over, with what follows the %
    fdSwitch('text', raw);
    return;
  }
  _qoMode = 'file';
  _qoQuery = raw;
  _qoOffset = 0;
  // recently opened files that match come first (exact file names before the
  // cut to 5, so a recent Items.vue is not pushed out by loose matches)
  const qName = raw.trim().toLowerCase(), byName = !/[\\/]/.test(qName);
  const isExact = k => byName && baseName(k).toLowerCase() === qName;
  _qoItems = STATE.recent.map(k => ({ k, m: fuzzyMatch(raw, k), e: isExact(k) })).filter(x => x.m)
    .sort((a, b) => (b.e - a.e) || (b.m.score - a.m.score)).slice(0, 5)
    .map(x => ({ label: x.k, path: x.k, indices: x.m.indices, meta: 'recent' }));
  _qoItems = qoExactNameFirst(_qoItems, raw);
  _qoSel = 0;
  if (_qoItems.length) renderQO(raw);
  await loadQOPage(true);
}

// Fuzzy match: a substring (word start preferred), else the letters in order
// (consecutive letters and word starts score higher). null when no match.
function fuzzyMatch(query, text) {
  const q = query.toLowerCase().replace(/\s+/g, ' ').trim();
  if (!q) return { score: 0, indices: [] };
  const t = text.toLowerCase();
  const at = t.indexOf(q);
  if (at >= 0) {
    const start = at === 0 || /[^a-z0-9]/.test(t[at - 1]);
    return { score: 1000 + (start ? 200 : 0) - at - text.length / 100, indices: [...Array(q.length).keys()].map(k => k + at) };
  }
  let ti = 0, prev = -2, score = 0;
  const indices = [];
  for (const ch of q) {
    if (ch === ' ') continue;
    const j = t.indexOf(ch, ti);
    if (j < 0) return null;
    const start = j === 0 || /[^a-z0-9]/.test(t[j - 1]) || (text[j] !== t[j] && text[j - 1] === t[j - 1]);
    score += (j === prev + 1 ? 6 : 0) + (start ? 10 : 0) - Math.min(j - ti, 20) * 0.2;
    indices.push(j);
    prev = j;
    ti = j + 1;
  }
  return { score, indices };
}
// Ctrl+Shift+P / '>' in Quick Open: the command registry, recently run first
function runCommandSearch(q) {
  const recent = STATE.recentCommands || [];
  const items = [];
  for (const c of COMMANDS) {
    if (c.desktop && !isDesktop()) continue;
    const label = `${c.cat}: ${c.title}`;
    const m = fuzzyMatch(q, label);
    if (!m) continue;
    const r = recent.indexOf(c.id);
    items.push({ label: label + (c.checked && c.checked() ? '  ✓' : ''), indices: m.indices, meta: c.keys || '', cmd: c.id,
                 disabled: !cmdEnabled(c), score: (q ? m.score : 0) + (r >= 0 ? 500 - r : 0) });
  }
  items.sort((a, b) => b.score - a.score);
  _qoItems = items;
  _qoSel = 0;
  renderQO(q);
}

// Find File: files named exactly like the query (any case) come first, in the
// order they had; the rest keep theirs. Recent files match loosely (letters in
// order), so without this they could sit between Items.vue and items.vue.
// A query with a path (/ or \) is left as it is.
function qoExactNameFirst(items, query) {
  const q = query.trim().toLowerCase();
  if (!q || /[\\/]/.test(q)) return items;
  const exact = [], rest = [];
  for (const it of items) (it.path && baseName(it.path).toLowerCase() === q ? exact : rest).push(it);
  return exact.length ? exact.concat(rest) : items;
}

let _qoAbort = null;
let _qoReqSeq = 0;
// fresh: a new query (offset 0) replaces a request still in flight; without it
// the keys typed meanwhile were dropped and the list kept an older result
async function loadQOPage(fresh) {
  if (_qoLoading && !fresh) return;
  _qoLoading = true;
  if (_qoAbort) _qoAbort.abort();
  const seq = ++_qoReqSeq;
  const queryAtStart = _qoQuery;
  _qoAbort = new AbortController();
  try {
    const url = `/api/files?q=${encodeURIComponent(queryAtStart)}&offset=${_qoOffset}&limit=${QO_PAGE}`;
    const r = await fetch(url, { signal: _qoAbort.signal });
    const data = await r.json();
    if (seq !== _qoReqSeq || queryAtStart !== _qoQuery) return; // stale
    const shown = new Set(_qoItems.map(i => i.path));
    const newItems = data.results.filter(x => !shown.has(x.path)).map(x => ({
      label: x.path,
      indices: x.indices,
      path: x.path,
    }));
    _qoItems = qoExactNameFirst(_qoItems.concat(newItems), queryAtStart);
    _qoTotal = data.total || 0;
    _qoHasMore = !!data.has_more;
    _qoOffset += newItems.length;
    if (_qoSel >= _qoItems.length) _qoSel = Math.max(0, _qoItems.length - 1);
    renderQO(_qoQuery);
  } catch (e) {
    if (e.name === 'AbortError') return;
    if (seq !== _qoReqSeq) return;
    document.getElementById('qoList').innerHTML = '<div class="qo-empty">error: ' + e.message + '</div>';
  } finally {
    if (seq === _qoReqSeq) _qoLoading = false;
  }
}

function runSymbolSearch(term) {
  const list = document.getElementById('qoList');
  if (!editor || !currentPath) {
    list.innerHTML = '<div class="qo-empty">open a file first</div>';
    _qoItems = [];
    return;
  }
  const model = editor.getModel();
  if (!model) { _qoItems = []; renderQO(); return; }
  outlineFor(model, currentPath).then(syms => {
    if (_qoMode !== 'symbol') return;
    showSymbolItems(syms, term);
  });
}
function showSymbolItems(syms, term) {
  const tl = term.toLowerCase();
  const filtered = term
    ? syms.filter(s => s.name.toLowerCase().includes(tl))
    : syms;
  _qoItems = filtered.map(s => ({
    label: s.name,
    meta: `${s.kind}  ·  line ${s.line}`,
    line: s.line,
    col: s.col,
  }));
  _qoSel = 0;
  renderQO(term);
}

// Regex outline, used only when the server has no ctags. Method-like rules
// skip control keywords (if/for/while/return/new …) so calls are not listed.
const _CTRL = '(?!(?:if|for|while|switch|catch|return|new|throw|else|do|try|await|yield|case|sizeof|typeof)\\b)';
function symbolPatterns(lang) {
  switch (lang) {
    case 'java': case 'kotlin': case 'groovy': case 'scala': case 'csharp':
      return [
        { re: /^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:public|private|protected|internal|static|final|abstract|sealed|open|data|inner|partial|enum|annotation)\s+)*(?:class|interface|enum|object|record|trait|struct|@interface)\s+(\w+)/, kind: 'class' },
        { re: /^\s*(?:(?:public|private|protected|internal|override|suspend|inline|open)\s+)*fun\s+(?:<[^>]*>\s*)?(?:[\w.]+\.)?(\w+)\s*[(<]/, kind: 'function' },
        { re: new RegExp('^\\s*(?:@\\w+(?:\\([^)]*\\))?\\s+)*(?:(?:public|private|protected|internal|static|final|abstract|synchronized|native|default|override|virtual|async|partial)\\s+)*(?:<[^>]+>\\s+)?' + _CTRL + '\\w[\\w<>?\\[\\],.\\s]*\\s+' + _CTRL + '(\\w+)\\s*\\([^;]*$'), kind: 'method' },
        { re: /^\s*(?:(?:public|private|protected|internal|static|final|readonly|const|volatile)\s+)+[\w<>?\[\],.\s]+\s+(\w+)\s*(?:=|;|\{\s*get)/, kind: 'field' },
      ];
    case 'javascript': case 'typescript':
      return [
        { re: /^\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:class|interface|type|enum|namespace)\s+(\w+)/, kind: 'class' },
        { re: /^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)\s*[(<]/, kind: 'function' },
        { re: /^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*(?::[^=]+)?=>|\w+\s*=>)/, kind: 'function' },
        { re: new RegExp('^\\s*(?:(?:public|private|protected|static|async|readonly|get|set|override|abstract)\\s+)*' + _CTRL + '\\*?(\\w+)\\s*(?:<[^>]*>)?\\s*\\([^)]*\\)\\s*(?::\\s*[^={;]+)?\\s*\\{'), kind: 'method' },
        { re: /^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)/, kind: 'variable' },
      ];
    case 'python':
      return [
        { re: /^\s*class\s+(\w+)/, kind: 'class' },
        { re: /^\s*(?:async\s+)?def\s+(\w+)\s*\(/, kind: 'function' },
        { re: /^([A-Za-z_]\w*)\s*(?::[^=]+)?=(?!=)/, kind: 'variable' },
      ];
    case 'go':
      return [
        { re: /^\s*func\s+(?:\([^)]*\)\s*)?(\w+)\s*[(\[]/, kind: 'function' },
        { re: /^\s*type\s+(\w+)/, kind: 'type' },
        { re: /^(?:var|const)\s+(\w+)/, kind: 'variable' },
      ];
    case 'rust':
      return [
        { re: /^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?(?:const\s+)?fn\s+(\w+)/, kind: 'function' },
        { re: /^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|type|union|mod)\s+(\w+)/, kind: 'type' },
        { re: /^\s*impl(?:<[^>]*>)?\s+(?:[\w:<>]+\s+for\s+)?(\w+)/, kind: 'class' },
      ];
    case 'c': case 'cpp': case 'objective-c':
      return [
        { re: /^\s*(?:typedef\s+)?(?:template\s*<[^>]*>\s*)?(?:struct|class|union|enum(?:\s+class)?)\s+(\w+)\s*(?:[:{]|$)/, kind: 'struct' },
        { re: /^\s*#\s*define\s+(\w+)/, kind: 'macro' },
        { re: new RegExp('^' + _CTRL + '[\\w\\*&:<>,~]+(?:\\s+[\\w\\*&:<>,~]+)*\\s+[\\*&]*(?:\\w+::)*(~?\\w+)\\s*\\([^;]*$'), kind: 'function' },
      ];
    case 'php':
      return [
        { re: /^\s*(?:abstract\s+|final\s+)*(?:class|interface|trait|enum)\s+(\w+)/, kind: 'class' },
        { re: /\bfunction\s+&?(\w+)\s*\(/, kind: 'function' },
      ];
    case 'ruby':
      return [
        { re: /^\s*(?:class|module)\s+([\w:]+)/, kind: 'class' },
        { re: /^\s*def\s+(?:self\.)?(\w+[?!=]?)/, kind: 'method' },
      ];
    case 'sql': case 'mysql': case 'pgsql':
      return [
        { re: /\bcreate\s+(?:or\s+replace\s+)?(?:temp(?:orary)?\s+)?(?:table|view|function|procedure|trigger|index|sequence|type)\s+(?:if\s+not\s+exists\s+)?(?:[\w"`\[\]]+\.)?["`\[]?(\w+)/i, kind: 'table' },
      ];
    case 'swift':
      return [
        { re: /^\s*(?:(?:public|private|internal|open|final|fileprivate)\s+)*(?:class|struct|enum|protocol|extension|actor)\s+(\w+)/, kind: 'class' },
        { re: /^\s*(?:(?:public|private|internal|open|static|override|mutating)\s+)*func\s+(\w+)/, kind: 'function' },
      ];
    case 'css': case 'scss': case 'less':
      return [{ re: /^\s*([.#][\w-]+|@[\w-]+|[a-z][\w-]*)\s*\{/, kind: 'rule' }];
    case 'markdown':
      return [{ re: /^#{1,6}\s+(.+?)\s*#*$/, kind: 'heading' }];
    case 'shell': case 'powershell': case 'bat':
      return [
        { re: /^\s*(?:function\s+)?([\w.-]+)\s*\(\)\s*\{?/, kind: 'function' },
        { re: /^\s*function\s+([\w-]+)/i, kind: 'function' },
        { re: /^:(\w+)/, kind: 'function' },
      ];
    default:
      return [
        { re: /^\s*(?:export\s+)?(?:function|class|interface|enum|struct|trait|impl|def|fn|func|fun|sub|procedure)\s+(\w+)/, kind: 'symbol' },
      ];
  }
}

function renderQO(term) {
  const list = document.getElementById('qoList');
  if (!_qoItems.length) {
    list.innerHTML = '<div class="qo-empty">no results</div>';
    return;
  }
  list.innerHTML = '';
  _qoItems.forEach((it, idx) => {
    const div = document.createElement('div');
    div.className = 'qo-item' + (idx === _qoSel ? ' sel' : '') + (it.disabled ? ' disabled' : '');
    let labelHtml;
    if (it.path && (_qoMode === 'file' || _qoMode === 'pick') && it.label === it.path) {
      // Find File row: badge · file name · folder (dim), matched letters marked in both
      const cut = it.path.lastIndexOf('/'), ind = it.indices || [];
      const name = it.path.slice(cut + 1), dir = cut > 0 ? it.path.slice(0, cut) : '';
      labelHtml = fileBadge(name) + '<span class="qo-name">' + renderWithIndices(name, ind.filter(i => i > cut).map(i => i - cut - 1)) + '</span>' +
        (dir ? '<span class="qo-dir">' + renderWithIndices(dir, ind.filter(i => i < cut)) + '</span>' : '');
      div.title = it.path;
      div.innerHTML = labelHtml + (it.meta ? `<span class="qo-meta">${escapeHtml(it.meta)}</span>` : '');
      div.onclick = e => activateQO(idx, e.ctrlKey || e.metaKey);
      list.appendChild(div);
      return;
    }
    if (it.indices) {
      labelHtml = renderWithIndices(it.label, it.indices);
    } else if (term && _qoMode === 'symbol') {
      labelHtml = highlight(it.label, term);
    } else {
      labelHtml = escapeHtml(it.label);
    }
    div.innerHTML = `
      <span class="qo-name">${labelHtml}</span>
      ${it.meta ? `<span class="qo-meta">${escapeHtml(it.meta)}</span>` : ''}
    `;
    div.onclick = e => activateQO(idx, e.ctrlKey || e.metaKey);
    list.appendChild(div);
  });
  // footer: count + more indicator
  if (_qoMode === 'file' && _qoTotal) {
    const footer = document.createElement('div');
    footer.className = 'qo-empty';
    footer.style.padding = '6px 16px';
    footer.style.borderTop = '1px solid var(--border)';
    footer.style.fontSize = '11px';
    footer.style.textAlign = 'left';
    footer.textContent = `${_qoItems.length} / ${_qoTotal}` + (_qoHasMore ? ' — scroll for more' : '');
    list.appendChild(footer);
  }
  // scroll selected into view
  const sel = list.querySelector('.qo-item.sel');
  if (sel) sel.scrollIntoView({ block: 'nearest' });
}

function renderWithIndices(text, indices) {
  let out = '', last = 0;
  const set = new Set(indices);
  for (let i = 0; i < text.length; i++) {
    if (set.has(i)) out += '<mark>' + escapeHtml(text[i]) + '</mark>';
    else out += escapeHtml(text[i]);
  }
  return out;
}

// beside (Ctrl+Enter): a file / workspace symbol opens in the other split pane
function activateQO(idx, beside) {
  const it = _qoItems[idx];
  if (!it) return;
  closeQO();
  if (_qoMode === 'command' && it.cmd) {
    if (!it.disabled) runCommand(it.cmd);
  } else if (beside && it.path && (_qoMode === 'file' || _qoMode === 'wsymbol')) {
    const find = _qoMode === 'wsymbol' ? { term: it.label, caseS: true, word: true } : null;
    openInOtherPane(it.path, activePaneIdx, true, null, it.line, find);
  } else if (_qoMode === 'file' && it.path && _qoFileHandler) {
    const fn = _qoFileHandler;
    _qoFileHandler = null;
    fn(it.path);
  } else if (_qoMode === 'file' && it.path) {
    openFile(it.path);
  } else if (_qoMode === 'line' && it.line && editor) {
    pushNav();
    editor.revealLineInCenter(it.line);
    editor.setPosition({ lineNumber: it.line, column: 1 });
    editor.focus();
  } else if (_qoMode === 'symbol' && it.line && editor) {
    pushNav();
    editor.revealLineInCenter(it.line);
    editor.setPosition({ lineNumber: it.line, column: it.col || 1 });
    editor.focus();
  } else if (_qoMode === 'pick' && it.path) {
    const fn = _pickHandler;
    _pickHandler = null;
    if (fn) fn(it.path);
  } else if (_qoMode === 'wsymbol' && it.path) {
    openFile(it.path, it.line, { term: it.label, caseS: true, word: true });
  }
}

document.getElementById('qoInput').addEventListener('input', () => {
  if (window._qoTimer) clearTimeout(window._qoTimer);
  window._qoTimer = setTimeout(runQO, 80);
});
document.getElementById('qoList').addEventListener('scroll', () => {
  const el = document.getElementById('qoList');
  if (_qoMode !== 'file' || !_qoHasMore || _qoLoading) return;
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 60) {
    loadQOPage();
  }
});
document.getElementById('qoInput').addEventListener('keydown', e => {
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    _qoSel = Math.min(_qoItems.length - 1, _qoSel + 1);
    renderQO(_qoQuery);
    // near end → preload next page
    if (_qoMode === 'file' && _qoHasMore && _qoSel >= _qoItems.length - 5) {
      loadQOPage();
    }
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    _qoSel = Math.max(0, _qoSel - 1);
    renderQO(_qoQuery);
  } else if (e.key === 'Enter') {
    e.preventDefault();
    activateQO(_qoSel, e.ctrlKey || e.metaKey);
  } else if (e.key === 'Escape') {
    e.preventDefault();
    dismissFD();
  } else if (e.key === 'Tab' && !e.shiftKey && !e.ctrlKey && !e.altKey && _qoMode !== 'pick' && !_qoFileHandler) {
    e.preventDefault();  // Find File ⇄ Find in Files, the typed text comes along
    fdSwitch('text', e.target.value);
  }
});

// ===== Go to Definition =====
// Monaco's own action: one result jumps, several open the peek list.
function gotoDefinition() { runEditorAction('editor.action.revealDefinition'); }

