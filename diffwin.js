// ===== ReadO diff window (diffwin.html) =====
// One file + revision at a time from the list the main window sent (window.READO_DIFFWIN, put in
// by server.py): {id, state: saved UI state, desc: {repo: {root}, index, items: [{path, hash, sub,
// key, ident, title, leftRev, leftPath, rightRev, rightPath}]}}. A side with no revision is empty
// (added / deleted file). Read-only; "Open in Editor" asks the main window to open the file.
(function () {
'use strict';
const W = window.READO_DIFFWIN, D = W.desc, ST = W.state || {}, GS = ST.git || {};
const opt = { inline: !!GS.inline, ws: !!GS.ignoreWs, eol: GS.ignoreEol !== false };
// line endings as in git.js: Monaco ignores CRLF / LF by itself; off, every CR is drawn as ␍
function eolOf(t) {
  if (!t) return '';
  const crlf = (t.match(/\r\n/g) || []).length, cr = (t.match(/\r/g) || []).length - crlf, lf = (t.match(/\n/g) || []).length - crlf;
  return crlf && !cr && !lf ? 'CRLF' : lf && !crlf && !cr ? 'LF' : cr && !crlf && !lf ? 'CR' : crlf + cr + lf ? 'mixed' : '';
}
const showCR = t => t.replace(/\r\n?/g, '␍\n');
// theme mode as in the main window: light / dark / system (anything else; follows the OS live)
const darkMQ = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
const isDark = () => ST.theme === 'dark' || (ST.theme !== 'light' && !!(darkMQ && darkMQ.matches));
let dark = isDark();
document.body.classList.add(dark ? 'theme-dark' : 'theme-light');
if (darkMQ) darkMQ.addEventListener('change', () => {
  if (isDark() === dark) return;
  dark = !dark;
  document.body.classList.remove('theme-light', 'theme-dark');
  document.body.classList.add(dark ? 'theme-dark' : 'theme-light');
  if (window.monaco) monaco.editor.setTheme(dark ? 'one-dark' : 'one-light');
});
const $ = s => document.querySelector(s);
const head = $('.gdm-head'), msg = $('.gdm-msg');
let idx = D.index || 0, ed = null, own = [], gen = 0, cur = null;

function toast(t) {
  const el = $('#toast');
  el.textContent = t; el.style.display = 'block';
  clearTimeout(el._t); el._t = setTimeout(() => { el.style.display = 'none'; }, 2200);
}
function post(url, body) {
  return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    .then(r => r.json().catch(() => ({}))).catch(() => ({}));
}
async function showText(rev, path) {
  if (rev == null) return '';
  const r = await fetch('/api/git/show?' + new URLSearchParams({ repo: D.repo.root, rev, path }), { cache: 'no-store' });
  const d = await r.json().catch(() => ({ error: 'HTTP ' + r.status }));
  if (d.error) throw new Error(d.error + (d.detail ? ': ' + d.detail : ''));
  if (d.binary) throw new Error(path + ': binary file');
  if (d.too_big) throw new Error(path + ': too big to compare');
  return d.missing ? '' : d.text;
}
let _langs = null;
function langFor(path) {
  const name = String(path || '').split('/').pop().toLowerCase();
  if (!_langs) {
    _langs = { ext: {}, name: {} };
    for (const l of monaco.languages.getLanguages()) {
      (l.extensions || []).forEach(e => { if (!_langs.ext[e]) _langs.ext[e] = l.id; });
      (l.filenames || []).forEach(f => { _langs.name[f.toLowerCase()] = l.id; });
    }
    Object.assign(_langs.ext, { '.vue': 'html', '.svelte': 'html', '.gradle': 'groovy', '.properties': 'ini' });
  }
  if (_langs.name[name]) return _langs.name[name];
  const i = name.lastIndexOf('.');
  return (i > 0 && _langs.ext[name.slice(i)]) || 'plaintext';
}
function syncButtons() {
  head.querySelector('[data-a="mode"]').textContent = opt.inline ? 'Unified' : 'Side by side';
  const ws = head.querySelector('[data-a="ws"]');
  ws.textContent = opt.ws ? 'Ignore whitespace' : 'Do not ignore';
  ws.classList.toggle('on', opt.ws);
  const eol = head.querySelector('[data-a="eol"]');
  eol.textContent = opt.eol ? 'Ignore line endings' : 'Show line endings';
  eol.classList.toggle('on', opt.eol);
  if (ed) ed.updateOptions({ renderSideBySide: !opt.inline, ignoreTrimWhitespace: opt.ws });
}
async function go(i, user) {
  if (i < 0 || i >= D.items.length) return;
  idx = i;
  const g = ++gen, it = D.items[i];
  head.querySelector('[data-a="prev"]').disabled = i <= 0;
  head.querySelector('[data-a="next"]').disabled = i >= D.items.length - 1;
  head.querySelector('.gdm-pos').textContent = D.items.length > 1 ? `${i + 1} / ${D.items.length}` : '';
  head.querySelector('.gdm-path').textContent = it.path || '';
  head.querySelector('.gdm-path').title = it.path || '';
  head.querySelector('.gdm-hash').textContent = it.hash || '';
  head.querySelector('.gdm-hash').style.display = it.hash ? '' : 'none';
  head.querySelector('.gdm-sub').textContent = it.sub || '';
  head.querySelector('[data-a="edit"]').disabled = !it.key;
  document.title = it.title || it.path || 'diff';
  if (user) post('/api/git/diffwin-nav', { id: W.id, ident: it.ident, title: document.title });
  msg.textContent = 'loading…'; msg.style.display = '';
  let left, right;
  try {
    [left, right] = await Promise.all([showText(it.leftRev, it.leftPath), showText(it.rightRev, it.rightPath)]);
  } catch (e) {
    if (g !== gen) return;
    msg.textContent = e.message;
    if (ed) ed.setModel(null);
    own.forEach(m => m.dispose()); own = [];
    return;
  }
  if (g !== gen) return;
  cur = it;
  msg.style.display = 'none';
  const lang = langFor(it.path);
  const el = eolOf(left), er = eolOf(right);
  head.querySelector('.gdm-sub').textContent = (it.sub || '') + (el && er && el !== er ? ` · line endings ${el} → ${er}` : '');
  const original = monaco.editor.createModel(opt.eol ? left : showCR(left), lang),
    modified = monaco.editor.createModel(opt.eol ? right : showCR(right), lang);
  ed.setModel({ original, modified });
  own.forEach(m => m.dispose());
  own = [original, modified];
  const first = ed.onDidUpdateDiff(() => {
    first.dispose();
    const ch = ed.getLineChanges();
    if (ch && ch.length) ed.getModifiedEditor().revealLineInCenter(Math.max(1, ch[0].modifiedStartLineNumber || 1));
  });
}
function openInEditor() {
  if (!cur || !cur.key) return;
  const ch = ed && ed.getLineChanges();
  const line = !cur.hash && ch && ch.length ? Math.max(1, ch[0].modifiedStartLineNumber || 1) : null;
  post('/api/git/diffwin-edit', { id: W.id, key: cur.key, line }).then(r => { if (!r.ok) toast('the ReadO window could not open it'); });
}
head.addEventListener('click', e => {
  const a = e.target.dataset && e.target.dataset.a;
  if (a === 'prev') go(idx - 1, true);
  if (a === 'next') go(idx + 1, true);
  if ((a === 'prevChange' || a === 'nextChange') && ed) ed.goToDiff(a === 'nextChange' ? 'next' : 'previous');
  if (a === 'mode') { opt.inline = !opt.inline; syncButtons(); }
  if (a === 'ws') { opt.ws = !opt.ws; syncButtons(); }
  if (a === 'eol') { opt.eol = !opt.eol; syncButtons(); go(idx); }
  if (a === 'edit') openInEditor();
});
document.addEventListener('keydown', e => {
  const inEditor = e.target.closest && e.target.closest('.monaco-editor');
  if ((e.key === 'ArrowUp' || e.key === 'ArrowDown') && (e.altKey || !inEditor)) {
    e.preventDefault(); go(idx + (e.key === 'ArrowUp' ? -1 : 1), true);
  } else if (e.key === 'F7' && ed) {
    e.preventDefault(); ed.goToDiff(e.shiftKey ? 'previous' : 'next');
  } else if (e.key === 'Escape' && !e.defaultPrevented) {
    post('/api/git/diffwin-close', { id: W.id });
  }
}, true);
window.DiffWin = { go, get idx() { return idx; }, get ed() { return ed; }, get cur() { return cur; }, opt };

require.config({ paths: { vs: '/vendor/monaco/vs' } });
require(['vs/editor/editor.main'], () => {
  // the main window's One Light / One Dark (source.html)
  monaco.editor.defineTheme('one-light', { base: 'vs', inherit: true, rules: [
    { token: '', foreground: '383a42', background: 'fafafa' }, { token: 'comment', foreground: 'a0a1a7', fontStyle: 'italic' },
    { token: 'keyword', foreground: 'a626a4' }, { token: 'string', foreground: '50a14f' }, { token: 'number', foreground: '986801' },
    { token: 'type', foreground: 'c18401' }, { token: 'type.identifier', foreground: 'c18401' }, { token: 'tag', foreground: 'e45649' },
    { token: 'attribute.name', foreground: 'b76b01' }, { token: 'attribute.value', foreground: '50a14f' }],
    colors: { 'editor.background': '#fafafa', 'editor.foreground': '#383a42', 'editor.lineHighlightBackground': '#f0f0f1',
      'editorLineNumber.foreground': '#a0a1a7', 'editorLineNumber.activeForeground': '#383a42', 'editor.selectionBackground': '#e5e5e6' } });
  monaco.editor.defineTheme('one-dark', { base: 'vs-dark', inherit: true, rules: [
    { token: '', foreground: 'abb2bf', background: '282c34' }, { token: 'comment', foreground: '5c6370', fontStyle: 'italic' },
    { token: 'keyword', foreground: 'c678dd' }, { token: 'string', foreground: '98c379' }, { token: 'number', foreground: 'd19a66' },
    { token: 'type', foreground: 'e5c07b' }, { token: 'type.identifier', foreground: 'e5c07b' }, { token: 'tag', foreground: 'e06c75' },
    { token: 'attribute.name', foreground: 'd19a66' }, { token: 'attribute.value', foreground: '98c379' }],
    colors: { 'editor.background': '#282c34', 'editor.foreground': '#abb2bf', 'editor.lineHighlightBackground': '#2c313a',
      'editorLineNumber.foreground': '#5c6370', 'editorLineNumber.activeForeground': '#abb2bf', 'editor.selectionBackground': '#3e4451' } });
  ed = monaco.editor.createDiffEditor($('.gdm-ed'), {
    automaticLayout: true, readOnly: true, originalEditable: false, renderSideBySide: !opt.inline,
    ignoreTrimWhitespace: opt.ws, fontSize: ST.fontSize || 13, theme: dark ? 'one-dark' : 'one-light',
    fontFamily: getComputedStyle(document.body).getPropertyValue('--mono'),
  });
  syncButtons();
  go(idx);
});
})();
