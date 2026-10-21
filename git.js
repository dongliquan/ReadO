// ===== ReadO Git tool window — read-only views (gitview.py) =====
// Local Changes · Log (graph, filters, branch tree, commit details) · History ·
// Stash · Console, plus blame in the editor, tree colours and the status-bar
// branch. Nothing here changes a repository: every write action becomes an
// instruction for AgentO (copied to the clipboard, AgentO brought up).
// Graph lanes follow the usual "first parent keeps the lane" idea (see NOTICE:
// VS Code SCM graph, MIT) — written for this file, not copied.
(function () {
'use strict';

const ROW_H = 22, LANE_W = 12, MAX_LANES = 40;
const LANE_COLORS = ['#4078f2', '#50a14f', '#e45649', '#c18401', '#a626a4', '#0184bc', '#986801', '#d75f00', '#2aa198', '#8e44ad'];
const G = {
  info: null,          // /api/git/info (availability)
  repos: [],           // [{root, name, base, state}]
  repo: null,          // selected repository summary
  status: null,        // last /status of G.repo
  refs: null,          // last /refs of G.repo
  fp: '',              // fingerprint of G.repo (HEAD / index / refs)
  decor: { files: {}, dirs: {} },
  blame: new Map(),    // doc key -> {data, decos, css}
  conflicts: new Set(),// ReadO keys of conflicted files (editor markers)
};
const S_DEFAULTS = { open: false, tab: 'changes', h: 300, repo: '', bw: 220, dw: 380, cw: 420, inline: false, ignoreWs: false, lineBlame: false,
  ignoreEol: true, showEol: false };
const S = () => {  // STATE.git with defaults filled in place (always the same object)
  if (!STATE.git || typeof STATE.git !== 'object') STATE.git = {};
  for (const [k, v] of Object.entries(S_DEFAULTS)) if (!(k in STATE.git)) STATE.git[k] = v;
  return STATE.git;
};
// Log / History columns right of the message: resizable (header edges), hideable (header right-click), saved in state.json
const LOG_COLS = [{ k: 'au', label: 'Author', w: 100, min: 50 }, { k: 'dt', label: 'Date', w: 125, min: 60 }, { k: 'hs', label: 'Hash', w: 70, min: 50 }];
const LOG_COL_MAX = 480;
function logCols() {  // STATE.git.logCols = {au: {w, on}, …}, repaired in place
  const s = S();
  if (!s.logCols || typeof s.logCols !== 'object') s.logCols = {};
  for (const c of LOG_COLS) {
    // same object kept (a drag holds on to it)
    const v = s.logCols[c.k] && typeof s.logCols[c.k] === 'object' ? s.logCols[c.k] : (s.logCols[c.k] = {});
    v.w = Number.isFinite(v.w) ? Math.max(c.min, Math.min(LOG_COL_MAX, Math.round(v.w))) : c.w;
    v.on = v.on !== false;
  }
  return s.logCols;
}
// per view (Log, History): a narrow list scales the columns down so the message keeps a third of the row, never a sideways scroll
const LOG_MSG_MIN = 120;
function layoutLogCols(wrap) {
  const cols = logCols(), list = wrap.querySelector('.gl-list'), avail = list ? list.clientWidth : 0;
  const vis = LOG_COLS.filter(c => cols[c.k].on), total = vis.reduce((s, c) => s + cols[c.k].w, 0);
  const room = Math.max(0, avail - Math.max(LOG_MSG_MIN, avail * 0.35));
  const scale = avail && total > room ? room / total : 1;
  for (const c of LOG_COLS) {
    wrap.style.setProperty('--gl-' + c.k, Math.max(24, Math.floor(cols[c.k].w * scale)) + 'px');
    wrap.classList.toggle('gl-no-' + c.k, !cols[c.k].on);
  }
}
function applyLogCols() { document.querySelectorAll('.gl-wrap').forEach(layoutLogCols); }
function logColMenu(x, y) {  // the commit message always shows; Author / Date / Hash toggle
  const cols = logCols();
  showMenu(x, y, [{ label: 'Subject', checked: true, disabled: true, run: () => {} }]
    .concat(LOG_COLS.map(c => ({ label: c.label, checked: cols[c.k].on, run: () => { cols[c.k].on = !cols[c.k].on; applyLogCols(); saveState(); } })),
      ['sep', { label: 'Reset Column Widths', run: () => { LOG_COLS.forEach(c => { cols[c.k].w = c.w; }); applyLogCols(); saveState(); } }]));
}

// ---------- small helpers ----------
const esc = s => escapeHtml(String(s == null ? '' : s));
const short = h => String(h || '').slice(0, 8);
function qs(params) {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v == null || v === '' || v === false) continue;
    (Array.isArray(v) ? v : [v]).forEach(x => u.append(k, x === true ? '1' : String(x)));
  }
  return u.toString();
}
const _aborts = new Map();
async function api(name, params, channel) {
  let ctl = null;
  if (channel) {
    if (_aborts.get(channel)) _aborts.get(channel).abort();
    ctl = new AbortController();
    _aborts.set(channel, ctl);
  }
  try {
    const r = await fetch('/api/git/' + name + '?' + qs(params), { cache: 'no-store', signal: ctl && ctl.signal });
    const d = await r.json().catch(() => ({ error: 'HTTP ' + r.status }));
    if (!r.ok && !d.error) d.error = 'HTTP ' + r.status;
    return d;
  } catch (e) {
    return { error: e.name === 'AbortError' ? 'cancelled' : e.message, aborted: e.name === 'AbortError' };
  }
}
const ERR_TEXT = {
  no_git: 'git is not installed (or not on PATH). Install Git for Windows 2.24 or newer to use the Git views.',
  old_git: 'the installed git is too old — the Git views need git 2.24 or newer.',
  not_repo: 'not a git repository (or outside the open folder)',
  unsafe_repo: 'git refuses this repository (safe.directory / owner check). ReadO does not change git settings.',
  timeout: 'git took too long and was stopped',
  busy: 'git is busy — try again',
};
const errText = d => ERR_TEXT[d.error] || (d.error + (d.detail ? ': ' + d.detail : ''));
function fmtDate(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000), now = new Date();
  const diff = (now - d) / 1000;
  const hm = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  if (diff >= 0 && diff < 60) return 'just now';
  if (diff >= 0 && diff < 3600) return Math.floor(diff / 60) + ' minutes ago';
  if (d.toDateString() === now.toDateString()) return 'Today ' + hm;
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return 'Yesterday ' + hm;
  return d.toLocaleDateString() + ' ' + hm;
}
const fullDate = ts => ts ? new Date(ts * 1000).toLocaleString() : '';
const norm = p => String(p || '').replace(/\\/g, '/').replace(/\/+$/, '');
// ReadO file key for a repository path (relative inside the open folder), or null
function keyFor(repo, rel) {
  if (!repo) return null;
  const full = norm(repo.root) + '/' + rel;
  const base = norm(repo.base || _settings.base_dir || '');
  if (base && full.toLowerCase().startsWith(base.toLowerCase() + '/')) return full.slice(base.length + 1);
  return null;
}
function dirOf(p) { const i = p.lastIndexOf('/'); return i < 0 ? '' : p.slice(0, i); }
function el(tag, cls, html) { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
async function copy(text, what) { await copyText(text, what); }

// ---------- read-only text: select, copy, find ----------
// The desktop app's WebView (pywebview, text_select off) makes the whole page unselectable and has no
// built-in context menu or Ctrl+F. Commit messages, the Console and diff headers opt back in
// (.rd-text: user-select: text) and get Copy / Select All / Find here. readable(box, extra) once per box;
// extra(e) -> more menu items for that right-click.
function selectionIn(box) {
  const s = getSelection();
  return s && !s.isCollapsed && box.contains(s.anchorNode) && box.contains(s.focusNode) ? String(s) : '';
}
function selectAllIn(box) {
  const r = document.createRange();
  r.selectNodeContents(box);
  const s = getSelection(); s.removeAllRanges(); s.addRange(r);
}
function readable(box, extra, opts) {
  if (box._readable) return;
  box._readable = true;
  box.classList.add('rd-text');
  if (box.tabIndex < 0 && !box.hasAttribute('tabindex')) box.tabIndex = -1;  // clicks focus it: Ctrl+C / A / F land here
  box.addEventListener('contextmenu', e => {
    if (e.target.closest('a, button, input')) return;
    e.preventDefault();
    e.stopPropagation();
    const sel = selectionIn(box);
    showMenu(e.clientX, e.clientY, [
      { label: 'Copy', hint: 'Ctrl+C', disabled: !sel, run: () => copyQuiet(sel).then(() => showToast('copied')) },
      ...(extra ? extra(e) : []),
      'sep',
      { label: 'Select All', hint: 'Ctrl+A', run: () => { box.focus(); selectAllIn(box); } },
      ...(opts && opts.find === false ? [] : [{ label: 'Find…', hint: 'Ctrl+F', run: () => TextFind.open(box) }]),
    ]);
  });
  box.addEventListener('keydown', e => {
    if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey || e.target !== box) return;
    const k = e.key.toLowerCase();
    if (k === 'c') { const sel = selectionIn(box); if (sel) { e.preventDefault(); e.stopPropagation(); copyQuiet(sel); } }
    else if (k === 'a') { e.preventDefault(); e.stopPropagation(); selectAllIn(box); }
    else if (k === 'f' && !(opts && opts.find === false)) { e.preventDefault(); e.stopPropagation(); TextFind.open(box); }
  });
}
// Ctrl+F in a read-only text box: a small find bar over its top right corner; matches are painted with
// the CSS Custom Highlight API (no DOM change, the selection stays); Enter / F3 next, Shift+Enter previous,
// Esc closes. The box may be re-rendered (another commit selected): the search runs again.
const TextFind = {
  box: null, bar: null, ranges: [], cur: -1, mo: null,
  open(box) {
    if (this.box !== box) this.close();
    this.box = box;
    if (!this.bar) {
      const bar = this.bar = el('div', 'rd-find');
      bar.innerHTML = '<input placeholder="find in text" spellcheck="false"><span class="n"></span>' +
        '<button data-a="prev" title="previous (Shift+Enter)">↑</button><button data-a="next" title="next (Enter / F3)">↓</button><button data-a="close" title="close (Esc)">✕</button>';
      const inp = bar.querySelector('input');
      inp.addEventListener('input', () => this.run(true));
      inp.addEventListener('keydown', e => {
        e.stopPropagation();
        if (e.key === 'Escape') { e.preventDefault(); this.close(true); }
        else if (e.key === 'Enter' || e.key === 'F3') { e.preventDefault(); this.step(e.shiftKey ? -1 : 1); }
      });
      bar.addEventListener('mousedown', e => { if (e.target.tagName === 'BUTTON') e.preventDefault(); });
      bar.addEventListener('click', e => {
        const a = e.target.dataset && e.target.dataset.a;
        if (a === 'close') this.close(true); else if (a) this.step(a === 'prev' ? -1 : 1);
      });
    }
    const host = box.parentElement;
    if (getComputedStyle(host).position === 'static') host.style.position = 'relative';
    host.appendChild(this.bar);
    this.bar.style.top = (box.offsetTop + 4) + 'px';
    this.bar.style.right = (host.clientWidth - box.offsetLeft - box.clientWidth + 6) + 'px';
    if (this.mo) this.mo.disconnect();
    this.mo = new MutationObserver(() => this.run(true));
    this.mo.observe(box, { childList: true, subtree: true, characterData: true });
    const inp = this.bar.querySelector('input'), sel = selectionIn(box).trim();
    if (sel && !sel.includes('\n')) inp.value = sel;
    inp.focus(); inp.select();
    this.run(true);
  },
  run(first) {
    const q = this.bar.querySelector('input').value.toLowerCase();
    this.ranges = [];
    if (q) {
      const walk = document.createTreeWalker(this.box, NodeFilter.SHOW_TEXT);
      for (let n; (n = walk.nextNode());) {
        const t = n.data.toLowerCase();
        for (let i = t.indexOf(q); i >= 0; i = t.indexOf(q, i + q.length)) {
          const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + q.length); this.ranges.push(r);
        }
      }
    }
    this.cur = this.ranges.length ? 0 : -1;
    this.paint(first);
  },
  step(d) {
    if (!this.ranges.length) return;
    this.cur = (this.cur + d + this.ranges.length) % this.ranges.length;
    this.paint(true);
  },
  paint(reveal) {
    const n = this.bar.querySelector('.n'), q = this.bar.querySelector('input').value;
    n.textContent = !q ? '' : this.ranges.length ? `${this.cur + 1}/${this.ranges.length}` : 'no matches';
    this.bar.classList.toggle('none', !!q && !this.ranges.length);
    if (window.CSS && CSS.highlights && window.Highlight) {
      CSS.highlights.set('rd-find', new Highlight(...this.ranges.filter((r, i) => i !== this.cur)));
      CSS.highlights.set('rd-find-cur', new Highlight(...(this.cur >= 0 ? [this.ranges[this.cur]] : [])));
    }
    const r = this.cur >= 0 && this.ranges[this.cur];
    if (reveal && r) {
      const rb = r.getBoundingClientRect(), bb = this.box.getBoundingClientRect();
      if (rb.top < bb.top + 28 || rb.bottom > bb.bottom - 4) this.box.scrollTop += rb.top - bb.top - bb.height / 3;
    }
  },
  close(refocus) {
    if (this.mo) { this.mo.disconnect(); this.mo = null; }
    if (window.CSS && CSS.highlights) { CSS.highlights.delete('rd-find'); CSS.highlights.delete('rd-find-cur'); }
    if (this.bar) this.bar.remove();
    const box = this.box;
    this.box = null; this.ranges = []; this.cur = -1;
    if (refocus && box) box.focus();
  },
};

// ---------- AgentO hand-off (instructions; ReadO never writes) ----------
function repoLine(repo) {
  const b = G.status && G.status.branch && G.repo && repo && G.repo.root === repo.root ? G.status.branch.head : (repo && repo.branch) || '';
  return `저장소: ${(repo ? repo.root : '').replace(/\//g, '\\')}${b ? ` (현재 브랜치: ${b})` : ''}`;
}
const AGENT = {
  commit: c => `다음 파일만 커밋해 줘:\n${c.files.map(f => '- ' + f).join('\n')}\n\n커밋 메시지(초안): ${c.message || '<변경 내용을 보고 작성>'}\n${c.amend ? '직전 커밋에 amend 해 줘.\n' : ''}커밋 전에 diff를 확인하고, 목록에 없는 변경은 건드리지 마.`,
  rollback: c => `다음 파일의 로컬 변경을 되돌려 줘(되돌리기 전에 diff를 보여 주고 확인을 받아 줘):\n${c.files.map(f => '- ' + f).join('\n')}`,
  resolve: c => `현재 ${c.state || '머지'} 중이고 충돌 파일이 있어. 충돌을 해결해 줘(해결 방향이 애매하면 먼저 물어봐 줘):\n${c.files.map(f => '- ' + f).join('\n')}`,
  push: c => `현재 브랜치${c.branch ? ' ' + c.branch : ''}를 ${c.upstream || '원격'}으로 push 해 줘. 먼저 ahead/behind를 확인하고, force push는 하지 마.`,
  pull: c => `현재 브랜치${c.branch ? ' ' + c.branch : ''}를 원격에서 pull(업데이트) 해 줘. 커밋되지 않은 변경이 있으면 먼저 알려 주고, 충돌이 나면 멈추고 알려 줘.`,
  fetch: () => `원격 저장소를 fetch 해 줘(git fetch --all --prune). 다른 변경은 하지 마.`,
  checkout: c => `브랜치 ${c.ref}로 체크아웃해 줘. 커밋되지 않은 변경이 있으면 먼저 알려 줘.`,
  checkoutRev: c => `커밋 ${short(c.h)} (${c.s || ''})을 detached HEAD로 체크아웃해 줘. 커밋되지 않은 변경이 있으면 먼저 알려 줘.`,
  newBranch: c => `${c.from ? `${c.from}에서` : '현재 위치에서'} 새 브랜치 '<새 브랜치 이름>'을 만들고 체크아웃해 줘.`,
  merge: c => `브랜치 ${c.ref}를 현재 브랜치${c.branch ? ' ' + c.branch : ''}에 merge 해 줘. 충돌이 나면 멈추고 알려 줘.`,
  rebase: c => `현재 브랜치${c.branch ? ' ' + c.branch : ''}를 ${c.ref} 위로 rebase 해 줘. 충돌이 나면 멈추고 알려 줘.`,
  deleteBranch: c => `로컬 브랜치 ${c.ref}를 삭제해 줘(머지되지 않은 커밋이 있으면 먼저 알려 줘).`,
  cherryPick: c => `커밋 ${short(c.h)} (${c.s || ''})을 현재 브랜치에 cherry-pick 해 줘. 충돌이 나면 멈추고 알려 줘.`,
  revert: c => `커밋 ${short(c.h)} (${c.s || ''})을 revert 해 줘(revert 커밋 생성). 충돌이 나면 멈추고 알려 줘.`,
  reset: c => `현재 브랜치를 커밋 ${short(c.h)} (${c.s || ''})으로 reset 해 줘(--mixed). 실행 전에 잃게 되는 커밋이 있는지 확인받아 줘.`,
  stashPush: () => `현재 로컬 변경을 stash 해 줘(메시지: <설명>). untracked 파일 포함 여부는 먼저 물어봐 줘.`,
  stashApply: c => `stash ${c.name} (${c.s || ''})을 apply 해 줘(stash는 남겨 둬). 충돌이 나면 멈추고 알려 줘.`,
  stashPop: c => `stash ${c.name} (${c.s || ''})을 pop 해 줘. 충돌이 나면 멈추고 알려 줘.`,
  stashDrop: c => `stash ${c.name} (${c.s || ''})을 삭제(drop)해 줘.`,
  ask: () => `이 저장소에서 다음 작업을 해 줘:\n<요청 내용>`,
};
const AGENT_TITLE = {
  commit: 'Commit', rollback: 'Rollback', resolve: 'Resolve Conflicts', push: 'Push', pull: 'Pull / Update', fetch: 'Fetch',
  checkout: 'Checkout', checkoutRev: 'Checkout Revision', newBranch: 'New Branch', merge: 'Merge', rebase: 'Rebase',
  deleteBranch: 'Delete Branch', cherryPick: 'Cherry-Pick', revert: 'Revert Commit', reset: 'Reset Current Branch',
  stashPush: 'Stash Changes', stashApply: 'Apply Stash', stashPop: 'Pop Stash', stashDrop: 'Drop Stash', ask: 'Ask AgentO',
};
function agentDialog(action, ctx, repo) {
  repo = repo || G.repo;
  if (!repo) return showToast('no git repository selected', true);
  const text = `[ReadO → AgentO] ${repoLine(repo)}\n\n` + AGENT[action](ctx || {});
  const bg = el('div', 'gx-bg');
  bg.innerHTML = `<div class="gx-dlg"><h3>${esc(AGENT_TITLE[action] || action)} — in AgentO</h3>
    <div class="sub">ReadO only shows git; this instruction goes to an AgentO session, which runs git. Edit it if needed.</div>
    <textarea spellcheck="false"></textarea>
    <div class="row"><span class="note">"Copy &amp; open AgentO" copies the text and brings AgentO up — paste it into the session that works in this repository.</span>
      <button data-a="term" title="open a terminal in this repository">terminal</button>
      <button data-a="copy">copy</button><button data-a="cancel">cancel</button>
      <button data-a="go" class="primary">copy &amp; open AgentO</button></div></div>`;
  const ta = bg.querySelector('textarea');
  ta.value = text;
  const close = () => { bg.remove(); document.removeEventListener('keydown', onKey, true); };
  const onKey = e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); } };
  document.addEventListener('keydown', onKey, true);
  bg.addEventListener('mousedown', e => { if (e.target === bg) close(); });
  bg.querySelector('.row').addEventListener('click', async e => {
    const a = e.target.dataset && e.target.dataset.a;
    if (!a) return;
    if (a === 'cancel') return close();
    if (a === 'term') return openTerminal(repo);
    await copyQuiet(ta.value);
    close();
    if (a === 'copy') return showToast('instruction copied — paste it into AgentO');
    const r = await postJson('/api/git/agento', { path: S().agentoPath || '' });
    if (r.ok && r.data.launched) showToast('instruction copied — AgentO is up, paste it into the session');
    else showToast('instruction copied — AgentO.exe was not found; open AgentO and paste it', true);
  });
  document.body.appendChild(bg);
  ta.focus();
  const i = ta.value.indexOf('<');
  if (i >= 0) ta.setSelectionRange(i, ta.value.indexOf('>', i) + 1);
}
async function copyQuiet(text) {
  try { await navigator.clipboard.writeText(text); return; } catch (e) {}
  const ta = Object.assign(document.createElement('textarea'), { value: text });
  document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove();
}
async function openTerminal(repo) {
  repo = repo || G.repo;
  if (!repo) return showToast('no git repository selected', true);
  const r = await postJson('/api/git/terminal', { repo: repo.root });
  showToast(r.ok ? 'terminal opened in ' + repo.name : 'could not open a terminal: ' + (r.data.error || r.status), !r.ok);
}
async function openAgentO() {
  const r = await postJson('/api/git/agento', { path: S().agentoPath || '' });
  showToast(r.ok && r.data.launched ? 'AgentO' : 'AgentO.exe was not found (running or installed under %LOCALAPPDATA%\\Programs\\AgentO)', !(r.ok && r.data.launched));
}

// ---------- pick-list popup (filters, branch popup) ----------
// items: [{value, label, hint, header}]; multi: checkboxes; onPick(values|value)
function pickList(anchor, items, opts) {
  closePick();
  const box = el('div', 'gpick');
  box.id = 'gitPick';
  const w = opts.width || 300;
  if (opts.width) box.style.width = w + 'px';
  const sel = new Set(opts.selected || []);
  box.innerHTML = `<input class="q" placeholder="${esc(opts.placeholder || 'filter…')}" spellcheck="false"><div class="lst"></div>` +
    (opts.multi ? '<div class="ft"><button data-a="clear">all</button><button data-a="ok">apply</button></div>' : '');
  const lst = box.querySelector('.lst'), q = box.querySelector('.q');
  let act = -1, shown = [];
  const render = () => {
    const t = q.value.trim().toLowerCase();
    shown = items.filter(it => it.header || !t || String(it.label).toLowerCase().includes(t));
    if (t) shown = shown.filter((it, i) => !it.header || (shown[i + 1] && !shown[i + 1].header));
    lst.innerHTML = shown.slice(0, 500).map((it, i) => it.header ? `<div class="hd">${esc(it.label)}</div>` :
      `<div class="it${i === act ? ' act' : ''}${it.cls ? ' ' + it.cls : ''}" data-i="${i}">${opts.multi ? `<input type="checkbox"${sel.has(it.value) ? ' checked' : ''}>` : ''}<span class="nm">${esc(it.label)}</span>${it.hint ? `<span class="hint">${esc(it.hint)}</span>` : ''}</div>`).join('') ||
      `<div class="gw-empty">${esc(opts.empty || 'nothing matches')}</div>`;
  };
  const choose = i => {
    const it = shown[i];
    if (!it || it.header) return;
    if (opts.multi) { sel.has(it.value) ? sel.delete(it.value) : sel.add(it.value); render(); return; }
    closePick();
    opts.onPick(it.value, it);
  };
  lst.addEventListener('click', e => { const r = e.target.closest('.it'); if (r) choose(+r.dataset.i); });
  q.addEventListener('input', () => { act = -1; render(); });
  q.addEventListener('keydown', e => {
    const n = shown.length;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      do { act = (act + (e.key === 'ArrowDown' ? 1 : -1) + n) % n; } while (shown[act] && shown[act].header && n > 1);
      render();
      const a = lst.querySelector('.act'); if (a) a.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (act >= 0) choose(act);
      else if (opts.multi) { closePick(); opts.onPick([...sel]); }
      else if (opts.onText && q.value.trim()) { closePick(); opts.onText(q.value.trim()); }
      else { const first = shown.findIndex(x => !x.header); if (first >= 0) choose(first); }
    } else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closePick(); }
  });
  const ft = box.querySelector('.ft');
  if (ft) ft.addEventListener('click', e => {
    if (e.target.dataset.a === 'clear') { closePick(); opts.onPick([]); }
    if (e.target.dataset.a === 'ok') { closePick(); opts.onPick([...sel]); }
  });
  render();
  document.body.appendChild(box);
  const r = anchor.getBoundingClientRect();
  const h = box.getBoundingClientRect().height;
  box.style.left = Math.max(4, Math.min(r.left, innerWidth - w - 4)) + 'px';
  box.style.top = (r.bottom + h + 4 < innerHeight ? r.bottom + 2 : Math.max(4, r.top - h - 2)) + 'px';
  q.focus();
}
function closePick() { const b = document.getElementById('gitPick'); if (b) b.remove(); }
window.addEventListener('mousedown', e => { if (!(e.target.closest && e.target.closest('#gitPick'))) closePick(); }, true);

// ---------- diff views (Monaco diff editor in ReadO's diff overlay) ----------
async function showText(repo, rev, path) {
  const d = await api('show', { repo: repo.root, rev, path });
  if (d.error) throw new Error(errText(d));
  if (d.binary) throw new Error(path + ': binary file');
  if (d.too_big) throw new Error(path + ': too big to compare');
  return d.missing ? '' : d.text;
}
// ---------- diff windows (every diff opened from the Git window, blame …) ----------
// A spec says what to compare: {path, hash, sub, left, right | doc (live editor model), key (ReadO file key), line}
async function specLocal(repo, f) {
  const leftPath = f.orig || f.path;
  const left = f.kind === 'added' || f.kind === 'untracked' ? '' : await showText(repo, 'HEAD', leftPath);
  const key = keyFor(repo, f.path);
  const doc = key && docs.get(key);
  const base = { path: f.path, hash: '', key: f.kind === 'deleted' ? null : key, left };
  if (doc && f.kind !== 'deleted' && !doc.model.isDisposed())
    return Object.assign(base, { doc, sub: 'HEAD ↔ editor' + (canEdit(doc) ? ' (edits go to the file)' : '') });
  const right = f.kind === 'deleted' ? '' : await showText(repo, 'WORKTREE', f.path);
  return Object.assign(base, { right, sub: (f.orig ? `renamed from ${f.orig} · ` : '') + 'HEAD ↔ Current version' });
}
async function specCommit(repo, c, f) {
  const parent = c.parent || (c.p && c.p[0]);
  const left = f.status === 'A' || !parent ? '' : await showText(repo, parent, f.orig || f.path);
  const right = f.status === 'D' ? '' : await showText(repo, c.h, f.path);
  return { path: f.path, hash: short(c.h), left, right, key: f.status === 'D' ? null : keyFor(repo, f.path),
    sub: `${parent ? short(parent) : '(none)'}${f.orig ? ' ' + f.orig : ''} → ${short(c.h)}` };
}
// A diff window is an OS window of its own (reado.py / pywebview, diffwin.html) that gets the files
// resolved: revision + path per side. Without one (browser mode) it is an in-page panel, below.
function descLocal(repo, f) {
  return { path: f.path, hash: '', key: f.kind === 'deleted' ? null : keyFor(repo, f.path),
    sub: (f.orig ? `renamed from ${f.orig} · ` : '') + 'HEAD ↔ Current version',
    leftRev: f.kind === 'added' || f.kind === 'untracked' ? null : 'HEAD', leftPath: f.orig || f.path,
    rightRev: f.kind === 'deleted' ? null : 'WORKTREE', rightPath: f.path,
    ident: 'L:' + repo.root + '|' + f.path, title: `${baseName(f.path)} · local changes` };
}
function descCommit(repo, c, f) {
  const parent = c.parent || (c.p && c.p[0]);
  return { path: f.path, hash: short(c.h), key: f.status === 'D' ? null : keyFor(repo, f.path),
    sub: `${parent ? short(parent) : '(none)'}${f.orig ? ' ' + f.orig : ''} → ${short(c.h)}`,
    leftRev: f.status === 'A' || !parent ? null : parent, leftPath: f.orig || f.path,
    rightRev: f.status === 'D' ? null : c.h, rightPath: f.path,
    ident: 'C:' + c.h + '|' + f.path, title: `${baseName(f.path)} · ${short(c.h)}` };
}
// items: what ↑ / ↓ walk through; load(item) -> spec (in-page); opts.desc(item) -> descriptor (OS window), opts.repo
function openDiffWin(items, index, load, opts) {
  opts = opts || {};
  if (!opts.desc || !opts.repo || G.nativeWin === false) return openPanelWin(items, index, load, opts);
  const lo = Math.max(0, index - 1500), list = items.slice(lo, lo + 3000);
  postJson('/api/git/diffwin', { repo: opts.repo.root, items: list.map(opts.desc), index: index - lo }).then(r => {
    if (r.ok && r.data.native) return;  // opened, or the open one came to the front
    if (r.ok) G.nativeWin = false;      // no OS windows here (browser): in-page panels from now on
    openPanelWin(items, index, load, opts);
  });
  return null;
}
// In-page fallback: floating, non-modal panels inside the page. The title bar moves
// one, the edges / corners resize it, several can be open (one per file + revision; opening the
// same one again brings it to the front). The page under them stays usable.
const DW = { wins: [], seq: 0, max: 8, z0: 40 };  // z: above the panes / Git window, below ReadO's menus (60)
const DW_MIN_W = 380, DW_MIN_H = 220, DW_STEP = 26;
function dwClamp(g) {  // whole window inside the app window
  const vw = innerWidth, vh = innerHeight;
  const w = Math.round(Math.min(Math.max(g.w, DW_MIN_W), vw)), h = Math.round(Math.min(Math.max(g.h, DW_MIN_H), vh));
  return { x: Math.round(Math.min(Math.max(g.x, 0), vw - w)), y: Math.round(Math.min(Math.max(g.y, 0), vh - h)), w, h };
}
function dwPlace(win, g) {
  win.g = dwClamp(g);
  Object.assign(win.bg.style, { left: win.g.x + 'px', top: win.g.y + 'px', width: win.g.w + 'px', height: win.g.h + 'px' });
}
function dwStart() {  // where a new window goes: cascaded from the front one, else the last saved place
  const f = dmFront();
  if (f) return { x: f.g.x + DW_STEP, y: f.g.y + DW_STEP, w: f.g.w, h: f.g.h };
  const s = S().dwin;
  if (s && s.w > 0 && s.h > 0) return s;
  const w = innerWidth * 0.8, h = innerHeight * 0.8;
  return { x: (innerWidth - w) / 2, y: (innerHeight - h) / 2, w, h };
}
const dmFront = () => DW.wins[DW.wins.length - 1] || null;
function dwFront(win) {
  const i = DW.wins.indexOf(win);
  if (i < 0) return;
  if (i !== DW.wins.length - 1) { DW.wins.splice(i, 1); DW.wins.push(win); }
  DW.wins.forEach((w, j) => { w.bg.style.zIndex = DW.z0 + j; w.bg.classList.toggle('front', w === win); });
}
function dwMax(win) {
  win.max = !win.max;
  win.bg.classList.toggle('max', win.max);
  win.bg.querySelector('[data-a="max"]').textContent = win.max ? '❐' : '□';
}
function dwDrag(handle, win, mode) {
  handle.addEventListener('pointerdown', e => {
    if (e.button !== 0 || win.max || (mode === 'move' && e.target.closest('button'))) return;
    e.preventDefault();
    dwFront(win);
    const x0 = e.clientX, y0 = e.clientY, g0 = Object.assign({}, win.g);
    handle.setPointerCapture(e.pointerId);
    document.body.classList.add('gdw-dragging');
    const move = ev => {
      const dx = ev.clientX - x0, dy = ev.clientY - y0, g = Object.assign({}, g0);
      if (mode === 'move') { g.x += dx; g.y += dy; return dwPlace(win, g); }
      if (/e/.test(mode)) g.w = Math.min(g0.w + dx, innerWidth - g0.x);
      if (/s/.test(mode)) g.h = Math.min(g0.h + dy, innerHeight - g0.y);
      if (/w/.test(mode)) { const r = g0.x + g0.w; g.x = Math.max(0, Math.min(g0.x + dx, r - DW_MIN_W)); g.w = r - g.x; }
      if (/n/.test(mode)) { const b = g0.y + g0.h; g.y = Math.max(0, Math.min(g0.y + dy, b - DW_MIN_H)); g.h = b - g.y; }
      dwPlace(win, g);
    };
    const up = () => {
      handle.removeEventListener('pointermove', move);
      document.body.classList.remove('gdw-dragging');
      S().dwin = Object.assign({}, win.g);  // the next first window opens here
      saveState();
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', up, { once: true });
    handle.addEventListener('pointercancel', up, { once: true });
  });
}
// a diff header (path · revision · description): selectable, and copied from its right-click menu
function readableHead(head) {
  const t = head.querySelector('.gdm-t');
  const part = c => (t.querySelector(c).textContent || '').trim();
  readable(t, () => [
    { label: 'Copy Path', disabled: !part('.gdm-path'), run: () => copy(part('.gdm-path'), 'path') },
    { label: 'Copy Revision Number', disabled: !part('.gdm-hash'), run: () => copy(part('.gdm-hash'), 'revision') },
    { label: 'Copy Description', disabled: !part('.gdm-sub'), run: () => copy(part('.gdm-sub'), 'description') },
  ], { find: false });
}
function buildDiffWin() {  const bg = el('div', 'gdw');
  bg.tabIndex = -1;
  bg.innerHTML = `<div class="gdm-head" title="drag to move · double-click: maximize / restore">
      <div class="gdm-t"><span class="gdm-path"></span><span class="gdm-hash"></span><span class="gdm-sub"></span></div>
      <span class="gdm-pos"></span>
      <button data-a="prev" title="previous file (↑ / Alt+↑)">↑</button><button data-a="next" title="next file (↓ / Alt+↓)">↓</button>
      <button data-a="mode" title="side by side / unified"></button>
      <button data-a="eol" title="${EOL_TITLE}"></button>
      <button data-a="edit" title="open the file in the editor">Open in Editor</button>
      <button data-a="max" class="x" title="maximize / restore">□</button>
      <button data-a="close" class="x" title="close (Esc)">✕</button></div>
    <div class="gdm-body"><div class="gdm-ed"></div><div class="gdm-msg"></div></div>` +
    ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'].map(d => `<div class="gdw-rz gdw-${d}" data-d="${d}"></div>`).join('');
  document.body.appendChild(bg);
  const win = { id: ++DW.seq, bg, ed: null, own: [], items: [], idx: 0, gen: 0, spec: null, ident: '', opts: {}, g: null, max: false };
  bg.addEventListener('mousedown', () => dwFront(win), true);
  bg.addEventListener('focusin', () => dwFront(win));
  const head = bg.querySelector('.gdm-head');
  head.addEventListener('click', e => {
    const a = e.target.dataset && e.target.dataset.a;
    if (a === 'close') closeDiffWin(win);
    if (a === 'prev') showDiffItem(win, win.idx - 1);
    if (a === 'next') showDiffItem(win, win.idx + 1);
    if (a === 'mode') { S().inline = !S().inline; saveState(); allViewers().forEach(syncDiffMode); }
    if (a === 'eol') toggleIgnoreEol();
    if (a === 'edit') openDiffInEditor(win);
    if (a === 'max') dwMax(win);
  });
  head.addEventListener('dblclick', e => { if (!e.target.closest('button')) dwMax(win); });
  dwDrag(head, win, 'move');
  readableHead(head);
  bg.querySelectorAll('.gdw-rz').forEach(h => dwDrag(h, win, h.dataset.d));
  bg.addEventListener('keydown', e => {
    const inEditor = e.target.closest && e.target.closest('.monaco-editor');
    if (e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); closeDiffWin(win); }  // only this window
    else if ((e.key === 'ArrowUp' || e.key === 'ArrowDown') && (e.altKey || !inEditor)) {
      e.preventDefault(); showDiffItem(win, win.idx + (e.key === 'ArrowUp' ? -1 : 1));
    }
    e.stopPropagation();  // ReadO's document-level keys (Ctrl+W …) act on the editor, not from in here
  });
  return win;
}
// Line endings: Monaco splits lines at CR and LF alike, so a diff ignores CRLF / LF by itself
// ("Ignore line endings", the default). Turned off, every CR is drawn as ␍ and CRLF ↔ LF lines
// show as changed. Either way the header names differing line endings ("line endings LF → CRLF").
const EOL_TITLE = 'on: CRLF / LF differences are not shown as changes · off: CR shown as ␍, line-ending changes visible';
function eolOf(t) {
  if (!t) return '';
  const crlf = (t.match(/\r\n/g) || []).length, cr = (t.match(/\r/g) || []).length - crlf, lf = (t.match(/\n/g) || []).length - crlf;
  return crlf && !cr && !lf ? 'CRLF' : lf && !crlf && !cr ? 'LF' : cr && !crlf && !lf ? 'CR' : crlf + cr + lf ? 'mixed' : '';
}
const showCR = t => t.replace(/\r\n?/g, '␍\n');
function eolNote(left, right) {
  const a = eolOf(left), b = eolOf(right);
  return a && b && a !== b ? `line endings ${a} → ${b}` : '';
}
function toggleIgnoreEol() {
  S().ignoreEol = !S().ignoreEol; saveState();
  allViewers().forEach(v => { syncDiffMode(v); if (v.spec && !v.spec.error) showDiffItem(v, v.idx); });
}
function syncDiffMode(win) {
  const inline = !!S().inline, ws = win.bg.querySelector('[data-a="ws"]'), eol = win.bg.querySelector('[data-a="eol"]');
  win.bg.querySelector('[data-a="mode"]').textContent = inline ? 'Unified' : 'Side by side';
  if (ws) { ws.textContent = S().ignoreWs ? 'Ignore whitespace' : 'Do not ignore'; ws.classList.toggle('on', !!S().ignoreWs); }
  if (eol) { eol.textContent = S().ignoreEol ? 'Ignore line endings' : 'Show line endings'; eol.classList.toggle('on', !!S().ignoreEol); }
  if (win.ed) win.ed.updateOptions({ renderSideBySide: !inline, ignoreTrimWhitespace: !!S().ignoreWs });
}
// the inline pane: the diff window's header and Monaco diff editor, docked (no move / close / file walk)
function DiffPane(container, opts) {
  container.innerHTML = `<div class="gdm-head gdp-head">
      <div class="gdm-t"><span class="gdm-path"></span><span class="gdm-hash"></span><span class="gdm-sub"></span></div>
      <span class="gdm-pos"></span>
      <button data-a="prevChange" title="previous change">↑</button><button data-a="nextChange" title="next change">↓</button>
      <button data-a="mode" title="side by side / unified"></button>
      <button data-a="ws" title="ignore leading / trailing whitespace"></button>
      <button data-a="eol" title="${EOL_TITLE}"></button>
      <button data-a="edit" title="open the file in the editor">Open in Editor</button>
      <button data-a="win" title="open in a diff window (double-click the file)">Show in Window</button></div>
    <div class="gdm-body"><div class="gdm-ed"></div><div class="gdm-msg"></div></div>`;
  const v = { inline: true, bg: container, ed: null, own: [], items: [], idx: 0, gen: 0, spec: null, ident: '', opts: opts || {} };
  DV.add(v);
  readableHead(container.querySelector('.gdm-head'));
  container.querySelector('.gdm-head').addEventListener('click', e => {
    const a = e.target.dataset && e.target.dataset.a;
    if ((a === 'prevChange' || a === 'nextChange') && v.ed) v.ed.goToDiff(a === 'nextChange' ? 'next' : 'previous');
    if (a === 'mode') { S().inline = !S().inline; saveState(); allViewers().forEach(syncDiffMode); }
    if (a === 'ws') { S().ignoreWs = !S().ignoreWs; saveState(); allViewers().forEach(syncDiffMode); }
    if (a === 'eol') toggleIgnoreEol();
    if (a === 'edit') openDiffInEditor(v);
    if (a === 'win' && v.opts.onWindow) v.opts.onWindow();
  });
  // item: what to show; load(item) -> spec; ident: same one already shown -> nothing to do
  v.show = (item, load, ident, force) => {
    if (!force && ident && v.ident === ident && v.spec) return;
    v.items = [item]; v.load = load; v.opts.ident = () => ident;
    container.querySelectorAll('.gdm-head button').forEach(x => { x.disabled = false; });
    showDiffItem(v, 0);
  };
  v.clear = text => {
    v.gen++; v.ident = ''; v.spec = null;
    if (v.ed) v.ed.setModel(null);
    dropDiffModels(v);
    container.querySelectorAll('.gdm-path, .gdm-hash, .gdm-sub').forEach(x => { x.textContent = ''; });
    container.querySelector('.gdm-hash').style.display = 'none';
    container.querySelectorAll('.gdm-head button').forEach(b => { b.disabled = true; });
    container.querySelector('[data-a="mode"]').disabled = container.querySelector('[data-a="ws"]').disabled =
      container.querySelector('[data-a="eol"]').disabled = false;
    const msg = container.querySelector('.gdm-msg');
    msg.textContent = text || 'Select a file to see its changes'; msg.style.display = '';
  };
  v.dispose = () => {
    v.clear();
    DV.delete(v);
    if (v.ed) { v.ed.dispose(); v.ed = null; }
  };
  syncDiffMode(v);
  v.clear();
  return v;
}
// items: what ↑ / ↓ walk through; load(item) -> spec;
// opts: {ident(item) -> "revision|path" (already open: that window comes to the front), onShow(item, i), focus}
function openPanelWin(items, index, load, opts) {
  opts = opts || {};
  const id = opts.ident ? opts.ident(items[index]) : '';
  const same = id && DW.wins.find(w => w.ident === id);
  if (same) { dwFront(same); same.bg.focus(); return same; }
  while (DW.wins.length >= DW.max) closeDiffWin(DW.wins.reduce((a, b) => (a.id < b.id ? a : b)), true);  // the oldest
  const start = dwStart();
  const win = buildDiffWin();
  Object.assign(win, { items, load, opts });
  dwPlace(win, start);
  DW.wins.push(win);
  dwFront(win);
  syncDiffMode(win);
  win.bg.focus();
  showDiffItem(win, index);
  return win;
}
const DV = new Set();  // inline diff panes (Local Changes' right side)
const liveViewer = v => (v.inline ? DV.has(v) : DW.wins.includes(v));
const allViewers = () => DW.wins.concat([...DV]);
async function showDiffItem(win, i) {
  if (!liveViewer(win) || i < 0 || i >= win.items.length) return;
  win.idx = i;
  const gen = ++win.gen, item = win.items[i];
  win.ident = win.opts.ident ? win.opts.ident(item) : '';
  const head = win.bg.querySelector('.gdm-head');
  const btn = a => head.querySelector(`[data-a="${a}"]`) || {};
  btn('prev').disabled = i <= 0;
  btn('next').disabled = i >= win.items.length - 1;
  head.querySelector('.gdm-pos').textContent = win.items.length > 1 ? `${i + 1} / ${win.items.length}` : '';
  const msg = win.bg.querySelector('.gdm-msg');
  msg.textContent = 'loading…'; msg.style.display = '';
  if (win.opts.onShow) win.opts.onShow(item, i);
  let spec;
  try { spec = await win.load(item); } catch (e) { spec = { error: e.message, path: '' }; }
  if (gen !== win.gen || !liveViewer(win)) return;
  win.spec = spec;
  head.querySelector('.gdm-path').textContent = spec.path || '';
  head.querySelector('.gdm-path').title = spec.path || '';
  head.querySelector('.gdm-hash').textContent = spec.hash || '';
  head.querySelector('.gdm-hash').style.display = spec.hash ? '' : 'none';
  const rightText = spec.error ? '' : spec.doc ? spec.doc.model.getValue() : spec.right;
  const note = spec.error ? '' : eolNote(spec.left, rightText);
  head.querySelector('.gdm-sub').textContent = (spec.sub || '') + (note ? ' · ' + note : '');
  btn('edit').disabled = !spec.key;
  btn('win').disabled = !!spec.error;
  if (spec.error) { msg.textContent = spec.error; if (win.ed) win.ed.setModel(null); dropDiffModels(win); return; }
  msg.style.display = 'none';
  const lang = langFor(spec.path);
  if (!win.ed) win.ed = monaco.editor.createDiffEditor(win.bg.querySelector('.gdm-ed'), {
    automaticLayout: true, readOnly: true, originalEditable: false, renderSideBySide: !S().inline,
    ignoreTrimWhitespace: !!S().ignoreWs,
    fontSize: STATE.fontSize || 13, theme: getTheme() === 'dark' ? 'one-dark' : 'one-light',
  });
  const raw = !S().ignoreEol;  // CR drawn as ␍: the editor's own model cannot carry that, a read-only copy does
  const live = spec.doc && !raw;
  const original = monaco.editor.createModel(raw ? showCR(spec.left) : spec.left, lang);
  const modified = live ? spec.doc.model : monaco.editor.createModel(raw ? showCR(rightText) : rightText, lang);
  const old = win.own;
  win.own = live ? [original] : [original, modified];
  win.ed.updateOptions({ readOnly: !(live && canEdit(spec.doc)) });
  win.ed.setModel({ original, modified });
  old.forEach(m => m.dispose());
  const first = win.ed.onDidUpdateDiff(() => {
    first.dispose();
    const ch = win.ed && win.ed.getLineChanges();
    if (ch && ch.length) win.ed.getModifiedEditor().revealLineInCenter(Math.max(1, ch[0].modifiedStartLineNumber || 1));
  });
}
function dropDiffModels(win) { win.own.forEach(m => m.dispose()); win.own = []; }
function openDiffInEditor(win) {
  const s = win.spec;
  if (!s || !s.key) return;
  const ch = win.ed && win.ed.getLineChanges();
  const line = ch && ch.length ? Math.max(1, ch[0].modifiedStartLineNumber || 1) : undefined;
  if (!win.inline) closeDiffWin(win, true);
  openFile(s.key, s.hash ? undefined : line);
}
function closeDiffWin(win, keepFocus) {
  const i = win ? DW.wins.indexOf(win) : -1;
  if (i < 0) return;
  const hadFocus = win.bg.contains(document.activeElement);
  win.gen++;
  DW.wins.splice(i, 1);
  if (win.ed) { win.ed.setModel(null); win.ed.dispose(); win.ed = null; }  // a live editor model is never disposed here
  dropDiffModels(win);
  win.bg.remove();
  if (keepFocus || !hadFocus) return;
  const next = dmFront();
  if (next) { dwFront(next); next.bg.focus(); } else if (win.opts.focus) win.opts.focus.focus();
}
const closeDiffModal = () => closeDiffWin(dmFront());
const diffModalOpen = () => DW.wins.length > 0;
window.addEventListener('resize', () => DW.wins.forEach(w => dwPlace(w, w.g)));
// a file tree's visible files, opened at `row`; the tree's selection follows prev / next.
// rev: what the files are compared at ("L:<repo>" for local changes, "C:<hash>" for a commit)
function openTreeDiff(tree, row, load, rev, desc, repo) {
  const list = tree.rows.filter(r => r.file);
  const i = Math.max(0, list.findIndex(r => r.id === row.id));
  openDiffWin(list, i, r => load(r.file), { ident: r => rev + '|' + r.file.path, onShow: r => tree.selectId(r.id), focus: tree.container,
    repo, desc: desc && (r => desc(r.file)) });
}
// single-file entry points (context menus, History rows)
function diffLocal(repo, f) { openDiffWin([f], 0, x => specLocal(repo, x), { ident: x => 'L:' + repo.root + '|' + x.path, repo, desc: x => descLocal(repo, x) }); }
function diffCommitFile(repo, c, f) { openDiffWin([f], 0, x => specCommit(repo, c, x), { ident: x => 'C:' + c.h + '|' + x.path, repo, desc: x => descCommit(repo, c, x) }); }

// ---------- file tree (Local Changes, commit files, stash files) ----------
// groups: [{id, label, files:[{path, st, cls, orig, add, del, tag, ...}], check}]
function buildTree(files) {
  const root = { dirs: new Map(), files: [] };
  for (const f of files) {
    const parts = f.path.replace(/\/$/, '').split('/');
    let n = root;
    for (const p of parts.slice(0, -1)) {
      if (!n.dirs.has(p)) n.dirs.set(p, { dirs: new Map(), files: [] });
      n = n.dirs.get(p);
    }
    n.files.push(f);
  }
  return root;
}
const countFiles = n => n.files.length + [...n.dirs.values()].reduce((a, d) => a + countFiles(d), 0);
function FileTree(container, opts) {
  const self = { groups: [], collapsed: new Set(opts.collapsed || []), sel: null, checked: new Set(), rows: [], container };
  container.tabIndex = 0;
  self.set = (groups, keepChecks) => {
    self.groups = groups;
    if (!keepChecks) {
      self.checked = new Set();
      groups.forEach(g => g.check && g.files.forEach(f => self.checked.add(g.id + '|' + f.path)));
    }
    render();
  };
  self.selected = () => self.sel && self.rows.find(r => r.id === self.sel);
  // move the selection (diff modal prev / next) without re-rendering; scroll only if it is out of view
  self.selectId = id => {
    self.sel = id;
    let hit = null;
    container.querySelectorAll('.gt-row').forEach(r => { const on = r.dataset.id === id; r.classList.toggle('sel', on); if (on) hit = r; });
    if (hit) hit.scrollIntoView({ block: 'nearest' });
  };
  self.checkedFiles = () => self.groups.flatMap(g => g.files.filter(f => self.checked.has(g.id + '|' + f.path)));
  function render() {
    const out = [];
    self.rows = [];
    const push = (id, html, row) => { self.rows.push(Object.assign({ id }, row)); out.push(html.replace('<div class="gt-row', `<div data-id="${esc(id)}" class="gt-row${self.sel === id ? ' sel' : ''}`)); };
    for (const g of self.groups) {
      const gid = 'g:' + g.id;
      const open = !self.collapsed.has(gid);
      if (opts.showGroups !== false) {
        push(gid, `<div class="gt-row group" style="padding-left:4px"><span class="tw">${open ? '▾' : '▸'}</span>` +
          (opts.checkable && g.checkable !== false ? `<input type="checkbox" data-chk="${esc(gid)}"${g.files.length && g.files.every(f => self.checked.has(g.id + '|' + f.path)) ? ' checked' : ''}>` : '') +
          `<span class="nm">${esc(g.label)}</span><span class="cnt">${g.files.length} file${g.files.length === 1 ? '' : 's'}</span></div>`, { group: g });
      }
      if (!open) continue;
      const walk = (node, prefix, depth, gpath) => {
        for (const [name, d] of [...node.dirs.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
          let label = name, sub = d, full = gpath ? gpath + '/' + name : name;
          while (!sub.files.length && sub.dirs.size === 1) {  // compress a/b/c
            const [n2, d2] = [...sub.dirs.entries()][0];
            label += '/' + n2; full += '/' + n2; sub = d2;
          }
          const id = g.id + '|d:' + full;
          const o = !self.collapsed.has(id);
          push(id, `<div class="gt-row" style="padding-left:${depth * 16 + 4}px"><span class="tw">${o ? '▾' : '▸'}</span>` +
            `${FOLDER_SVG}<span class="nm">${esc(label)}</span><span class="cnt">${countFiles(sub)} file${countFiles(sub) === 1 ? '' : 's'}</span></div>`, { dir: full, group: g });
          if (o) walk(sub, '', depth + 1, full);
        }
        for (const f of node.files.slice().sort((a, b) => a.path.localeCompare(b.path))) {
          const id = g.id + '|' + f.path;
          const name = f.path.replace(/\/$/, '').split('/').pop() + (f.path.endsWith('/') ? '/' : '');
          push(id, `<div class="gt-row ${f.cls || ''}" style="padding-left:${depth * 16 + 4}px"><span class="tw"></span>` +
            (opts.checkable && g.checkable !== false ? `<input type="checkbox" data-chk="${esc(id)}"${self.checked.has(id) ? ' checked' : ''}>` : '') +
            `<span class="st">${esc(f.st || '')}</span><span class="nm">${esc(name)}</span>` +
            (f.orig ? `<span class="dim">← ${esc(f.orig)}</span>` : '') + (f.tag ? `<span class="tag">${esc(f.tag)}</span>` : '') +
            (f.add != null && (f.add || f.del) ? `<span class="num"><span class="a">+${f.add}</span> <span class="d">−${f.del}</span></span>` : (f.binary ? '<span class="num">binary</span>' : '')) +
            '</div>', { file: f, group: g });
        }
      };
      walk(buildTree(g.files), '', opts.showGroups === false ? 0 : 1, '');
    }
    container.innerHTML = out.join('') || `<div class="gw-empty">${esc(opts.empty || 'no files')}</div>`;
  }
  const rowOf = e => { const r = e.target.closest('.gt-row'); return r && self.rows.find(x => x.id === r.dataset.id); };
  const toggle = row => { self.collapsed.has(row.id) ? self.collapsed.delete(row.id) : self.collapsed.add(row.id); render(); };
  container.addEventListener('click', e => {
    const chk = e.target.dataset && e.target.dataset.chk;
    const row = rowOf(e);
    if (chk && row) {
      const on = e.target.checked;
      const files = row.file ? [row] : self.groups.filter(g => g === row.group).flatMap(g => g.files.filter(f => !row.dir || f.path.startsWith(row.dir + '/')).map(f => ({ id: g.id + '|' + f.path })));
      files.forEach(r => on ? self.checked.add(r.id) : self.checked.delete(r.id));
      render();
      if (opts.onCheck) opts.onCheck();
      return;
    }
    if (!row) return;
    self.sel = row.id;
    if (!row.file) return toggle(row);
    self.selectId(row.id);
    if (opts.onFile) opts.onFile(row);  // single click: the diff (Local Changes: the right pane; elsewhere: a diff window)
  });
  container.addEventListener('dblclick', e => {
    const row = rowOf(e);
    if (row && row.file && opts.onOpen && !(e.target.dataset && e.target.dataset.chk)) opts.onOpen(row);
  });
  container.addEventListener('contextmenu', e => {
    const row = rowOf(e);
    if (!row || !opts.onMenu) return;
    e.preventDefault();
    self.sel = row.id;
    container.querySelectorAll('.gt-row.sel').forEach(r => r.classList.remove('sel'));
    e.target.closest('.gt-row').classList.add('sel');
    opts.onMenu(e, row.file, row.group, row);
  });
  container.addEventListener('keydown', e => {
    const i = self.rows.findIndex(r => r.id === self.sel);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const n = Math.max(0, Math.min(self.rows.length - 1, i + (e.key === 'ArrowDown' ? 1 : -1)));
      if (self.rows[n]) { self.sel = self.rows[n].id; render(); const s = container.querySelector('.sel'); if (s) s.scrollIntoView({ block: 'nearest' });
        if (opts.onSelect && self.rows[n].file) opts.onSelect(self.rows[n]);
      }
    } else if ((e.key === 'Enter' || (e.key === 'd' && e.ctrlKey)) && i >= 0) {
      e.preventDefault(); e.stopPropagation();
      const r = self.rows[i];
      const enter = opts.onEnter || opts.onFile;
      if (r.file && enter) enter(r); else if (!r.file) toggle(r);
    } else if ((e.key === 'ArrowRight' || e.key === 'ArrowLeft') && i >= 0 && !self.rows[i].file) {
      e.preventDefault();
      const closed = self.collapsed.has(self.rows[i].id);
      if ((e.key === 'ArrowRight') === closed) toggle(self.rows[i]);
    }
  });
  return self;
}

// ---------- tool window frame ----------
let W = null;  // DOM refs
function buildWindow() {
  const gw = el('div', 'gw');
  gw.id = 'gitWin';
  gw.innerHTML = `<div class="gw-sash"></div>
   <div class="gw-head">
    <span class="gw-title">Git</span>
    <span class="gw-tab" data-tab="changes">Local Changes</span>
    <span class="gw-tab" data-tab="log">Log</span>
    <span class="gw-tab" data-tab="history" style="display:none"></span>
    <span class="gw-tab" data-tab="stash">Stash</span>
    <span class="gw-tab" data-tab="console">Console</span>
    <span class="gw-spacer"></span>
    <select class="gw-repo" title="repository"></select>
    <button class="gw-ibtn gw-br" data-a="branch" title="branches: check out, pull, fetch">⎇ <span class="nm">…</span></button>
    <button class="gw-ibtn" data-a="pull" title="Pull (git pull --ff-only: fast-forward only)">↓ Pull</button>
    <button class="gw-ibtn" data-a="fetch" title="Fetch (git fetch --prune)">Fetch</button>
    <button class="gw-ibtn" data-a="refresh" title="refresh">⟳</button>
    <button class="gw-ibtn agent" data-a="agent" title="ask AgentO to change the repository (commit, push, branches …)">AgentO ▾</button>
    <button class="gw-ibtn" data-a="close" title="hide (Alt+9 / Ctrl+Shift+G)">✕</button>
   </div>
   <div class="gw-body">
    <div class="gw-page" data-page="changes"></div>
    <div class="gw-page" data-page="log"></div>
    <div class="gw-page" data-page="history"></div>
    <div class="gw-page" data-page="stash"></div>
    <div class="gw-page" data-page="console"></div>
    <div class="gw-page" data-page="msg"><div class="gw-msg"></div></div>
   </div>`;
  document.body.insertBefore(gw, document.getElementById('statusbar'));
  W = { gw, head: gw.querySelector('.gw-head'), repoSel: gw.querySelector('.gw-repo'), pages: {} };
  gw.querySelectorAll('.gw-page').forEach(p => { W.pages[p.dataset.page] = p; });
  gw.style.height = Math.max(120, Math.min(S().h, innerHeight - 200)) + 'px';
  W.head.addEventListener('click', e => {
    const tab = e.target.closest('.gw-tab');
    if (tab) {
      if (e.target.classList.contains('x')) { closeHistory(); return; }
      return setTab(tab.dataset.tab);
    }
    const btn = e.target.closest('[data-a]'), a = btn && btn.dataset.a;
    if (a === 'close') toggleWindow(false);
    if (a === 'refresh') refreshAll(true);
    if (a === 'branch' && G.repo) branchPopup(btn, G.repo);
    if (a === 'pull' && G.repo) tbPull(G.repo);
    if (a === 'fetch' && G.repo) gitFetch(G.repo);
    if (a === 'agent') agentMenu(e.target);
  });
  W.repoSel.addEventListener('change', () => selectRepo(W.repoSel.value));
  // resize by the top edge
  const sash = gw.querySelector('.gw-sash');
  sash.addEventListener('mousedown', e => {
    e.preventDefault();
    sash.classList.add('drag');
    const y0 = e.clientY, h0 = gw.getBoundingClientRect().height;
    const mv = ev => { gw.style.height = Math.max(120, Math.min(innerHeight - 160, h0 + y0 - ev.clientY)) + 'px'; };
    const up = () => { sash.classList.remove('drag'); removeEventListener('mousemove', mv); removeEventListener('mouseup', up);
      S().h = Math.round(gw.getBoundingClientRect().height); saveState(); };
    addEventListener('mousemove', mv); addEventListener('mouseup', up);
  });
}
function agentMenu(anchor) {
  const r = anchor.getBoundingClientRect();
  const st = G.status || {}, b = st.branch || {};
  const conflicted = (st.files || []).filter(f => f.kind === 'conflicted').map(f => f.path);
  showMenu(r.left, r.bottom + 2, [
    { label: 'Commit…', hint: STATE.keymap === 'intellij' ? 'Ctrl+K' : '', run: () => runCommand('git.agentCommit') },
    { label: 'Push…', hint: STATE.keymap === 'intellij' ? 'Ctrl+Shift+K' : '', run: () => agentDialog('push', { branch: b.head, upstream: b.upstream }) },
    'sep',
    { label: 'New Branch…', run: () => agentDialog('newBranch', {}) },
    { label: 'Stash Changes…', run: () => agentDialog('stashPush') },
    { label: 'Resolve Conflicts…', disabled: !conflicted.length, run: () => agentDialog('resolve', { files: conflicted, state: G.repo && G.repo.state }) },
    'sep',
    { label: 'Ask AgentO…', run: () => agentDialog('ask') },
    { label: 'Open AgentO', run: () => openAgentO() },
    { label: 'Open Terminal Here', run: () => openTerminal() },
  ]);
}
function toggleWindow(on) {
  S();
  if (!W) buildWindow();
  STATE.git.open = on == null ? !STATE.git.open : !!on;
  W.gw.classList.toggle('show', STATE.git.open);
  if (window.refreshToolStrip) refreshToolStrip();  // ReadO's tool strip: Git icon state
  saveState();
  if (STATE.git.open) start();
}
async function start() {
  if (!G.info) G.info = await api('info');
  if (!G.info.available) return showMsg(`<b>Git views are off</b><br>${esc(ERR_TEXT[G.info.reason] || G.info.reason)}` +
    (G.info.version ? `<br>found git ${esc(G.info.version)}` : ''));
  if (!G.repos.length) await loadRepos();
  if (!G.repo) return showMsg(_settings.base_dir ? '<b>No git repository</b><br>in or around the open folder' : '<b>No folder open</b>');
  setTab(STATE.git.tab || 'changes');
}
function showMsg(html) {
  if (!W) return;
  Object.values(W.pages).forEach(p => p.classList.remove('active'));
  W.pages.msg.classList.add('active');
  W.pages.msg.firstElementChild.innerHTML = html;
}
function setTab(tab) {
  S().tab = tab;
  saveState();
  if (!W) return;
  W.head.querySelectorAll('.gw-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  if (!G.repo || (G.info && !G.info.available)) return start();
  Object.entries(W.pages).forEach(([k, p]) => p.classList.toggle('active', k === tab));
  if (tab === 'changes') Changes.show();
  if (tab === 'log') Log.show();
  if (tab === 'history' && History) History.show();
  if (tab === 'stash') Stash.show();
  if (tab === 'console') Console_.show();
}
async function loadRepos() {
  const d = await api('repos');
  G.repos = d.repos || [];
  let want = S().repo;
  if (!G.repos.some(r => r.root === want)) {
    const doc = currentDoc();
    const inf = doc ? await api('info', { path: doc.key }) : null;
    want = inf && inf.repo ? inf.repo.root : (G.repos[0] || {}).root;
    if (inf && inf.repo && !G.repos.some(r => r.root === inf.repo.root)) G.repos.unshift(inf.repo);
  }
  renderRepoSel();
  if (want) await selectRepo(want, true);
  else G.repo = null;
}
function renderRepoSel() {
  if (!W) return;
  W.repoSel.innerHTML = G.repos.map(r => `<option value="${esc(r.root)}">${esc(r.name)}</option>`).join('');
  W.repoSel.style.display = G.repos.length > 1 ? '' : 'none';
  if (G.repo) W.repoSel.value = G.repo.root;
}
async function selectRepo(root, quiet) {
  let r = G.repos.find(x => x.root === root);
  if (!r) {
    const inf = await api('info', { repo: root });
    if (!inf.repo) return showToast('not a repository: ' + root, true);
    r = inf.repo;
    G.repos.push(r);
    renderRepoSel();
  }
  const changed = !G.repo || G.repo.root !== r.root;
  G.repo = r;
  S().repo = r.root;
  saveState();
  if (W) W.repoSel.value = r.root;
  if (changed) { G.status = null; G.refs = null; G.fp = ''; Log.reset(); Changes.reset(); Stash.reset(); closeHistory(true); }
  if (!quiet && W && STATE.git.open) setTab(STATE.git.tab);
  updateBranch();
}

// ---------- data refresh ----------
async function loadStatus(fresh) {
  if (!G.repo) return null;
  const d = await api('status', { repo: G.repo.root, fresh: fresh ? 1 : 0 }, 'status');
  if (d.aborted) return G.status;
  if (d.error) { G.status = { error: d }; return G.status; }
  G.status = d;
  if (d.repo) G.repo.state = d.repo.state;
  updateBranch();
  updateConflicts();
  return d;
}
async function loadRefs() {
  if (!G.repo) return null;
  const d = await api('refs', { repo: G.repo.root }, 'refs');
  if (!d.error && !d.aborted) G.refs = d;
  return G.refs;
}
async function refreshAll(user) {
  if (!G.repo) { await loadRepos(); if (STATE.git.open) start(); return; }
  if (user) { G.info = null; G.info = await api('info'); }
  await loadStatus(true);
  await loadRefs();
  if (STATE.git.open) {
    const t = STATE.git.tab;
    if (t === 'changes') Changes.render();
    if (t === 'log') Log.reload(true);
    if (t === 'history' && History) History.reload(true);
    if (t === 'stash') Stash.load();
  } else Log.stale = true;
  refreshDecor();
}
// cheap fingerprint poll; status itself every 10 s while visible (working-tree edits do not move it)
let _tick = 0, _fpBusy = false;
async function poll() {
  if (document.hidden || _fpBusy || !G.repo || !G.info || !G.info.available) return;
  _fpBusy = true;
  try {
    _tick++;
    const d = await api('fp', { repo: G.repo.root });
    if (d.fp && d.fp !== G.fp) {
      const first = !G.fp;
      G.fp = d.fp;
      if (!first) {
        await loadStatus(true); await loadRefs();
        if (STATE.git.open && STATE.git.tab === 'changes') Changes.render();
        if (Log.loaded) Log.reload(false); else Log.stale = true;
        if (History && History.loaded) History.reload(false);
        if (STATE.git.open && STATE.git.tab === 'stash') Stash.load();
      }
    } else if (_tick % 4 === 0 && (STATE.git.open && STATE.git.tab === 'changes' || !G.status)) {
      await loadStatus(false);
      if (STATE.git.open && STATE.git.tab === 'changes') Changes.render();
    }
    if (_tick % 2 === 0) refreshDecor();
  } finally { _fpBusy = false; }
}

// ---------- Local Changes ----------
const KIND_ST = { modified: 'M', added: 'A', deleted: 'D', renamed: 'R', copied: 'C', typechange: 'T', conflicted: '!', untracked: '?' };
// changed files as the page counts them: line-ending-only ones (status "eol") left out unless shown
const shownFiles = st => (st && st.files ? (S().showEol ? st.files : st.files.filter(f => !f.eol)) : []);
function toggleShowEol() {
  S().showEol = !S().showEol; saveState();
  Changes.render(); renderTB(); refreshDecor();
}
const Changes = {
  tree: null, built: false,
  reset() { if (this.pane) this.pane.dispose(); this.pane = null; this.built = false; this._known = null; this._sig = null; if (W) W.pages.changes.innerHTML = ''; },
  build() {
    const p = W.pages.changes;
    p.innerHTML = `<div class="gw-col lc-left" style="width:${S().cw}px">
      <div class="gw-banner" style="display:none"></div>
      <div class="gw-bar">
        <button data-a="refresh" title="refresh">⟳</button>
        <button data-a="diff" title="show the selected file's diff in a window (double-click / Enter)">diff</button>
        <button data-a="expand" title="expand all">+</button><button data-a="collapse" title="collapse all">−</button>
        <button data-a="commit" class="agent" title="ask AgentO to commit the ticked files">Commit… (AgentO)</button>
        <button data-a="rollback" title="ask AgentO to roll back the ticked files">Rollback…</button>
        <button data-a="eol" class="tg" title="files whose only difference from HEAD is CRLF ↔ LF line endings (hidden by default; also in counts and tree colours)">Show line-ending-only changes</button>
        <span class="sum"></span>
      </div>
      <div class="gw-scroll"></div></div>
      <div class="gw-vsash" data-s="cw"></div>
      <div class="gw-col lc-diff"></div>`;
    this.bar = p.querySelector('.gw-bar');
    this.banner = p.querySelector('.gw-banner');
    this.tree = FileTree(p.querySelector('.gw-scroll'), {
      checkable: true, empty: 'no local changes',
      onFile: row => this.select(row),                                   // click: the diff on the right
      onSelect: row => { clearTimeout(this._selT); this._selT = setTimeout(() => this.select(row), 60); },  // ↑ / ↓
      onOpen: row => this.diff(row), onEnter: row => this.diff(row),     // double-click / Enter: a diff window
      onMenu: (e, f, g, row) => this.menu(e, f, row),
    });
    this.pane = DiffPane(p.querySelector('.lc-diff'), { onWindow: () => { const r = this.tree.selected(); if (r && r.file) this.diff(r); } });
    const sash = p.querySelector('.gw-vsash'), left = p.querySelector('.lc-left');
    sash.addEventListener('mousedown', ev => {
      ev.preventDefault();
      const x0 = ev.clientX, w0 = left.getBoundingClientRect().width;
      sash.classList.add('drag');
      const mv = e2 => { left.style.width = Math.max(200, Math.min(p.clientWidth - 240, w0 + e2.clientX - x0)) + 'px'; };
      const up = () => { sash.classList.remove('drag'); removeEventListener('mousemove', mv); removeEventListener('mouseup', up);
        S().cw = Math.round(left.getBoundingClientRect().width); saveState(); };
      addEventListener('mousemove', mv); addEventListener('mouseup', up);
    });
    this.bar.addEventListener('click', e => {
      const a = e.target.dataset && e.target.dataset.a;
      if (a === 'refresh') loadStatus(true).then(() => this.render());
      if (a === 'diff') { const r = this.tree.selected(); if (r && r.file) this.diff(r); else showToast('select a file'); }
      if (a === 'expand') { this.tree.collapsed.clear(); this.tree.set(this.tree.groups, true); }
      if (a === 'collapse') { this.tree.rows.filter(r => !r.file).forEach(r => this.tree.collapsed.add(r.id)); this.tree.set(this.tree.groups, true); }
      if (a === 'commit') this.agentFiles('commit');
      if (a === 'rollback') this.agentFiles('rollback');
      if (a === 'eol') toggleShowEol();
    });
    this.built = true;
  },
  diff(row) { const repo = G.repo; openTreeDiff(this.tree, row, f => specLocal(repo, f.raw), 'L:' + repo.root, f => descLocal(repo, f.raw), repo); },
  select(row, force) {
    if (!row || !row.file || !this.pane) return;
    const repo = G.repo, f = row.file;
    this.pane.show(f, x => specLocal(repo, x.raw), 'L:' + repo.root + '|' + f.path, force);
  },
  agentFiles(action) {
    const files = this.tree.checkedFiles().filter(f => action !== 'commit' || f.raw.kind !== 'conflicted').map(f => f.path);
    if (!files.length) return showToast('tick the files first', true);
    agentDialog(action, { files });
  },
  menu(e, f, row) {
    if (!f) return;
    const raw = f.raw, key = keyFor(G.repo, raw.path);
    showMenu(e.clientX, e.clientY, [
      { label: 'Show Diff in Window', hint: 'double-click / Enter', run: () => this.diff(row) },
      { label: 'Open File', disabled: !key || raw.kind === 'deleted', run: () => openFile(key) },
      { label: 'Show History', disabled: raw.kind === 'untracked' || raw.kind === 'added', run: () => openHistory(G.repo, raw.orig || raw.path) },
      { label: 'Copy Path', run: () => copy(raw.path, 'path') },
      'sep',
      { label: 'Commit This File… (AgentO)', disabled: raw.kind === 'conflicted', run: () => agentDialog('commit', { files: [raw.path] }) },
      { label: 'Rollback… (AgentO)', run: () => agentDialog('rollback', { files: [raw.path] }) },
      { label: 'Resolve Conflict… (AgentO)', disabled: raw.kind !== 'conflicted', run: () => agentDialog('resolve', { files: [raw.path], state: G.repo.state }) },
    ]);
  },
  async show() {
    if (!this.built) this.build();
    if (!G.status) { this.bar.querySelector('.sum').textContent = 'loading…'; await loadStatus(false); }
    this.render();
  },
  render() {
    if (!this.built || !G.status) return;
    const st = G.status;
    if (st.error) { this.tree.set([]); this.bar.querySelector('.sum').textContent = errText(st.error); return; }
    const mk = f => ({ path: f.path, orig: f.orig, st: KIND_ST[f.kind] || 'M', cls: 'k-' + f.kind + (f.eol ? ' k-eol' : ''), raw: f,
      tag: f.eol ? 'line endings only' : f.kind === 'untracked' || f.kind === 'conflicted' ? '' : f.staged && f.unstaged ? 'partly staged' : f.staged ? 'staged' : '' });
    const shown = shownFiles(st);
    const conf = shown.filter(f => f.kind === 'conflicted').map(mk);
    const unv = shown.filter(f => f.kind === 'untracked').map(mk);
    const chg = shown.filter(f => f.kind !== 'conflicted' && f.kind !== 'untracked').map(mk);
    const eb = this.bar.querySelector('[data-a="eol"]');
    eb.classList.toggle('on', !!S().showEol);
    eb.style.display = st.eol_only || S().showEol ? '' : 'none';
    const groups = [];
    if (conf.length) groups.push({ id: 'conflicts', label: 'Merge Conflicts', files: conf, check: false });
    groups.push({ id: 'changes', label: 'Changes', files: chg, check: true });
    if (unv.length) groups.push({ id: 'unversioned', label: 'Unversioned Files', files: unv, check: false });
    const sig = JSON.stringify(shown.map(f => f.path + f.x + f.y + (f.eol ? 'e' : '')));
    if (this._sig !== sig) {
      this._sig = sig;
      const ids = groups.flatMap(g => g.files.map(f => g.id + '|' + f.path));
      if (!this._known) this.tree.set(groups, false);  // first time: everything under Changes ticked
      else {  // keep the user's ticks; files that are new under Changes start ticked
        const keep = new Set(ids.filter(id => this.tree.checked.has(id) || (!this._known.has(id) && id.startsWith('changes|'))));
        this.tree.checked = keep;
        this.tree.set(groups, true);
      }
      this._known = new Set(ids);
      // the right pane: refresh the selected file, or ask for one
      const sel = this.tree.selected();
      if (sel && sel.file) this.select(sel, true); else this.pane.clear();
    }
    const b = st.branch || {};
    const n = shown.length - (S().showEol ? st.eol_only || 0 : 0);
    this.bar.querySelector('.sum').textContent = `${n} file${n === 1 ? '' : 's'}${st.truncated ? '+ (list cut)' : ''} · ` +
      (st.eol_only ? `${st.eol_only} line-ending-only ${S().showEol ? 'shown' : 'hidden'} · ` : '') +
      (b.detached ? 'detached HEAD ' + short(b.oid) : '⎇ ' + (b.head || '?')) +
      (b.upstream ? ` → ${b.upstream} ↑${b.ahead} ↓${b.behind}` : '') + (st.ms > 800 ? ` · status ${st.ms} ms` : '');
    const state = st.repo && st.repo.state;
    this.banner.style.display = state ? '' : 'none';
    if (state) {
      this.banner.innerHTML = `<b>${esc(state.toUpperCase())}</b><span>${conf.length} conflicted file${conf.length === 1 ? '' : 's'} — ReadO shows them; AgentO resolves them</span>` +
        `<button>Resolve… (AgentO)</button>`;
      this.banner.querySelector('button').onclick = () => agentDialog('resolve', { files: conf.map(f => f.path), state });
    }
  },
};

// ---------- graph lanes ----------
// st: {lanes: [sha|null], colors: [n], next}; returns the row's drawing data
function laneStep(st, c, graph) {
  const before = st.lanes, cb = st.colors;
  const after = before.slice(), ca = cb.slice();
  let col = before.indexOf(c.h);
  if (col < 0) {
    col = after.indexOf(null);
    if (col < 0) col = after.length;
    ca[col] = st.next++;
  }
  const color = ca[col];
  after[col] = null;
  const ps = graph ? c.p : [];
  ps.forEach((p, i) => {
    if (after.indexOf(p) >= 0) return;  // joins a line that is already there
    if (i === 0 && after[col] === null) { after[col] = p; ca[col] = color; return; }
    let j = after.indexOf(null);
    if (j < 0 || j === col) { j = after.indexOf(null, col + 1); if (j < 0) j = after.length; }
    after[j] = p; ca[j] = st.next++;
  });
  while (after.length && after[after.length - 1] === null) { after.pop(); ca.pop(); }
  st.lanes = after; st.colors = ca;
  return { col, color, before, cb, after, ca };
}
const lx = k => 8 + k * LANE_W;
const lc = n => LANE_COLORS[n % LANE_COLORS.length];
function graphSvg(row, c, graph) {
  const H = ROW_H, m = H / 2;
  if (!graph) return `<svg width="20" height="${H}"><circle cx="10" cy="${m}" r="3.5" fill="${lc(0)}"/></svg>`;
  const { col, before, cb, after, ca, color } = row;
  const width = Math.min(MAX_LANES, Math.max(before.length, after.length, col + 1)) * LANE_W + 6;
  const seg = (x1, y1, x2, y2, clr) => x1 === x2
    ? `<path d="M${x1} ${y1}L${x2} ${y2}" stroke="${clr}"/>`
    : `<path d="M${x1} ${y1}C${x1} ${(y1 + y2) / 2} ${x2} ${(y1 + y2) / 2} ${x2} ${y2}" stroke="${clr}"/>`;
  let s = '';
  for (let k = 0; k < before.length && k < MAX_LANES; k++) {
    const sha = before[k];
    if (!sha) continue;
    if (sha === c.h) s += seg(lx(k), 0, lx(col), m, lc(cb[k]));
    else {
      const k2 = after.indexOf(sha);
      if (k2 >= 0 && k2 < MAX_LANES) s += seg(lx(k), 0, lx(k2), H, lc(cb[k]));
    }
  }
  c.p.forEach(p => {
    const j = after.indexOf(p);
    if (j >= 0 && j < MAX_LANES) s += seg(lx(col), m, lx(j), H, lc(ca[j]));
  });
  const merge = c.p.length > 1;
  s += col < MAX_LANES ? `<circle cx="${lx(col)}" cy="${m}" r="${merge ? 3 : 3.6}" fill="${merge ? 'var(--panel)' : lc(color)}" stroke="${lc(color)}" stroke-width="${merge ? 1.6 : 0}"/>` : '';
  return `<svg width="${width}" height="${H}" fill="none" stroke-width="1.6">${s}</svg>`;
}
function refChips(refs) {
  return (refs || []).map(r => {
    let cls = 'remote', name = r;
    if (r.startsWith('HEAD -> ')) { cls = 'head'; name = r.slice(8); }
    else if (r === 'HEAD') { cls = 'head'; }
    else if (r.startsWith('tag: ')) { cls = 'tag'; name = r.slice(5); }
    else if (G.refs && G.refs.local.some(b => b.name === r)) cls = 'local';
    return `<span class="ref ${cls}" title="${esc(r)}">${esc(name)}</span>`;
  }).join('');
}

// ---------- Log view (also used for a file's History) ----------
function LogView(page, opts) {
  const V = {
    page, opts, rows: [], lane: null, built: false, loaded: false, loading: false, hasMore: true,
    selIdx: -1,         // the lead row (keyboard, details of one commit)
    selH: new Set(),    // hashes of all selected rows
    anchor: -1,         // where Shift+click / Shift+arrows extend from
    filters: Object.assign({ text: '', regex: false, case: false, ref: [], author: [], since: '', until: '', path: [] }, opts.filters || {}),
    gen: 0, stale: false,
  };
  V.reset = () => { V.built = false; V.loaded = false; V.rows = []; page.innerHTML = ''; };
  V.graphOn = () => !(V.filters.text || V.filters.author.length || V.filters.since || V.filters.until);
  V.build = () => {
    const st = S();
    page.innerHTML = (opts.history ? '' : `<div class="gw-col gl-branches" style="width:${st.bw}px"><input class="gb-filter" placeholder="branches…" spellcheck="false"><div class="gw-scroll gb-tree"></div></div><div class="gw-vsash" data-s="bw"></div>`) +
      `<div class="gl-wrap"><div class="gl-filter">
        <input class="q" placeholder="${opts.history ? 'Text or hash in this file’s history' : 'Text or hash'}" spellcheck="false">
        <button class="fb opt" data-f="regex" title="regex">.*</button><button class="fb opt" data-f="case" title="match case">Cc</button>
        ${opts.history ? '' : '<button class="fb" data-f="ref">Branch ▾</button>'}
        <button class="fb" data-f="author">User ▾</button><button class="fb" data-f="date">Date ▾</button>
        ${opts.history ? '' : '<button class="fb" data-f="path">Paths ▾</button>'}
        <button class="fb" data-f="reload" title="refresh">⟳</button>
        <span class="cnt"></span></div>
        <div class="gl-head" title="drag a column edge to resize (double-click: default width) · right-click: columns"><span class="msg">Subject</span>${
          LOG_COLS.map(c => `<span class="${c.k}" data-c="${c.k}"><i class="gl-rs" data-c="${c.k}"></i>${c.label}</span>`).join('')}</div>
        <div class="gl-list" tabindex="0"><div class="gl-rows"></div></div></div>
      <div class="gw-vsash" data-s="dw"></div>
      <div class="gw-col gl-details" style="width:${st.dw}px"><div class="gd-sum"></div><div class="gd-files"></div><div class="gd-msg"></div></div>`;
    V.list = page.querySelector('.gl-list');
    V.rowsEl = page.querySelector('.gl-rows');
    V.cnt = page.querySelector('.cnt');
    V.q = page.querySelector('.q');
    V.files = FileTree(page.querySelector('.gd-files'), {
      showGroups: false, empty: 'select a commit',
      onFile: row => V.fileDiff(row),
      onMenu: (e, f, g, row) => f && V.fileMenu(e, f.raw, row),
    });
    V.sum = page.querySelector('.gd-sum');
    V.msg = page.querySelector('.gd-msg');
    V.branchTree = page.querySelector('.gb-tree');
    V.head = page.querySelector('.gl-head');
    applyLogCols();
    V.head.addEventListener('mousedown', e => {
      const rs = e.target.closest('.gl-rs');
      if (!rs || e.button !== 0) return;
      e.preventDefault();
      const k = rs.dataset.c, def = LOG_COLS.find(c => c.k === k), col = logCols()[k];
      const x0 = e.clientX, w0 = col.w;
      rs.classList.add('drag');
      // the edge is the column's left side: dragging left widens it
      const mv = e2 => { col.w = Math.max(def.min, Math.min(LOG_COL_MAX, Math.round(w0 - (e2.clientX - x0)))); applyLogCols(); };
      const up = e2 => { mv(e2); rs.classList.remove('drag'); removeEventListener('mousemove', mv); removeEventListener('mouseup', up); saveState(); };
      addEventListener('mousemove', mv); addEventListener('mouseup', up);
    });
    V.head.addEventListener('dblclick', e => {
      const rs = e.target.closest('.gl-rs');
      if (!rs) return;
      logCols()[rs.dataset.c].w = LOG_COLS.find(c => c.k === rs.dataset.c).w;
      applyLogCols(); saveState();
    });
    V.head.addEventListener('contextmenu', e => { e.preventDefault(); logColMenu(e.clientX, e.clientY); });
    // the commit message / multi-selection summary: select, copy, Ctrl+F
    readable(V.msg, () => V.detail ? [
      { label: 'Copy Commit Message', run: () => copy(V.detail.body, 'commit message') },
      { label: 'Copy Revision Number', run: () => copy(V.detail.h, 'revision') },
    ] : []);
    readable(V.sum);
    V.list.addEventListener('scroll', () => requestAnimationFrame(V.paint));
    new ResizeObserver(() => V.paint()).observe(V.list);
    // Ctrl+click: toggle · Shift+click: range from the anchor (Ctrl+Shift: added) · right-click keeps a multi-selection
    V.list.addEventListener('mousedown', e => {
      const r = e.target.closest('.gl-row');
      if (!r) return;
      const i = +r.dataset.i, ctrl = e.ctrlKey || e.metaKey;
      if (e.button === 2) { if (!V.isSel(i)) V.select(i); return; }
      if (e.button !== 0) return;
      if (e.shiftKey) { e.preventDefault(); V.selectRange(V.anchor >= 0 ? V.anchor : i, i, ctrl); }
      else if (ctrl) V.toggleSel(i);
      else V.select(i);
    });
    V.list.addEventListener('dblclick', e => {
      const r = e.target.closest('.gl-row');
      if (r && opts.history) V.historyDiff(+r.dataset.i);
    });
    V.list.addEventListener('contextmenu', e => {
      const r = e.target.closest('.gl-row');
      if (!r) return;
      e.preventDefault();
      if (!V.isSel(+r.dataset.i)) V.select(+r.dataset.i);
      V.commitMenu(e, V.rows[+r.dataset.i].c);
    });
    V.list.addEventListener('keydown', e => {
      const page_ = Math.max(1, Math.floor(V.list.clientHeight / ROW_H) - 1);
      const mv = { ArrowDown: 1, ArrowUp: -1, PageDown: page_, PageUp: -page_, Home: -1e9, End: 1e9 }[e.key];
      if (mv != null) {
        e.preventDefault();
        const to = Math.max(0, Math.min(V.rows.length - 1, V.selIdx + mv));
        if (e.shiftKey && V.selIdx >= 0) V.selectRange(V.anchor >= 0 ? V.anchor : V.selIdx, to, false, true);
        else V.select(to, true);
      }
      else if (e.key === 'a' && (e.ctrlKey || e.metaKey) && V.rows.length) { e.preventDefault(); V.selectRange(0, V.rows.length - 1, false, false, V.selIdx >= 0 ? V.selIdx : 0); }
      else if (e.key === 'c' && e.ctrlKey && V.selH.size) { e.preventDefault(); V.copyHashes(); }
      else if (e.key === 'Enter' && opts.history && V.selIdx >= 0) { e.preventDefault(); V.historyDiff(V.selIdx); }
    });
    let qt = null;
    V.q.addEventListener('input', () => { clearTimeout(qt); qt = setTimeout(() => { V.filters.text = V.q.value.trim(); V.reload(false, true); }, 350); });
    V.q.addEventListener('keydown', e => { if (e.key === 'Enter') { clearTimeout(qt); V.filters.text = V.q.value.trim(); V.reload(false, true); }
      if (e.key === 'ArrowDown') { e.preventDefault(); V.list.focus(); if (V.selIdx < 0) V.select(0, true); } });
    page.querySelector('.gl-filter').addEventListener('click', e => { const b = e.target.closest('.fb'); if (b) V.filterMenu(b); });
    page.querySelectorAll('.gw-vsash').forEach(sh => sh.addEventListener('mousedown', ev => {
      ev.preventDefault();
      const which = sh.dataset.s, panel = which === 'bw' ? page.querySelector('.gl-branches') : page.querySelector('.gl-details');
      const x0 = ev.clientX, w0 = panel.getBoundingClientRect().width;
      sh.classList.add('drag');
      const mv = e2 => { const w = which === 'bw' ? w0 + e2.clientX - x0 : w0 - (e2.clientX - x0); panel.style.width = Math.max(140, Math.min(innerWidth * 0.6, w)) + 'px'; };
      const up = () => { sh.classList.remove('drag'); removeEventListener('mousemove', mv); removeEventListener('mouseup', up);
        S()[which] = Math.round(panel.getBoundingClientRect().width); saveState(); };
      addEventListener('mousemove', mv); addEventListener('mouseup', up);
    }));
    if (V.branchTree) {
      V.bcollapsed = new Set(['tags']);
      page.querySelector('.gb-filter').addEventListener('input', () => V.renderBranches());
      V.branchTree.addEventListener('click', e => V.branchClick(e));
      V.branchTree.addEventListener('contextmenu', e => V.branchClick(e, true));
    }
    V.built = true;
    V.syncFilterButtons();
  };
  V.syncFilterButtons = () => {
    const f = V.filters, set = (k, on, label) => { const b = page.querySelector(`.fb[data-f="${k}"]`); if (b) { b.classList.toggle('set', !!on); if (label != null) b.textContent = label; } };
    set('regex', f.regex); set('case', f.case);
    set('ref', f.ref.length, f.ref.length ? 'Branch: ' + f.ref.map(r => r.replace(/^refs\/(heads|remotes|tags)\//, '')).join(', ') + ' ▾' : 'Branch ▾');
    set('author', f.author.length, f.author.length ? 'User: ' + f.author.join(', ') + ' ▾' : 'User ▾');
    set('date', f.since || f.until, f.since || f.until ? `Date: ${f.since || '…'} – ${f.until || '…'} ▾` : 'Date ▾');
    set('path', f.path.length, f.path.length ? 'Paths: ' + f.path.join(', ') + ' ▾' : 'Paths ▾');
    if (V.q && V.q.value !== f.text && document.activeElement !== V.q) V.q.value = f.text;
  };
  V.filterMenu = async b => {
    const f = V.filters, k = b.dataset.f;
    if (k === 'regex' || k === 'case') { f[k] = !f[k]; V.syncFilterButtons(); if (f.text) V.reload(false, true); return; }
    if (k === 'reload') { await loadRefs(); return V.reload(true); }
    if (k === 'ref') {
      const refs = G.refs || await loadRefs() || { local: [], remote: [], tags: [] };
      const items = [{ value: 'HEAD', label: 'HEAD (current branch)' }, { header: true, label: 'Local' }]
        .concat(refs.local.map(x => ({ value: x.ref, label: x.name, hint: x.current ? 'current' : '' })), [{ header: true, label: 'Remote' }],
          refs.remote.map(x => ({ value: x.ref, label: x.name })), [{ header: true, label: 'Tags' }], refs.tags.map(x => ({ value: x.ref, label: x.name })));
      return pickList(b, items, { multi: true, selected: f.ref, placeholder: 'branches… (Enter: apply)', onPick: v => { f.ref = v; V.syncFilterButtons(); V.reload(false, true); } });
    }
    if (k === 'author') {
      const d = await api('authors', { repo: G.repo.root });
      const me = (G.refs && G.refs.user) || '';
      const items = (d.authors || []).map(a => ({ value: a, label: a, hint: a === me ? 'me' : '' }));
      return pickList(b, items, { multi: true, selected: f.author, placeholder: 'users… (Enter: apply)', onPick: v => { f.author = v; V.syncFilterButtons(); V.reload(false, true); } });
    }
    if (k === 'date') {
      const day = n => { const d = new Date(Date.now() - n * 864e5); return d.toISOString().slice(0, 10); };
      const items = [{ value: '', label: 'All' }, { value: day(1) + '|', label: 'Last 24 hours' }, { value: day(7) + '|', label: 'Last 7 days' },
        { value: day(30) + '|', label: 'Last 30 days' }, { value: day(365) + '|', label: 'Last year' }];
      return pickList(b, items, { placeholder: 'or type YYYY-MM-DD..YYYY-MM-DD, Enter', onPick: v => {
        [f.since, f.until] = (v || '|').split('|'); V.syncFilterButtons(); V.reload(false, true); },
      onText: t => {
        const m = t.match(/^(\d{4}-\d{2}-\d{2})?\s*(?:\.\.|–|-|~)?\s*(\d{4}-\d{2}-\d{2})?$/);
        if (!m) return showToast('dates as YYYY-MM-DD..YYYY-MM-DD', true);
        f.since = m[1] || ''; f.until = m[2] || ''; V.syncFilterButtons(); V.reload(false, true); } });
    }
    if (k === 'path') {
      const doc = currentDoc();
      const items = [{ value: '', label: '(all paths)' }];
      if (doc) {
        const inf = await api('info', { path: doc.key });
        if (inf.repo && inf.repo.root === G.repo.root && inf.rel) {
          items.push({ value: inf.rel, label: inf.rel, hint: 'current file' });
          if (dirOf(inf.rel)) items.push({ value: dirOf(inf.rel), label: dirOf(inf.rel) + '/', hint: 'its folder' });
        }
      }
      f.path.forEach(p => items.push({ value: p, label: p, hint: 'in filter' }));
      return pickList(b, items, { placeholder: 'type a repository path, Enter', empty: 'type a path relative to the repository and press Enter',
        onPick: v => { f.path = v ? [v] : []; V.syncFilterButtons(); V.reload(false, true); },
        onText: t => { f.path = t.split(',').map(s => s.trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')).filter(Boolean); V.syncFilterButtons(); V.reload(false, true); } });
    }
  };
  V.params = (offset, n, reload) => {
    const f = V.filters;
    return Object.assign({ repo: G.repo.root, offset, n, reload: reload ? 1 : 0, text: f.text, regex: f.regex, case: f.case,
      ref: f.ref, author: f.author, since: f.since, until: f.until, path: f.path }, opts.history ? { follow: 1 } : {});
  };
  V.show = async () => {
    if (!V.built) V.build();
    if (!V.loaded || V.stale) await V.reload(V.stale);
    else V.paint();
    if (V.branchTree && !G.refs) { await loadRefs(); }
    if (V.branchTree) V.renderBranches();
  };
  // keep: re-select the same commit and scroll position (refresh after a change)
  V.reload = async (fromServer, filterChange) => {
    if (!V.built || !G.repo) return;
    const gen = ++V.gen;
    const keepHash = !filterChange && V.selIdx >= 0 && V.rows[V.selIdx] ? V.rows[V.selIdx].c.h : null;
    const keepSet = !filterChange && V.selH.size > 1 ? [...V.selH] : null;
    const keepTop = filterChange ? 0 : V.list.scrollTop;
    V.loading = true; V.stale = false;
    V.cnt.textContent = 'loading…';
    const d = await api('log', V.params(0, 300, true), opts.history ? 'history' : 'log');
    if (gen !== V.gen || d.aborted) return;
    V.loading = false;
    V.rows = []; V.lane = { lanes: [], colors: [], next: 0 }; V.selIdx = -1; V.selH = new Set(); V.anchor = -1;
    if (d.error) { V.cnt.textContent = ''; V.rowsEl.style.height = '0px'; V.rowsEl.innerHTML = `<div class="gw-empty">${esc(errText(d))}</div>`; return; }
    V.graph = !opts.history && V.graphOn() && !d.hash_hit;
    V.append(d);
    V.loaded = true;
    if (G.refs && V.branchTree) V.renderBranches();
    V.list.scrollTop = keepTop;
    let idx = keepHash ? V.rows.findIndex(r => r.c.h === keepHash) : -1;
    if (idx < 0 && (d.hash_hit || opts.history)) idx = 0;
    if (V.pendingSelect) { const j = V.rows.findIndex(r => r.c.h.startsWith(V.pendingSelect)); if (j >= 0) idx = j; V.pendingSelect = null; }
    const keepIdx = keepSet ? keepSet.map(h => V.rows.findIndex(r => r.c.h === h)).filter(j => j >= 0) : [];
    if (keepIdx.length > 1) V.setSel(keepIdx, idx >= 0 ? idx : keepIdx[0], false);
    else if (idx >= 0) V.select(idx, true); else { V.paint(); V.clearDetail(); }
  };
  V.append = d => {
    for (const c of d.commits) V.rows.push({ c, g: laneStep(V.lane, c, V.graph) });
    V.hasMore = d.has_more;
    V.cnt.textContent = `${V.rows.length}${V.hasMore ? '+' : ''} commit${V.rows.length === 1 ? '' : 's'}` + (d.ms > 1500 && V.rows.length <= 300 ? ` · ${d.ms} ms` : '');
    V.rowsEl.style.height = (V.rows.length + (V.hasMore ? 1 : 0)) * ROW_H + 'px';
  };
  V.more = async () => {
    if (V.loading || !V.hasMore) return;
    V.loading = true;
    const gen = V.gen;
    const d = await api('log', V.params(V.rows.length, 500, false), opts.history ? 'history' : 'log');
    V.loading = false;
    if (gen !== V.gen || d.error) return;
    V.append(d);
    V.paint();
  };
  V.paint = () => {
    if (!V.built || !V.list.clientHeight) return;
    V.head.style.paddingRight = (V.list.offsetWidth - V.list.clientWidth) + 'px';  // header columns line up past the scrollbar
    layoutLogCols(V.head.parentNode);
    const top = V.list.scrollTop, h = V.list.clientHeight;
    const first = Math.max(0, Math.floor(top / ROW_H) - 8), last = Math.min(V.rows.length, Math.ceil((top + h) / ROW_H) + 8);
    const me = G.refs && G.refs.user;
    let s = '';
    for (let i = first; i < last; i++) {
      const { c, g } = V.rows[i];
      const merge = c.p.length > 1;
      s += `<div class="gl-row${V.selH.has(c.h) ? ' sel' : ''}${i === V.selIdx && V.selH.size > 1 ? ' lead' : ''}${merge ? ' merge' : ''}${me && c.an === me ? ' mine' : ''}" data-i="${i}" style="top:${i * ROW_H}px" title="${esc(short(c.h) + ' ' + c.an + ' ' + fullDate(c.at))}">` +
        graphSvg(g, c, V.graph) + `<span class="msg">${refChips(c.refs)}<span class="s">${esc(c.s)}</span>${opts.history && c.path_at ? ` <span class="dim" style="color:var(--text-mute)">${esc(c.path_from && c.fs === 'R' ? c.path_from + ' → ' + c.path_at : '')}</span>` : ''}</span>` +
        `<span class="au">${esc(c.an)}</span><span class="dt">${esc(fmtDate(c.at))}</span><span class="hs">${esc(short(c.h))}</span></div>`;
    }
    if (V.hasMore && last >= V.rows.length) s += `<div class="gl-more" style="top:${V.rows.length * ROW_H}px">loading more…</div>`;
    if (!V.rows.length) s = `<div class="gw-empty">${V.loading ? 'loading…' : 'no commits match'}</div>`;
    V.rowsEl.innerHTML = s;
    if (V.hasMore && last >= V.rows.length - 60) V.more();
  };
  // ----- selection: one commit (details as before) or several (their files merged) -----
  V.isSel = i => !!V.rows[i] && V.selH.has(V.rows[i].c.h);
  V.select = (i, reveal) => { if (i >= 0 && i < V.rows.length) { V.anchor = i; V.setSel([i], i, reveal); } };
  V.toggleSel = i => {
    if (!V.rows[i]) return;
    const h = V.rows[i].c.h, set = new Set(V.selH);
    if (set.has(h) && set.size > 1) set.delete(h); else set.add(h);
    V.anchor = i;
    const idx = V.rows.map((r, j) => set.has(r.c.h) ? j : -1).filter(j => j >= 0);
    V.setSel(idx, set.has(h) ? i : idx[0], false);
  };
  // rows a..b (either order); add: keep the current selection too; keepAnchor: Shift+arrows
  V.selectRange = (a, b, add, reveal, lead) => {
    const lo = Math.min(a, b), hi = Math.max(a, b), idx = [];
    for (let j = lo; j <= hi; j++) idx.push(j);
    if (add) V.rows.forEach((r, j) => { if (V.selH.has(r.c.h) && (j < lo || j > hi)) idx.push(j); });
    V.anchor = a;
    V.setSel(idx, lead != null ? lead : b, reveal);
  };
  V.setSel = (idx, lead, reveal) => {
    V.selH = new Set(idx.map(j => V.rows[j].c.h));
    V.selIdx = lead;
    if (reveal) {
      const t = lead * ROW_H, b = t + ROW_H;
      if (t < V.list.scrollTop) V.list.scrollTop = t;
      else if (b > V.list.scrollTop + V.list.clientHeight) V.list.scrollTop = b - V.list.clientHeight;
    }
    const multi = V.selH.size > 1;
    V.rowsEl.querySelectorAll('.gl-row').forEach(r => {
      const j = +r.dataset.i;
      r.classList.toggle('sel', V.isSel(j)); r.classList.toggle('lead', multi && j === lead);
    });
    if (!V.rowsEl.querySelector(`.gl-row[data-i="${lead}"]`)) V.paint();
    clearTimeout(V._dt);
    V._dt = setTimeout(() => multi ? V.loadMulti() : V.loadDetail(V.rows[lead].c), multi ? 150 : 90);
  };
  V.selected = () => V.rows.filter(r => V.selH.has(r.c.h)).map(r => r.c);  // newest first, as listed
  V.copyHashes = () => {
    const cs = V.selected();
    if (cs.length === 1) return copy(cs[0].h, 'revision');
    copy(cs.map(c => c.h).join('\n'), cs.length + ' revisions');
  };
  V.clearDetail = () => { V.detail = null; V.multi = null; V.sum.style.display = 'none'; V.files.set([]); V.msg.innerHTML = ''; };
  // several commits: one request; a contiguous range is diffed base..newest, otherwise the files of each are merged
  V.loadMulti = async () => {
    const cs = V.selected(), gen = V._mg = (V._mg || 0) + 1, repo = G.repo;
    if (cs.length < 2) return;
    V.detail = null; V.multi = { loading: true, n: cs.length };
    V.sum.style.display = 'block';
    V.sum.innerHTML = `<b>${cs.length} commits selected</b> <span class="dim">loading files…</span>`;
    V.files.set([]); V.msg.innerHTML = '';
    const r = await postJson('/api/git/commits', { repo: repo.root, revs: cs.map(c => c.h) });
    if (gen !== V._mg) return;  // the selection changed meanwhile
    const d = r.data || {};
    if (!r.ok || d.error) {
      V.multi = null; V.files.set([]);
      V.sum.innerHTML = `<b>${cs.length} commits selected</b> <span class="err">${esc(d.error ? errText(d) : 'HTTP ' + r.status)}</span>`;
      return;
    }
    V.multi = Object.assign(d, { repo, cs });
    const files = d.files.map(f => ({ path: f.path, orig: f.orig, st: f.status, cls: 'k-' + f.status, add: f.binary ? null : f.add, del: f.del,
      binary: f.binary, tag: f.n > 1 ? f.n + ' commits' : '', raw: f }));
    V.files.set([{ id: 'c', label: '', files }]);
    const b = d.base ? short(d.base) : '(empty)', h = short(d.head);
    V.sum.innerHTML = `<b>${d.n} commits selected</b> · ${d.files.length}${d.truncated ? '+' : ''} file${d.files.length === 1 ? '' : 's'}` +
      (d.range ? ` <span class="dim">· one range: changes ${esc(b)} → ${esc(h)}</span>`
        : `<div class="note">not one range: files changed in any of them${d.partial ? ` (the newest ${d.n - d.partial}; ${d.partial} more not listed)` : ''}. ` +
          `A file's diff compares ${esc(b)} (parent of the oldest) with ${esc(h)} (the newest), so it can include commits in between that are not selected.</div>`);
    const list = cs.slice(0, 200);
    V.msg.innerHTML = list.map(c => `<div class="mc"><a data-h="${esc(c.h)}">${esc(short(c.h))}</a> ${esc(c.s)} <span class="dim">${esc(c.an)}</span></div>`).join('') +
      (cs.length > list.length ? `<div class="dim">… ${cs.length - list.length} more</div>` : '') +
      `<div class="meta"><a data-copy="1">copy ${cs.length} hashes</a></div>`;
    V.msg.onclick = e => {
      const t = e.target.dataset || {};
      if (t.copy) V.copyHashes();
      if (t.h) { const j = V.rows.findIndex(r => r.c.h === t.h); if (j >= 0) V.select(j, true); }
    };
  };
  // a changed file of the selection: what its diff compares
  V.fileTarget = f => {
    const m = V.multi;
    if (!m) return { c: V.detail, f, ident: 'C:' + V.detail.h };
    const c = { h: m.head, parent: m.base, p: m.base ? [m.base] : [] };
    // union: the file as it differs between base and newest ("" = same content: both sides shown)
    const g = m.range ? f : { path: f.path, orig: f.bh_orig, status: f.bh || 'M' };
    return { c, f: g, ident: 'M:' + (m.base || '') + '..' + m.head, multi: m };
  };
  V.fileDiff = row => {
    const repo = G.repo;
    if (!V.detail && !(V.multi && V.multi.files)) return;
    const t0 = V.fileTarget(row.file.raw), label = t0.multi ? `${t0.multi.base ? short(t0.multi.base) : '(empty)'}..${short(t0.multi.head)}` : null;
    const spec = x => { const t = V.fileTarget(x.raw); return specCommit(repo, t.c, t.f).then(s => label ? Object.assign(s, { hash: label, sub: s.sub + `  ·  ${t.multi.n} commits` }) : s); };
    const desc = x => { const t = V.fileTarget(x.raw), d = descCommit(repo, t.c, t.f);
      if (label) Object.assign(d, { ident: t.ident + '|' + x.path, hash: label, title: `${baseName(x.path)} · ${label}`, sub: d.sub + `  ·  ${t.multi.n} commits` });
      return d; };
    openTreeDiff(V.files, row, spec, t0.ident, desc, repo);
  };
  V.loadDetail = async c => {
    V.multi = null; V.sum.style.display = 'none'; V._mg = (V._mg || 0) + 1;  // a late multi answer is dropped
    const d = await api('commit', { repo: G.repo.root, rev: c.h }, opts.history ? 'hcommit' : 'commit');
    if (d.aborted || V.selH.size > 1) return;
    if (d.error) { V.msg.textContent = errText(d); V.files.set([]); return; }
    V.detail = d;
    const files = d.files.map(f => ({ path: f.path, orig: f.orig, st: f.status, cls: 'k-' + f.status, add: f.binary ? null : f.add, del: f.del, binary: f.binary, raw: f }));
    V.files.set([{ id: 'c', label: '', files }]);
    if (opts.history && c.path_at) {
      const id = 'c|' + c.path_at;
      if (V.files.rows.some(r => r.id === id)) { V.files.sel = id; V.files.set(V.files.groups, true); }
    }
    const lines = d.body.split('\n');
    const subj = lines.shift();
    const people = d.an === d.cn ? `${esc(d.an)} &lt;${esc(d.ae)}&gt; on ${esc(fullDate(d.at))}`
      : `${esc(d.an)} &lt;${esc(d.ae)}&gt; on ${esc(fullDate(d.at))}<br>committed by ${esc(d.cn)} on ${esc(fullDate(d.ct))}`;
    V.msg.innerHTML = `<div class="subj">${esc(subj)}</div>${esc(lines.join('\n'))}<div class="meta">${esc(short(d.h))} ${people}` +
      (d.refs.length ? `<br>${refChips(d.refs)}` : '') +
      (d.p.length ? `<br>parent${d.p.length > 1 ? 's' : ''}: ${d.p.map(p => `<a data-h="${esc(p)}">${esc(short(p))}</a>`).join(' ')}` : '<br>(root commit)') +
      `<br><a data-copy="${esc(d.h)}">copy hash</a>${d.truncated ? ' · file list cut at 3000' : ''}</div>`;
    V.msg.onclick = e => {
      const h = e.target.dataset && e.target.dataset.h, cp = e.target.dataset && e.target.dataset.copy;
      if (cp) copy(cp, 'revision');
      if (h) { const j = V.rows.findIndex(r => r.c.h === h); if (j >= 0) V.select(j, true); else showToast('parent is not in the loaded list (filters)', true); }
    };
  };
  V.historyDiff = i => {
    if (!V.rows[i]) return;
    const repo = G.repo;
    const pathAt = c => c.path_at || V.filters.path[0];
    const at = r => [{ h: r.c.h, p: r.c.p, parent: r.c.p[0] },
      { path: pathAt(r.c), orig: r.c.path_from && r.c.fs === 'R' ? r.c.path_from : null, status: r.c.fs || 'M' }];
    openDiffWin(V.rows, i, r => specCommit(repo, ...at(r)),
      { ident: r => 'C:' + r.c.h + '|' + pathAt(r.c), onShow: (r, j) => V.select(j, true), focus: V.list, repo, desc: r => descCommit(repo, ...at(r)) });
  };
  V.fileMenu = (e, f, row) => {
    const key = keyFor(G.repo, f.path);
    showMenu(e.clientX, e.clientY, [
      { label: 'Show Diff', hint: 'click / Enter', run: () => V.fileDiff(row) },
      { label: 'Open Current Version', disabled: !key || f.status === 'D', run: () => openFile(key) },
      { label: 'Show History', run: () => openHistory(G.repo, f.path) },
      { label: 'Copy Path', run: () => copy(f.path, 'path') },
    ]);
  };
  V.commitMenu = (e, c) => {
    const b = (G.status && G.status.branch) || {};
    const n = V.selH.size;
    if (n > 1) {  // several commits: only what applies to all of them
      const cs = V.selected();
      return showMenu(e.clientX, e.clientY, [
        { label: `Copy Revision Numbers (${n})`, hint: 'Ctrl+C', run: () => V.copyHashes() },
        { label: `Copy Subjects (${n})`, run: () => copy(cs.map(x => x.s).join('\n'), n + ' subjects') },
        ...(opts.history ? [{ label: 'Show Diff', disabled: true, run: () => {} }] : []),
        { label: 'Show in Log', disabled: true, run: () => {} },
        'sep',
        ...['Checkout Revision… (AgentO)', 'New Branch from Here… (AgentO)', 'Cherry-Pick… (AgentO)', 'Revert Commit… (AgentO)',
          `Reset ${b.head || 'Current Branch'} to Here… (AgentO)`].map(label => ({ label, disabled: true, run: () => {} })),
      ]);
    }
    showMenu(e.clientX, e.clientY, [
      { label: 'Copy Revision Number', hint: 'Ctrl+C', run: () => copy(c.h, 'revision') },
      { label: 'Copy Subject', run: () => copy(c.s, 'subject') },
      ...(opts.history ? [{ label: 'Show Diff', hint: 'Enter', run: () => V.historyDiff(V.selIdx) }] : []),
      { label: 'Show in Log', disabled: !opts.history, run: () => { setTab('log'); Log.reveal(c.h); } },
      'sep',
      { label: 'Checkout Revision… (AgentO)', run: () => agentDialog('checkoutRev', c) },
      { label: 'New Branch from Here… (AgentO)', run: () => agentDialog('newBranch', { from: `커밋 ${short(c.h)} (${c.s})` }) },
      { label: 'Cherry-Pick… (AgentO)', run: () => agentDialog('cherryPick', c) },
      { label: 'Revert Commit… (AgentO)', run: () => agentDialog('revert', c) },
      { label: `Reset ${b.head || 'Current Branch'} to Here… (AgentO)`, run: () => agentDialog('reset', c) },
    ]);
  };
  V.reveal = h => {
    const j = V.rows.findIndex(r => r.c.h.startsWith(h));
    if (j >= 0) return V.select(j, true);
    V.pendingSelect = h;
    V.filters.text = h.slice(0, 12); V.syncFilterButtons();
    V.reload(false, true);
  };
  // branch tree: HEAD / Local / Remote / Tags, folders by "/"
  V.renderBranches = () => {
    if (!V.branchTree) return;
    const refs = G.refs;
    if (!refs) { V.branchTree.innerHTML = '<div class="gw-empty">loading…</div>'; return; }
    const t = (page.querySelector('.gb-filter').value || '').trim().toLowerCase();
    const sel = new Set(V.filters.ref);
    const out = [];
    const row = (id, depth, html, attrs) => out.push(`<div class="gb-row${attrs && attrs.ref && sel.has(attrs.ref) ? ' sel' : ''}${attrs && attrs.sec ? ' sec' : ''}" data-id="${esc(id)}"${attrs && attrs.ref ? ` data-ref="${esc(attrs.ref)}"` : ''} style="padding-left:${depth * 14 + 4}px">${html}</div>`);
    const b = (G.status && G.status.branch) || {};
    row('head', 0, `<span class="tw"></span><span class="nm">HEAD (${esc(refs.head ? 'Current Branch' : 'detached ' + short(refs.head_sha))})</span>`, { ref: 'HEAD', sec: true });
    const section = (id, label, list, nameOf, extra) => {
      const items = list.filter(x => !t || nameOf(x).toLowerCase().includes(t));
      if (t && !items.length) return;
      const open = t || !V.bcollapsed.has(id);
      row(id, 0, `<span class="tw">${open ? '▾' : '▸'}</span><span class="nm">${esc(label)}</span><span class="ab">${items.length}</span>`, { sec: true });
      if (!open) return;
      const tree = { dirs: new Map(), items: [] };
      for (const x of items) {
        const parts = nameOf(x).split('/');
        let n = tree;
        for (const p of parts.slice(0, -1)) { if (!n.dirs.has(p)) n.dirs.set(p, { dirs: new Map(), items: [] }); n = n.dirs.get(p); }
        n.items.push(x);
      }
      const walk = (n, depth, path) => {
        for (const [name, d] of [...n.dirs.entries()].sort((a, c) => a[0].localeCompare(c[0]))) {
          const fid = id + ':' + path + name;
          const o = t || !V.bcollapsed.has(fid);
          row(fid, depth, `<span class="tw">${o ? '▾' : '▸'}</span>${FOLDER_SVG}<span class="nm">${esc(name)}</span>`);
          if (o) walk(d, depth + 1, path + name + '/');
        }
        for (const x of n.items.sort((a, c) => nameOf(a).localeCompare(nameOf(c)))) row('r:' + x.ref, depth, `<span class="tw"></span>${extra(x)}<span class="nm">${esc(nameOf(x).split('/').pop())}</span>` +
          (x.ahead || x.behind ? `<span class="ab">↑${x.ahead} ↓${x.behind}</span>` : '') + (x.gone ? '<span class="ab">gone</span>' : ''), { ref: x.ref });
      };
      walk(tree, 1, '');
    };
    const star = x => x.current || (b.upstream && x.name === b.upstream) ? '<span class="cur">★</span>' : '';
    section('local', 'Local', refs.local, x => x.name, star);
    section('remote', 'Remote', refs.remote, x => x.name, star);
    section('tags', 'Tags', refs.tags, x => x.name, () => '');
    V.branchTree.innerHTML = out.join('');
  };
  V.branchClick = (e, menu) => {
    const r = e.target.closest('.gb-row');
    if (!r) return;
    const ref = r.dataset.ref;
    if (!ref) {
      if (menu) return;
      V.bcollapsed.has(r.dataset.id) ? V.bcollapsed.delete(r.dataset.id) : V.bcollapsed.add(r.dataset.id);
      return V.renderBranches();
    }
    if (menu) { e.preventDefault(); return branchMenu(e.clientX, e.clientY, ref, V); }
    V.filters.ref = V.filters.ref.length === 1 && V.filters.ref[0] === ref ? [] : [ref];
    V.syncFilterButtons(); V.renderBranches(); V.reload(false, true);
  };
  return V;
}
function refName(ref) { return ref.replace(/^refs\/(heads|remotes|tags)\//, ''); }
function branchMenu(x, y, ref, view) {
  const b = (G.status && G.status.branch) || {};
  const name = refName(ref), local = ref.startsWith('refs/heads/'), isCur = local && name === b.head;
  showMenu(x, y, [
    { label: 'Show in Log', run: () => { setTab('log'); Log.filters.ref = [ref]; Log.syncFilterButtons(); Log.reload(false, true); } },
    { label: 'Copy Name', run: () => copy(name, 'name') },
    'sep',
    { label: `Checkout ${name}`, disabled: isCur || !/^refs\/(heads|remotes)\//.test(ref), run: () => gitCheckout(G.repo, ref) },
    { label: `New Branch from ${name}… (AgentO)`, run: () => agentDialog('newBranch', { from: name }) },
    { label: `Merge ${name} into ${b.head || 'Current'}… (AgentO)`, disabled: isCur || ref === 'HEAD', run: () => agentDialog('merge', { ref: name, branch: b.head }) },
    { label: `Rebase ${b.head || 'Current'} onto ${name}… (AgentO)`, disabled: isCur || ref === 'HEAD', run: () => agentDialog('rebase', { ref: name, branch: b.head }) },
    ...(local ? [{ label: `Push ${name}… (AgentO)`, run: () => agentDialog('push', { branch: name }) },
                 { label: `Delete ${name}… (AgentO)`, disabled: isCur, run: () => agentDialog('deleteBranch', { ref: name }) }] : []),
  ]);
}

let Log = null, History = null;
function openHistory(repo, path) {
  if (!repo) return;
  if (!W) buildWindow();
  if (G.repo !== repo && (!G.repo || G.repo.root !== repo.root)) selectRepo(repo.root, true);
  const tab = W.head.querySelector('.gw-tab[data-tab="history"]');
  tab.style.display = '';
  tab.innerHTML = `History: ${esc(path.split('/').pop())}<span class="x" title="close">×</span>`;
  tab.title = path;
  History = LogView(W.pages.history, { history: true, filters: { path: [path] } });
  W.pages.history.innerHTML = '';
  STATE.git.open = true; STATE.git.tab = 'history'; W.gw.classList.add('show'); saveState();
  start();
}
function closeHistory(quiet) {
  if (!W) return;
  const tab = W.head.querySelector('.gw-tab[data-tab="history"]');
  tab.style.display = 'none';
  W.pages.history.innerHTML = '';
  History = null;
  if (!quiet && STATE.git.tab === 'history') setTab('log');
}

// ---------- Stash (read only) ----------
const Stash = {
  built: false, items: [], sel: -1,
  reset() { this.built = false; if (W) W.pages.stash.innerHTML = ''; },
  build() {
    const p = W.pages.stash;
    p.innerHTML = `<div class="gw-col" style="width:45%"><div class="gw-bar"><button data-a="refresh">⟳</button>
      <button data-a="push" class="agent" title="ask AgentO to stash the local changes">Stash Changes… (AgentO)</button><span class="sum"></span></div>
      <div class="gw-scroll st-list" tabindex="0"></div></div><div class="gw-vsash"></div>
      <div class="gw-col" style="flex:1"><div class="gw-scroll st-files"></div></div>`;
    this.list = p.querySelector('.st-list');
    this.files = FileTree(p.querySelector('.st-files'), { showGroups: false, empty: 'select a stash',
      onFile: row => { const repo = G.repo, det = this.detail; if (det) openTreeDiff(this.files, row, f => specCommit(repo, det, f.raw), 'C:' + det.h, f => descCommit(repo, det, f.raw), repo); } });
    p.querySelector('.gw-bar').addEventListener('click', e => {
      if (e.target.dataset.a === 'refresh') this.load();
      if (e.target.dataset.a === 'push') agentDialog('stashPush');
    });
    this.list.addEventListener('click', e => { const r = e.target.closest('.gt-row'); if (r) this.select(+r.dataset.i); });
    this.list.addEventListener('contextmenu', e => {
      const r = e.target.closest('.gt-row'); if (!r) return;
      e.preventDefault(); this.select(+r.dataset.i);
      const s = this.items[+r.dataset.i];
      showMenu(e.clientX, e.clientY, [
        { label: 'Apply… (AgentO)', run: () => agentDialog('stashApply', s) },
        { label: 'Pop… (AgentO)', run: () => agentDialog('stashPop', s) },
        { label: 'Drop… (AgentO)', run: () => agentDialog('stashDrop', s) },
        'sep', { label: 'Copy Hash', run: () => copy(s.h, 'revision') },
        { label: 'Copy Message', run: () => copy(s.s, 'stash message') },
      ]);
    });
    this.built = true;
  },
  async show() { if (!this.built) this.build(); await this.load(); },
  async load() {
    if (!this.built || !G.repo) return;
    const d = await api('stash', { repo: G.repo.root }, 'stash');
    if (d.aborted) return;
    this.items = d.items || [];
    W.pages.stash.querySelector('.sum').textContent = d.error ? errText(d) : `${this.items.length} stash${this.items.length === 1 ? '' : 'es'} · read only`;
    this.list.innerHTML = this.items.map((s, i) => `<div class="gt-row${i === this.sel ? ' sel' : ''}" data-i="${i}" style="padding-left:8px"><span class="nm">${esc(s.name)}</span><span class="dim">${esc(s.s)}</span><span class="num">${esc(fmtDate(s.at))}</span></div>`).join('') ||
      '<div class="gw-empty">no stashes</div>';
    if (this.sel >= this.items.length) this.sel = -1;
  },
  async select(i) {
    this.sel = i;
    this.list.querySelectorAll('.gt-row').forEach(r => r.classList.toggle('sel', +r.dataset.i === i));
    const s = this.items[i];
    const d = await api('commit', { repo: G.repo.root, rev: s.h }, 'scommit');
    if (d.error) return this.files.set([]);
    this.detail = d;
    this.files.set([{ id: 's', label: '', files: d.files.map(f => ({ path: f.path, orig: f.orig, st: f.status, cls: 'k-' + f.status, add: f.add, del: f.del, binary: f.binary, raw: f })) }]);
  },
};

// ---------- Console (git commands ReadO ran) ----------
const Console_ = {
  built: false, entries: [], since: 0, timer: null,
  build() {
    const p = W.pages.console;
    p.innerHTML = `<div class="gw-col" style="flex:1"><div class="gw-bar"><button data-a="clear">clear</button><span class="sum">git commands ReadO ran (newest last) — all read-only except Pull, Fetch and Checkout</span></div><div class="gw-scroll"></div></div>`;
    this.box = p.querySelector('.gw-scroll');
    p.querySelector('.gw-bar').addEventListener('click', e => { if (e.target.dataset.a === 'clear') { this.entries = []; this.render(); } });
    readable(this.box, e => {
      const en = this.entry(e.target.closest('.gc-row'));
      return (en ? [{ label: 'Copy Command', run: () => copy(en.cmd, 'command') }] : [])
        .concat(en && en.out ? [{ label: 'Copy Output', run: () => copy(en.out, 'output') }] : [])
        .concat([{ label: 'Copy All', run: () => copy(this.entries.map(x => x.cmd + (x.out ? '\n' + x.out : x.err ? '\n' + x.err : '')).join('\n'), 'console') }]);
    });
    this.built = true;
  },
  show() {
    if (!this.built) this.build();
    this.load();
    clearInterval(this.timer);
    this.timer = setInterval(() => { if (STATE.git.open && STATE.git.tab === 'console' && !document.hidden) this.load(); else clearInterval(this.timer); }, 2000);
  },
  async load() {
    const d = await api('console', { since: this.since });
    const fresh = d.entries || [];
    for (const e of fresh) { this.entries.push(e); this.since = Math.max(this.since, e.id); }
    if (this.entries.length > 500) this.entries.splice(0, this.entries.length - 500);
    // new commands are appended, old rows dropped from the top: what the user selected stays selected
    if (!this.box.querySelector('.gc-row')) this.render();
    else if (fresh.length) this.append(fresh);
  },
  rowHtml(e) {
    return `<div class="gc-row${e.rc ? ' err' : ''}" data-id="${e.id}"><span class="t">${esc(new Date(e.t * 1000).toLocaleTimeString())}</span>` +
      `<span class="ms">${e.ms} ms</span><span class="c" title="${esc(e.cwd)}">${esc(e.cmd)}</span>${e.err && !e.out ? `<span class="e">${esc(e.err)}</span>` : ''}` +
      `${e.out ? `<pre class="o">${esc(e.out)}</pre>` : ''}</div>`;
  },
  entry(row) { return row && this.entries.find(x => x.id === +row.dataset.id); },
  append(list) {
    const atEnd = this.box.scrollTop + this.box.clientHeight >= this.box.scrollHeight - 30;
    this.box.insertAdjacentHTML('beforeend', list.map(e => this.rowHtml(e)).join(''));
    const rows = this.box.querySelectorAll('.gc-row');
    for (let i = 0; i < rows.length - this.entries.length; i++) rows[i].remove();
    if (atEnd) this.box.scrollTop = this.box.scrollHeight;
  },
  render() {
    const atEnd = this.box.scrollTop + this.box.clientHeight >= this.box.scrollHeight - 30;
    this.box.innerHTML = this.entries.map(e => this.rowHtml(e)).join('') || '<div class="gw-empty">no git commands yet</div>';
    if (atEnd) this.box.scrollTop = this.box.scrollHeight;
  },
};

// ---------- sidebar tree colours ----------
let _decorBusy = false;
async function refreshDecor() {
  if (_decorBusy || !G.info || !G.info.available || !_settings.base_dir) return;
  _decorBusy = true;
  try {
    const d = await api('decor', { dir: expandedTreeDirs(), eol: S().showEol ? 1 : '' });
    if (d.error) return;
    G.decor = d;
    applyDecor(document.getElementById('tree'));
  } finally { _decorBusy = false; }
}
function applyDecor(root) {
  if (!root) return;
  const nodes = root.matches && root.matches('.node') ? [root] : root.querySelectorAll('.node');
  nodes.forEach(n => {
    const p = n.dataset.path;
    const f = G.decor.files[p], d = n.dataset.dir === '1' ? G.decor.dirs[p] : null;
    const want = (f ? 'gs-' + f : '') + (d ? ' gd-' + d : '');
    if ((n._gcls || '') === want) return;
    n.classList.remove('gs-M', 'gs-A', 'gs-U', 'gs-C', 'gs-R', 'gs-D', 'gd-M', 'gd-C', 'gd-U');
    if (f) n.classList.add('gs-' + f);
    if (d) n.classList.add('gd-' + d);
    n._gcls = want;
  });
}

// ---------- status bar ----------
const _updateBranch = updateBranch;
updateBranch = function () {
  _updateBranch();
  const sb = document.getElementById('sbBranch');
  if (!sb) return;
  const doc = currentDoc();
  const st = G.status && !G.status.error ? G.status : null;
  let txt = sb.textContent;
  if (!txt && st && G.repo) txt = '⎇ ' + (st.branch.head || 'detached ' + short(st.branch.oid));
  if (txt && st && G.repo && st.branch.upstream && (!doc || !doc.gitBranch || doc.gitBranch === st.branch.head) && (st.branch.ahead || st.branch.behind))
    txt += ` ↑${st.branch.ahead} ↓${st.branch.behind}`;
  if (txt && G.repo && G.repo.state) txt += ' · ' + G.repo.state.toUpperCase();
  sb.textContent = txt;
  sb.classList.toggle('gw-link', !!txt);
  const wb = W && W.head.querySelector('[data-a="branch"] .nm');
  if (wb) {
    const b = st ? st.branch : null;
    wb.textContent = !b ? '…' : (b.head || 'detached ' + short(b.oid)) + (b.upstream && (b.ahead || b.behind) ? `  ↑${b.ahead} ↓${b.behind}` : '');
    const pb = W.head.querySelector('[data-a="pull"]');
    pb.title = 'Pull (git pull --ff-only: fast-forward only)' + (b && b.behind ? ` — ↓${b.behind} known` : '') +
      (b && !b.head ? '\n— ' + PULL_WHY.detached : b && !b.upstream ? '\n— ' + PULL_WHY.no_upstream : '');
  }
};
// Branches of a repository (toolbar branch chip, status bar, Git window): the current branch with
// ↑ahead ↓behind, Pull / Fetch, then Local and Remote branches with a filter box — picking one
// checks it out (a remote-only one through a new local tracking branch).
async function branchPopup(anchor, repo) {
  if (!repo) {
    const doc = currentDoc();
    if (doc && doc.gitRepo) {
      const inf = await api('info', { path: doc.key });
      if (inf.repo && (!G.repo || G.repo.root !== inf.repo.root)) await selectRepo(inf.repo.root, true);
    }
    if (!G.repo) { await loadRepos(); if (!G.repo) return showToast('no git repository here', true); }
    repo = G.repo;
  }
  const [refs, st] = await Promise.all([api('refs', { repo: repo.root }), api('status', { repo: repo.root })]);
  if (refs.error) return showToast('branches: ' + errText(refs), true);
  const b = (st && st.branch) || {};
  const tracked = new Map(refs.local.filter(x => x.upstream).map(x => [x.upstream, x.name]));
  const ab = x => (x.ahead || x.behind ? `↑${x.ahead} ↓${x.behind}` : '');
  const cur = b.head ? b.head + (b.upstream ? ` → ${b.upstream}  ↑${b.ahead} ↓${b.behind}` : ' (no upstream)')
    : 'detached HEAD ' + short(b.oid || refs.head_sha || '');
  const state = (st && st.repo && st.repo.state) || '';
  const items = [{ header: true, label: 'Current: ' + cur + (state ? ' · ' + state.toUpperCase() : '') },
    { value: 'act:pull', label: 'Pull (fast-forward only)', hint: b.behind ? `↓${b.behind}` : '' },
    { value: 'act:fetch', label: 'Fetch (--prune)' },
    { value: 'act:log', label: 'Show Log' },
    { value: 'act:newBranch', label: 'New Branch… (AgentO)' },
    { value: 'act:push', label: 'Push… (AgentO)', hint: STATE.keymap === 'intellij' ? 'Ctrl+Shift+K' : '' },
    { header: true, label: 'Local' }].concat(
    refs.local.map(x => ({ value: x.ref, label: x.name, current: x.current, cls: x.current ? 'cur' : '',
      hint: (x.current ? '✓ current  ' : '') + (x.gone ? 'upstream gone  ' : '') + ab(x) })),
    [{ header: true, label: 'Remote' }],
    refs.remote.map(x => ({ value: x.ref, label: x.name, hint: tracked.has(x.name) ? 'local ' + tracked.get(x.name) : 'new local branch' })));
  pickList(anchor, items, { placeholder: `${repo.name}: filter branches…`, empty: 'no branch matches', width: 380, onPick: (v, it) => {
    if (v === 'act:pull') return tbPull(repo);
    if (v === 'act:fetch') return gitFetch(repo);
    if (v === 'act:log') return (async () => { if (!G.repo || G.repo.root !== repo.root) await selectRepo(repo.root, true); openTab('log'); })();
    if (v === 'act:newBranch' || v === 'act:push') return (async () => {
      if (!G.repo || G.repo.root !== repo.root) await selectRepo(repo.root, true);
      if (v === 'act:newBranch') agentDialog('newBranch', {}); else agentDialog('push', { branch: b.head, upstream: b.upstream });
    })();
    if (it.current) return showToast('already on ' + it.label);
    gitCheckout(repo, v);
  } });
}

// ---------- blame in the editor ----------
// "Annotate with Git Blame" (editor / gutter right-click, Git menu, palette): author + date per
// line in the gutter; hover: commit details; click: that commit's changes in the diff modal.
const _blameLoads = new Map();  // doc key -> in-flight /blame (annotations and the line-end hint share it)
function fetchBlame(doc) {
  if (!_blameLoads.has(doc.key)) _blameLoads.set(doc.key, api('blame', { path: doc.key }).finally(() => _blameLoads.delete(doc.key)));
  return _blameLoads.get(doc.key);
}
// IntelliJ look: "M/D/YYYY author" on every line, left of the line numbers; each commit's lines share
// one shade, newer commits darker, the oldest quarter of the file's commits unshaded
const BLAME_W = 160;  // px, the annotation column (fixed)
const mdy = ts => { const d = new Date(ts * 1000); return `${d.getMonth() + 1}/${d.getDate()}/${d.getFullYear()}`; };
function blameStyle(data) {
  const times = [...new Set(data.commits.filter(c => !c.uncommitted).map(c => c.at))].sort((x, y) => x - y);
  const rank = new Map(times.map((t, i) => [t, times.length > 1 ? i / (times.length - 1) : 1]));
  return data.commits.map((c, i) => {
    const txt = c.uncommitted ? 'Not committed' : `${mdy(c.at)} ${c.an}`;
    const r = c.uncommitted ? 1 : rank.get(c.at);
    const heat = r < 0.25 ? 0 : 0.25 + 0.75 * (r - 0.25) / 0.75;
    return `.gbc-${i}{--gbt:${cssStr(txt)};--gbh:${heat.toFixed(2)}}`;
  }).join('\n');
}
function cssStr(s) { return '"' + [...String(s)].map(ch => /[\w .:/\-]/.test(ch) ? ch : '\\' + ch.codePointAt(0).toString(16) + ' ').join('') + '"'; }
const paneOf = ed => panes.find(p => p.editor === ed);
const paneDoc = p => p && p.currentPath ? docs.get(p.currentPath) : null;
async function toggleBlame(force, doc) {
  doc = doc || currentDoc();
  if (!doc) return showToast('open a file first', true);
  const cur = G.blame.get(doc.key);
  if (cur && force !== true) { clearBlame(doc); return; }
  if (doc.dirty) showToast('blame shows the saved file — unsaved edits shift the lines', true);
  const d = await fetchBlame(doc);
  if (d.aborted) return;
  if (d.error) return showToast('blame: ' + errText(d), true);
  if (d.untracked) return showToast(baseName(doc.key) + ' is not in git yet', true);
  if (!docs.has(doc.key) || doc.model.isDisposed()) return;
  if (G.blame.has(doc.key)) clearBlame(doc);
  const style = el('style');
  style.textContent = blameStyle(d);
  document.head.appendChild(style);
  const decos = [];
  const n = Math.min(d.lines.length, doc.model.getLineCount());
  for (let i = 0; i < n; i++) {
    const ci = d.lines[i], r = new monaco.Range(i + 1, 1, i + 1, 1);
    // shade: every row of the line (wrapped rows too); text: its first row only
    decos.push({ range: r, options: { isWholeLine: true, marginClassName: `gba gbc-${ci}` } },
               { range: r, options: { marginClassName: `gbl gbc-${ci}` } });
  }
  const ids = doc.model.deltaDecorations([], decos);
  G.blame.set(doc.key, { data: d, ids, style });
  syncBlameWidth();
}
function clearBlame(doc) {
  const b = G.blame.get(doc.key);
  if (!b) return;
  if (!doc.model.isDisposed()) doc.model.deltaDecorations(b.ids, []);
  b.style.remove();
  G.blame.delete(doc.key);
  hideBlameTip();
  syncBlameWidth();
}
function syncBlameWidth() {
  for (const p of panes) {
    if (!p.editor) continue;
    const on = !!(p.currentPath && G.blame.has(p.currentPath));
    // the annotation column is drawn over a widened line-number column; the numbers stay right-aligned after it
    let want = 5;  // Monaco's default
    if (on) {
      const m = p.editor.getModel(), lay = p.editor.getLayoutInfo();
      const dw = p.editor.getOption(monaco.editor.EditorOption.fontInfo).maxDigitWidth || 8;
      const digits = Math.max(3, String(m ? m.getLineCount() : 1).length);
      want = Math.ceil((BLAME_W + 10 - lay.lineNumbersLeft) / dw) + digits;
    }
    if (p._gbw !== want) { p.editor.updateOptions({ lineNumbersMinChars: want }); p._gbw = want; }
    if (p._gbKey) p._gbKey.set(on);  // editor context menu: Annotate <-> Close Annotations
  }
}
// the blamed commit shown on `line` (decorations follow edits, so not d.lines[line - 1])
function blameAt(doc, line) {
  const b = doc && G.blame.get(doc.key);
  if (!b || doc.model.isDisposed()) return null;
  const dec = doc.model.getLineDecorations(line).find(x => b.ids.includes(x.id));
  const m = dec && /gbc-(\d+)/.exec(dec.options.marginClassName || '');
  return m ? { repo: b.data.repo, rel: b.data.rel, c: b.data.commits[+m[1]] } : null;
}
// IntelliJ's annotation tooltip: "commit <full hash>", "Author: name <mail>", "Date: M/D/YYYY h:mm AM", blank line, message.
// blame only knows the subject; the full message is fetched on first hover and cached per commit.
const mdyhm = ts => { const d = new Date(ts * 1000), h = d.getHours();
  return `${mdy(ts)} ${h % 12 || 12}:${String(d.getMinutes()).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`; };
const _tipBody = new Map();  // commit hash -> full message
let _tip = null, _tipFor = null;
function blameTipHtml(c) {
  if (c.uncommitted) return '<div class="tx">Not committed yet</div>';
  const msg = _tipBody.has(c.h) ? _tipBody.get(c.h) : c.s;
  return `<div class="tx">commit <span class="h">${esc(c.h)}</span>\nAuthor: ${esc(c.an)}${c.ae ? ` &lt;${esc(c.ae)}&gt;` : ''}\n` +
    `Date: ${esc(mdyhm(c.at))}\n\n<span class="s">${esc(msg)}</span></div>`;
}
function blameTip(x, y, c, repo) {
  if (!_tip) { _tip = el('div', 'gbl-tip'); document.body.appendChild(_tip); }
  if (_tipFor !== c || _tip.style.display !== 'block') {
    _tipFor = c;
    _tip.innerHTML = blameTipHtml(c);
    if (!c.uncommitted && repo && !_tipBody.has(c.h)) {
      api('commit', { repo: repo.root, rev: c.h }, 'blameTip').then(cm => {
        if (!cm || cm.aborted || cm.error || cm.body == null) return;
        _tipBody.set(c.h, cm.body);
        if (_tipFor === c && _tip.style.display === 'block') _tip.innerHTML = blameTipHtml(c);
      });
    }
  }
  _tip.style.display = 'block';
  const r = _tip.getBoundingClientRect();
  _tip.style.left = Math.max(4, Math.min(x + 14, innerWidth - r.width - 4)) + 'px';
  _tip.style.top = (y + 18 + r.height < innerHeight ? y + 18 : Math.max(4, y - r.height - 8)) + 'px';
}
function hideBlameTip() { if (_tip) _tip.style.display = 'none'; }
// a blamed commit's changed files in the diff modal, opened at this file
async function openBlameCommit(repo, c, rel) {
  hideBlameTip();
  const cm = await api('commit', { repo: repo.root, rev: c.h }, 'blameCommit');
  if (cm.aborted) return;
  if (cm.error) return showToast('commit: ' + errText(cm), true);
  const files = cm.files || [];
  if (!files.length) return showToast(short(c.h) + ' changes no files', true);
  const i = Math.max(0, files.findIndex(f => f.path === (c.f || rel)));
  const subject = String(cm.body || '').split('\n')[0];
  openDiffWin(files, i, f => specCommit(repo, cm, f).then(s => Object.assign(s, { sub: s.sub + '  ·  ' + cm.an + '  ·  ' + subject })),
    { ident: f => 'C:' + cm.h + '|' + f.path, repo,
      desc: f => { const d = descCommit(repo, cm, f); d.sub += '  ·  ' + cm.an + '  ·  ' + subject; return d; } });
}
function blameMenu(p, line, x, y) {
  const doc = paneDoc(p);
  if (!doc) return;
  const at = blameAt(doc, line);
  const items = [];
  if (at && at.c && !at.c.uncommitted) {
    items.push({ label: `Show Diff (${short(at.c.h)})`, run: () => openBlameCommit(at.repo, at.c, at.rel) },
      { label: 'Show Commit in Git Log', run: () => showGitCommit(at.repo, at.c.h) },
      { label: 'Copy Revision Number', run: () => copy(at.c.h, 'revision') },
      { label: 'Copy Commit Message', run: async () => {  // the hover tooltip follows the mouse, so it is copied from here
        const body = _tipBody.has(at.c.h) ? _tipBody.get(at.c.h) : (await api('commit', { repo: at.repo.root, rev: at.c.h }, 'blameCopy')).body;
        if (body != null) copy(body, 'commit message'); else showToast('could not read the commit message', true);
      } }, 'sep');
  }
  items.push(G.blame.has(doc.key) ? { label: 'Close Annotations', run: () => clearBlame(doc) }
                                  : { label: 'Annotate with Git Blame', run: () => toggleBlame(true, doc) });
  items.push({ label: "Show Current Line's Commit at Line End", checked: !!S().lineBlame, run: () => toggleLineBlame() },
    'sep', { label: 'Show History for Current File', run: () => runCommand('git.history') });
  showMenu(x, y, items);
}
// pane editors: blame width per model, clicks / hover / right-click on blame and change markers
const GUTTER = () => { const T = monaco.editor.MouseTargetType; return [T.GUTTER_GLYPH_MARGIN, T.GUTTER_LINE_NUMBERS, T.GUTTER_LINE_DECORATIONS]; };
function hookEditors() {
  if (typeof monaco === 'undefined') return;  // Monaco loads after this file
  registerEditorActions();
  for (const p of panes) {
    if (!p.editor || p._gitHooked) continue;
    p._gitHooked = true;
    p._gbKey = p.editor.createContextKey('readoBlame', false);
    p.editor.onDidChangeModel(() => { hideBlameTip(); setTimeout(syncBlameWidth, 0); lineBlameSoon(); });
    p.editor.onDidChangeCursorPosition(() => lineBlameSoon());
    p.editor.onMouseMove(e => {
      const t = e.target, at = t && t.position && inBlameColumn(p, e.event.posx) && blameAt(paneDoc(p), t.position.lineNumber);
      if (at && at.c) blameTip(e.event.posx, e.event.posy, at.c, at.repo); else hideBlameTip();
    });
    // a click on an annotation opens its commit; Monaco would select the line, so it never sees the click
    // (on the container: Monaco rebuilds its own DOM node for every model)
    p.editor.getContainerDomNode().addEventListener('mousedown', e => {
      if (e.button !== 0 || !inBlameColumn(p, e.clientX)) return;
      const t = p.editor.getTargetAtClientPoint(e.clientX, e.clientY);
      const at = t && t.position && blameAt(paneDoc(p), t.position.lineNumber);
      if (!at) return;
      e.preventDefault(); e.stopPropagation();
      if (at.c && !at.c.uncommitted) openBlameCommit(at.repo, at.c, at.rel);
    }, true);
    p.editor.onMouseLeave(hideBlameTip);
    p.editor.onContextMenu(e => {  // Monaco shows no menu on the gutter: ReadO's own
      if (!e.target || !GUTTER().includes(e.target.type) || !e.target.position) return;
      hideBlameTip();
      blameMenu(p, e.target.position.lineNumber, e.event.posx, e.event.posy);
    });
    p.editor.onMouseDown(e => {
      if (!e.target || e.target.type !== monaco.editor.MouseTargetType.GUTTER_LINE_DECORATIONS || !e.event.leftButton) return;
      const line = e.target.position && e.target.position.lineNumber;
      const doc = paneDoc(p);
      if (!doc || !line) return;
      const marker = doc.model.getLineDecorations(line).find(x => /git-(add|mod|del)/.test(x.options.linesDecorationsClassName || ''));
      if (marker) compareHeadAt(doc, line);
    });
  }
}
function inBlameColumn(p, clientX) {
  if (!(p.currentPath && G.blame.has(p.currentPath))) return false;
  const x = clientX - p.editor.getContainerDomNode().getBoundingClientRect().left;
  return x >= 0 && x < BLAME_W;
}
// editor right-click menu (Monaco's own): one entry that flips with the annotations
function registerEditorActions() {
  if (registerEditorActions.done) return;
  registerEditorActions.done = true;
  const docOf = ed => paneDoc(paneOf(ed));
  monaco.editor.addEditorAction({ id: 'reado.git.annotate', label: 'Annotate with Git Blame', precondition: '!readoBlame',
    contextMenuGroupId: '1_git', contextMenuOrder: 1, run: ed => toggleBlame(true, docOf(ed)) });
  monaco.editor.addEditorAction({ id: 'reado.git.closeAnnotations', label: 'Close Annotations', precondition: 'readoBlame',
    contextMenuGroupId: '1_git', contextMenuOrder: 1, run: ed => { const d = docOf(ed); if (d) clearBlame(d); } });
}

// ---------- current line's commit at the line end (Settings / Git menu; off by default) ----------
const _lineBlame = new Map();  // doc key -> {ver, fp, data, at, failed, pending}
let _lbTimer = 0;
function lineBlameSoon() { clearTimeout(_lbTimer); _lbTimer = setTimeout(updateLineBlame, 150); }
function toggleLineBlame(on) {
  S().lineBlame = on == null ? !S().lineBlame : !!on;
  saveState();
  updateLineBlame();
}
function relDate(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 3600) return Math.max(1, Math.floor(s / 60)) + ' min ago';
  if (s < 86400) return Math.floor(s / 3600) + ' hours ago';
  if (s < 86400 * 30) return Math.floor(s / 86400) + ' days ago';
  return mdy(ts);
}
async function updateLineBlame() {
  const act = currentPane();
  for (const p of panes) if (p._lbDecos && p !== act) p._lbDecos.clear();
  if (!act || !act.editor) return;
  const clear = () => { if (act._lbDecos) act._lbDecos.clear(); };
  const doc = paneDoc(act);
  if (!S().lineBlame || !doc || doc.model.isDisposed() || doc.dirty || (G.info && !G.info.available)) return clear();
  const ver = doc.model.getAlternativeVersionId();
  let e = _lineBlame.get(doc.key);
  if (e && e.pending) return;
  if (!e || e.ver !== ver || e.fp !== G.fp || (e.failed && Date.now() - e.at > 10000)) {
    e = { ver, fp: G.fp, pending: true, at: Date.now() };
    _lineBlame.set(doc.key, e);
    clear();
    const d = await fetchBlame(doc);
    e.pending = false;
    e.data = d.error || d.untracked ? null : d;
    e.failed = !!d.error && d.error !== 'not_repo' && d.error !== 'too_big';
    if (_lineBlame.get(doc.key) === e) lineBlameSoon();
    return;
  }
  const pos = act.editor.getPosition();
  const ci = e.data && pos ? e.data.lines[pos.lineNumber - 1] : null;
  const c = ci == null ? null : e.data.commits[ci];
  if (!c) return clear();
  const text = c.uncommitted ? 'You · not committed yet' : `${c.an}, ${relDate(c.at)} · ${c.s}`;
  const col = doc.model.getLineMaxColumn(pos.lineNumber);
  if (!act._lbDecos) act._lbDecos = act.editor.createDecorationsCollection();
  act._lbDecos.set([{ range: new monaco.Range(pos.lineNumber, col, pos.lineNumber, col),
    options: { showIfCollapsed: true, after: { content: '  ' + text, inlineClassName: 'glb-inline' } } }]);
}
async function compareHeadAt(doc, line) {
  await compareWithHead();
  if (_diff && _diff.ed) setTimeout(() => {
    const ed = _diff.ed.getModifiedEditor();
    ed.revealLineInCenter(line); ed.setPosition({ lineNumber: line, column: 1 });
  }, 120);
}
async function showGitCommit(repo, h) {
  if (!W) buildWindow();
  if (repo && (!G.repo || G.repo.root !== repo.root)) await selectRepo(repo.root, true);
  STATE.git.open = true; W.gw.classList.add('show'); saveState();
  await start();
  setTab('log');
  await Log.show();
  Log.reveal(h);
}

// ---------- conflict markers in open editors ----------
const _confDecos = new Map();
function updateConflicts() {
  const st = G.status;
  const keys = new Set();
  if (st && !st.error && G.repo) st.files.filter(f => f.kind === 'conflicted').forEach(f => { const k = keyFor(G.repo, f.path); if (k) keys.add(k); });
  G.conflicts = keys;
  for (const [key, ids] of _confDecos) {
    const doc = docs.get(key);
    if (!keys.has(key) || !doc) { if (doc && !doc.model.isDisposed()) doc.model.deltaDecorations(ids, []); _confDecos.delete(key); }
  }
  keys.forEach(k => markConflicts(docs.get(k)));
}
function markConflicts(doc) {
  if (!doc || doc.model.isDisposed() || !G.conflicts.has(doc.key)) return;
  const decos = [];
  let inside = false;
  const n = doc.model.getLineCount();
  for (let i = 1; i <= n && i < 200000; i++) {
    const t = doc.model.getLineContent(i);
    const mark = /^(<{7}|={7}|>{7}|\|{7})( |$)/.test(t);
    if (mark) inside = !t.startsWith('>>>>>>>');
    if (mark || inside) decos.push({ range: new monaco.Range(i, 1, i, 1), options: { isWholeLine: true, className: mark ? 'gconf-mark' : 'gconf-line',
      overviewRuler: mark ? { color: '#d1242f', position: 4 } : undefined } });
  }
  _confDecos.set(doc.key, doc.model.deltaDecorations(_confDecos.get(doc.key) || [], decos));
}

// ---------- commands, menu, keys, toolbar ----------
async function historyOfCurrent() {
  const doc = currentDoc();
  if (!doc) return showToast('open a file first', true);
  const inf = await api('info', { path: doc.key });
  if (!inf.available) return showToast(errText({ error: inf.reason }), true);
  if (!inf.repo) return showToast('not in a git repository', true);
  if (!G.repos.some(r => r.root === inf.repo.root)) G.repos.push(inf.repo);
  openHistory(G.repos.find(r => r.root === inf.repo.root), inf.rel);
}
async function ensureRepoForCommand() {
  if (!G.info) G.info = await api('info');
  if (!G.info.available) { showToast(errText({ error: G.info.reason }), true); return false; }
  if (!G.repo) await loadRepos();
  if (!G.repo) { showToast('no git repository in or around the open folder', true); return false; }
  if (!G.status) await loadStatus(false);
  return true;
}
function openTab(tab) { if (!W) buildWindow(); STATE.git.open = true; STATE.git.tab = tab; W.gw.classList.add('show'); saveState(); start(); }
const GIT_COMMANDS = [
  { id: 'git.toolwin', cat: 'Git', title: 'Git Tool Window', keys: 'Ctrl+Shift+G', bind: ['Ctrl+Shift+G'], run: () => toggleWindow(), checked: () => !!(STATE.git && STATE.git.open) },
  { id: 'git.changes', cat: 'Git', title: 'Local Changes', run: () => openTab('changes') },
  { id: 'git.log', cat: 'Git', title: 'Log', run: () => openTab('log') },
  { id: 'git.stash', cat: 'Git', title: 'Stash List', run: () => openTab('stash') },
  { id: 'git.console', cat: 'Git', title: 'Console (git commands)', run: () => openTab('console') },
  { id: 'git.history', cat: 'Git', title: 'Show History for Current File', run: () => historyOfCurrent(), enabled: () => !!currentDoc() },
  { id: 'git.blame', cat: 'Git', title: 'Annotate with Git Blame', run: () => toggleBlame(), enabled: () => !!currentDoc(),
    checked: () => { const d = currentDoc(); return !!(d && G.blame.has(d.key)); } },
  { id: 'git.lineBlame', cat: 'Git', title: "Show Current Line's Commit at Line End", run: () => toggleLineBlame(), checked: () => !!S().lineBlame },
  { id: 'git.branches', cat: 'Git', title: 'Branches…', run: () => branchPopup(document.getElementById('sbBranch')) },
  { id: 'git.refresh', cat: 'Git', title: 'Refresh Git Status', run: () => refreshAll(true) },
  { id: 'git.showEol', cat: 'Git', title: 'Show Line-Ending-Only Changes', run: () => toggleShowEol(), checked: () => !!S().showEol },
  { id: 'git.ignoreEol', cat: 'Git', title: 'Diff: Ignore Line Endings', run: () => toggleIgnoreEol(), checked: () => !!S().ignoreEol },
  { id: 'git.repo', cat: 'Git', title: 'Choose Repository…', run: async () => {
    await loadRepos();
    if (!G.repos.length) return showToast('no git repository in or around the open folder', true);
    pickList(document.getElementById('sbBranch'), G.repos.map(r => ({ value: r.root, label: r.name, hint: r.root })), { placeholder: 'repository…',
      onPick: v => { selectRepo(v); if (!STATE.git.open) toggleWindow(true); } });
  } },
  { id: 'git.agentCommit', cat: 'Git', title: 'Commit… (AgentO)', run: async () => {
    if (!(await ensureRepoForCommand())) return;
    const st = G.status;
    const ticked = Changes.built && Changes.tree ? Changes.tree.checkedFiles().map(f => f.path) : [];
    const files = ticked.length ? ticked : shownFiles(st).filter(f => f.kind !== 'untracked' && f.kind !== 'conflicted').map(f => f.path);
    if (!files.length) return showToast('nothing to commit (untracked files: tick them in Local Changes)', true);
    agentDialog('commit', { files });
  } },
  { id: 'git.agentPush', cat: 'Git', title: 'Push… (AgentO)', run: async () => {
    if (!(await ensureRepoForCommand())) return;
    const b = G.status.branch || {};
    agentDialog('push', { branch: b.head, upstream: b.upstream });
  } },
  { id: 'git.pull', cat: 'Git', title: 'Pull (fast-forward only)', run: () => tbPull(TB.repo || G.repo), enabled: () => !TB.busy && !!(TB.repo || G.repo) },
  { id: 'git.fetch', cat: 'Git', title: 'Fetch', run: () => gitFetch(TB.repo || G.repo), enabled: () => !TB.busy && !!(TB.repo || G.repo) },
  { id: 'git.agentBranch', cat: 'Git', title: 'New Branch… (AgentO)', run: async () => { if (await ensureRepoForCommand()) agentDialog('newBranch', {}); } },
  { id: 'git.agentStash', cat: 'Git', title: 'Stash Changes… (AgentO)', run: async () => { if (await ensureRepoForCommand()) agentDialog('stashPush'); } },
  { id: 'git.agentAsk', cat: 'Git', title: 'Ask AgentO…', run: async () => { if (await ensureRepoForCommand()) agentDialog('ask'); } },
  { id: 'git.openAgentO', cat: 'Git', title: 'Open AgentO', run: () => openAgentO() },
  { id: 'git.agentoPath', cat: 'Git', title: 'Set AgentO.exe Location…', run: async () => {
    const r = await askChoice('AgentO.exe location', 'Used when AgentO is not running and not installed under %LOCALAPPDATA%\Programs\AgentO. Full path to AgentO.exe (empty: find it automatically).',
      [{ label: 'save', value: 'ok', primary: true }, { label: 'cancel', value: 'cancel' }], { input: S().agentoPath || '' });
    if (!r || r.value !== 'ok') return;
    S().agentoPath = (r.text || '').trim().replace(/^"|"$/g, '');
    saveState();
    const t = await postJson('/api/git/agento', { path: S().agentoPath, probe: true });
    showToast(t.ok && t.data.path ? 'AgentO: ' + t.data.path : 'AgentO.exe not found there', !(t.ok && t.data.path));
  } },
  { id: 'git.terminal', cat: 'Git', title: 'Open Terminal in Repository', run: async () => { if (await ensureRepoForCommand()) openTerminal(); } },
];
function registerCommands() {
  for (const c of GIT_COMMANDS) { if (!CMD.has(c.id)) { COMMANDS.push(c); CMD.set(c.id, c); } }
  Object.assign(KEYMAPS.intellij.over, {
    'git.toolwin': { keys: 'Alt+9', bind: ['Alt+9'] },
    'git.changes': { keys: 'Alt+0', bind: ['Alt+0'] },
    'git.agentCommit': { keys: 'Ctrl+K', bind: ['Ctrl+K'], capture: true },
    'git.agentPush': { keys: 'Ctrl+Shift+K', bind: ['Ctrl+Shift+K'], capture: true },
  });
  if (!MENUS.some(m => m.label === 'Git')) {
    const i = MENUS.findIndex(m => m.label === 'Window');
    MENUS.splice(i < 0 ? MENUS.length - 1 : i, 0, { label: 'Git', items: ['git.toolwin', 'git.changes', 'git.log', 'git.stash', 'git.console', '-',
      'git.history', 'git.blame', 'git.lineBlame', 'file.compareHead', '-', 'git.branches', 'git.pull', 'git.fetch', '-',
      { label: 'AgentO', items: ['git.agentCommit', 'git.agentPush', '-','git.agentBranch', 'git.agentStash', '-', 'git.agentAsk', 'git.openAgentO', 'git.agentoPath'] },
      'git.terminal', '-', 'git.showEol', 'git.ignoreEol', '-', 'git.repo', 'git.refresh'] });
  }
  applyKeymap(STATE.keymap);
  renderMenuBar();
  // toolbar group: branch of the active file's repository, Pull (ReadO), Commit / Push (requests to AgentO)
  const groups = document.getElementById('tbGroups');
  if (groups && !groups.querySelector('[data-group="git"]')) {
    const prefs = groups.querySelector('[data-group="prefs"]');
    const g = el('div', 'tbg gtb');
    g.dataset.group = 'git';
    g.innerHTML = `<button class="tbtn gtb-branch" id="gtbBranch"><svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.3"><circle cx="4.5" cy="3.5" r="1.6"/><circle cx="4.5" cy="12.5" r="1.6"/><circle cx="11.5" cy="6" r="1.6"/><path d="M4.5 5.1v5.8M11.5 7.6c0 2.6-7 1.6-7 3.3"/></svg><span class="nm">Git</span><span class="ab"></span></button>` +
      `<button class="tbtn gtb-act" id="gtbPull" data-a="pull"><svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2.5v9M4 7.5l4 4 4-4M3 14h10"/></svg><span class="spin"></span></button>` +
      `<button class="tbtn gtb-act agento" id="gtbCommit" data-a="commit"><svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8.5l3 3 7-7"/></svg><span class="am">A</span></button>` +
      `<button class="tbtn gtb-act agento" id="gtbPush" data-a="push"><svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M8 13.5v-9M4 8.5l4-4 4 4M3 2h10"/></svg><span class="am">A</span></button>`;
    const anchor = prefs && prefs.previousElementSibling && prefs.previousElementSibling.classList.contains('tbsep') ? prefs.previousElementSibling : prefs;
    groups.insertBefore(g, anchor);
    groups.insertBefore(el('span', 'tbsep'), g);
    g.querySelector('#gtbBranch').addEventListener('click', e => { if (TB.repo) branchPopup(e.currentTarget, TB.repo); else tbOpenLog(); });
    g.querySelector('#gtbBranch').addEventListener('contextmenu', e => { e.preventDefault(); tbOpenLog(); });
    g.querySelector('#gtbPull').addEventListener('click', () => tbPull());
    g.querySelector('#gtbCommit').addEventListener('click', () => tbRequest('commit'));
    g.querySelector('#gtbPush').addEventListener('click', () => tbRequest('push'));
    renderTB();
  }
  renderToolbarTitles();
  try { fitToolbar(); } catch (e) {}
}

// ---------- toolbar Git group ----------
// Target: the repository of the active file (else the Git tool window's). Pull runs here
// (fetch + merge --ff-only, gitview.pull); Commit / Push only ask AgentO (agento:// deep link).
const TB = { key: null, repo: null, st: null, fp: '', t: 0, busy: false, loading: false };
// Commit / Push through agento://dispatch (GIT-DESIGN §14.3, draft): off until AgentO handles it;
// meanwhile the buttons copy the instruction (the existing AgentO hand-off)
let USE_DEEPLINK = false;
const _repoByDir = new Map();  // ReadO folder key -> {t, repo|null}
const dirKey = k => { const i = k.lastIndexOf('/'); return i < 0 ? '' : k.slice(0, i); };
function repoForKeyCached(key) {
  const hit = _repoByDir.get(dirKey(key));
  return hit && Date.now() - hit.t < 60000 ? hit.repo : undefined;
}
async function repoForKey(key) {
  const c = repoForKeyCached(key);
  if (c !== undefined) return c;
  const inf = await api('info', { path: key });
  const repo = inf.repo || null;
  _repoByDir.set(dirKey(key), { t: Date.now(), repo });
  return repo;
}
async function tbRefresh(force) {
  if (TB.loading) return;
  TB.loading = true;
  try {
    if (!G.info) G.info = await api('info');
    const doc = currentDoc();
    const key = doc ? doc.key : '';
    let repo = null;
    if (G.info.available) repo = key ? await repoForKey(key) : G.repo;
    const moved = (repo && repo.root) !== (TB.repo && TB.repo.root);
    TB.repo = repo; TB.key = key;
    if (!repo) { TB.st = null; TB.fp = ''; return; }
    const fp = await api('fp', { repo: repo.root });
    if (force || moved || fp.fp !== TB.fp || Date.now() - TB.t > 8000) {
      const st = await api('status', { repo: repo.root, fresh: force ? 1 : '' });
      if (TB.repo !== repo) return;
      TB.st = st.error ? null : st; TB.fp = fp.fp || ''; TB.t = Date.now();
    }
  } finally {
    TB.loading = false;
    renderTB();
  }
}
const PULL_WHY = {
  detached: 'HEAD is detached — no branch to pull', no_upstream: 'the branch has no upstream (tracking) branch',
  repo_busy: 'a merge / rebase is in progress — finish or abort it first (AgentO / terminal); ReadO leaves it as it is',
  non_ff: 'the branch has diverged from its upstream, so it cannot fast-forward. ReadO does not merge or rebase — ask AgentO to merge / rebase, or pull in a terminal.',
  local_changes: 'local changes would be overwritten. ReadO never forces this or discards them — commit or stash them first (AgentO), then try again.',  auth: 'the remote needs credentials ReadO cannot ask for — sign in once with git (terminal / AgentO), then pull again',
  busy: 'a pull / fetch / checkout is already running', timeout: 'git took longer than 60 s and was stopped',
  nothing_to_commit: 'nothing to commit', nothing_to_push: 'nothing to push (↑0)',
};
const whyText = d => PULL_WHY[d.error] || errText(d);
function tbState() {
  const st = TB.st, b = st && st.branch, files = shownFiles(st);
  return { st, b, files, commitable: files.filter(f => f.kind !== 'conflicted'), avail: !!(G.info && G.info.available) };
}
function renderTB() {
  const btn = document.getElementById('gtbBranch');
  if (!btn) return;
  const { st, b, commitable, avail } = tbState();
  const repo = TB.repo;
  const name = !avail || !repo ? 'Git' : b ? (b.head || 'detached ' + short(b.oid)) : (repo.branch || '…');
  btn.querySelector('.nm').textContent = name;
  const ab = b && b.upstream && (b.ahead || b.behind) ? (b.ahead ? `↑${b.ahead}` : '') + (b.behind ? ` ↓${b.behind}` : '') : '';
  btn.querySelector('.ab').textContent = ab.trim();
  btn.classList.toggle('on', !!(avail && repo));
  const tw = CMD.get('git.toolwin');
  btn.title = !avail ? 'Git — ' + errText({ error: (G.info && G.info.reason) || 'no_git' })
    : !repo ? 'Git — the active file is not in a git repository\nClick: Git tool window' + (tw && tw.keys ? ` (${tw.keys})` : '')
    : `${repo.name}: branch ${name}` + (b && b.upstream ? ` → ${b.upstream}  ↑${b.ahead} ↓${b.behind}` : b && b.head ? ' (no upstream)' : '') +
      (repo.state ? ` · ${repo.state.toUpperCase()}` : '') + `\n${repo.root}\nClick: branches (checkout, pull, fetch) · right-click: Log` + (tw && tw.keys ? ` (${tw.keys})` : '');
  const set = (id, off, title) => { const x = document.getElementById(id); x.disabled = !!off; x.title = title; };
  const pullWhy = !avail ? 'git not found' : !repo ? 'not in a git repository' : !st ? 'loading…' : !b.head ? PULL_WHY.detached
    : !b.upstream ? PULL_WHY.no_upstream : (st.repo && st.repo.state) ? PULL_WHY.repo_busy : '';
  set('gtbPull', TB.busy || pullWhy, TB.busy ? 'Pull — running…' : 'Pull (git pull --ff-only: fast-forward only)' +
    (b && b.behind ? ` — ↓${b.behind} known` : '') + (pullWhy ? '\n— ' + pullWhy : ''));
  document.getElementById('gtbPull').classList.toggle('busy', TB.busy);
  if (W) W.head.querySelectorAll('[data-a="pull"],[data-a="fetch"],[data-a="branch"]').forEach(x => { x.disabled = TB.busy; x.classList.toggle('busy', TB.busy); });
  const commitWhy = !repo || !st ? 'not in a git repository' : !commitable.length ? 'no local changes' : '';
  set('gtbCommit', commitWhy, `Commit… — AgentO에 요청(head coach에게 전달)` + (commitable.length ? ` · ${commitable.length} changed file(s)` : '') + (commitWhy ? '\n— ' + commitWhy : ''));
  const pushWhy = !repo || !st ? 'not in a git repository' : !b.head ? PULL_WHY.detached : b.upstream && !b.ahead ? 'nothing to push (↑0)' : '';
  set('gtbPush', pushWhy, `Push — AgentO에 요청(head coach에게 전달, force 없음)` + (b && b.ahead ? ` · ↑${b.ahead}` : '') + (pushWhy ? '\n— ' + pushWhy : ''));
}
// breadcrumb: the repository folder of the file stands out (chip); the path after it stays as it was
const _renderCrumbs = renderCrumbs;
renderCrumbs = function (path) {
  const plain = _renderCrumbs(path);
  if (!path || isAbsKey(path) || !G.info || !G.info.available) return plain;
  const repo = repoForKeyCached(path);
  if (repo === undefined) {
    repoForKey(path).then(r => { const c = document.getElementById('crumbs'); if (r && c && currentPath === path) c.innerHTML = renderCrumbs(path); });
    return plain;
  }
  const base = norm(_settings.base_dir || ''), root = repo ? norm(repo.root) : '';
  if (!repo || !base || !root.toLowerCase().startsWith(base.toLowerCase() + '/')) return plain;  // the folder is the repository (or inside it)
  const pre = root.slice(base.length + 1);
  if (!path.toLowerCase().startsWith(pre.toLowerCase() + '/')) return plain;
  const segs = pre.split('/'), name = segs.pop(), sep = '<span class="sep">/</span>';
  return (segs.length ? segs.map(esc).join(sep) + sep : '') +
    `<span class="crumb-repo" title="git repository: ${esc(repo.root.replace(/\//g, '\\'))}${repo.branch ? '\nbranch ' + esc(repo.branch) : ''}">${esc(name)}</span>` +
    sep + _renderCrumbs(path.slice(pre.length + 1));
};
async function tbOpenLog() {
  if (TB.repo && (!G.repo || G.repo.root !== TB.repo.root)) await selectRepo(TB.repo.root, true);
  if (!TB.repo && !G.repo) return toggleWindow(true);
  openTab('log');
}
// open documents with unsaved editor edits in this repository, and their repo-relative paths
function dirtyDocsIn(repo) {
  const root = norm(repo.root).toLowerCase() + '/';
  return [...docs.values()].filter(d => d.dirty && norm(fullPathOf(d.key)).toLowerCase().startsWith(root));
}
function unsavedIn(repo) {
  const n = norm(repo.root).length + 1;
  return dirtyDocsIn(repo).map(d => norm(fullPathOf(d.key)).slice(n));
}
// TB.busy: a pull / fetch / checkout is running (any repository); its buttons wait
function tbBusy(on) { TB.busy = on; renderTB(); }
async function tbAfterChange(repo) {
  await tbRefresh(true);
  if (G.repo && G.repo.root === repo.root) await refreshAll(false);
  else refreshDecor();
  updateBranch();
}
// After a pull / checkout moved HEAD: the folder tree, the open files (unedited ones re-read,
// edited ones kept and flagged, deleted ones marked), the git views and the symbol index
// (rebuilt by the server, gitview._source_changed) show the new sources at once.
async function refreshSource(repo) {
  for (let i = 0; i < 60 && _polling; i++) await new Promise(r => setTimeout(r, 50));
  try { await pollChanges(); } catch (e) {}
  try { await refreshTreeDir(''); } catch (e) {}
  try { refreshIndexStatus(); } catch (e) {}
  const root = norm(repo.root).toLowerCase() + '/';  // changed-line markers + status bar branch against the new HEAD
  for (const d of docs.values()) if (norm(fullPathOf(d.key)).toLowerCase().startsWith(root)) scheduleGit(d, 0);
  await tbAfterChange(repo);
}
const choiceOf = r => (r && typeof r === 'object' ? r.value : r);
// a refused / failed pull, fetch or checkout: why, what git said, where the full output is
// files in the way of a pull / checkout that differ from HEAD only in CRLF ↔ LF (gitview._eol_note):
// what it means and how to clear it — advice only; ReadO changes neither the files nor the settings
function eolHelp(d) {
  const f = d.eol_files || [];
  if (!f.length) return '';
  return `\n\n${d.eol_all ? (f.length === 1 ? 'The file' : `All ${f.length} files`) : `${f.length} of the ${(d.blocking || []).length} files`} in the way ` +
    `${f.length === 1 ? 'differs' : 'differ'} from HEAD only in line endings (CRLF ↔ LF):\n` + f.slice(0, 8).map(x => '  ' + x).join('\n') + (f.length > 8 ? `\n  … ${f.length - 8} more` : '') +
    `\ngit still counts that as a local change. ReadO does not restore these files or change the repository's settings.` +
    `\nTo clear it yourself: check core.autocrlf (here: ${d.autocrlf || 'not set'}) and .gitattributes (e.g. "* text=auto"), then restore ` +
    `the files (git checkout -- <file>; their content is unchanged) or renormalize (git add --renormalize .) — or ask AgentO.`;
}
async function gitFailDialog(title, d, repo, extraButtons) {
  const out = String(d.git || d.output || '').trim().split('\n').slice(-14).join('\n');
  const v = choiceOf(await askChoice(title, whyText(d) + eolHelp(d) + (out ? '\n\ngit:\n' + out : ''),
    [...(extraButtons || []), { label: 'show Console', value: 'console' }, { label: 'ok', value: 'ok', primary: true }]));
  if (v === 'console' || v === 'stash') {
    if (!G.repo || G.repo.root !== repo.root) await selectRepo(repo.root, true);
    if (v === 'console') openTab('console'); else agentDialog('stashPush');
  }
}
async function tbPull(repo) {
  repo = repo || TB.repo;
  if (TB.busy || !repo) return;
  tbBusy(true);
  const inf = await api('pullinfo', { repo: repo.root });
  tbBusy(false);
  if (inf.error) return showToast('pull: ' + errText(inf), true);
  if (inf.reason) return showToast('pull: ' + whyText({ error: inf.reason }), true);
  const unsaved = unsavedIn(repo);
  const msg = `Repository:  ${repo.root.replace(/\//g, '\\')}\nBranch:        ${inf.branch}  ←  ${inf.upstream}` +
    (inf.behind ? `  (↓${inf.behind} known before fetch)` : '') +
    `\nRemote:        ${inf.remote}${inf.url ? '  ' + inf.url : ''}\n\n` +
    'Runs git fetch, then git merge --ff-only (= git pull --ff-only). If the branch cannot fast-forward, or local changes are in the way, ReadO stops and changes nothing — no merge commit, rebase or stash.' +
    (inf.dirty ? `\n\n${inf.dirty} local change(s) are kept as they are` + (inf.eol_only ? ` (${inf.eol_only} only in line endings).` : '.') : '') +
    (unsaved.length ? `\n\n⚠ ${unsaved.length} file(s) here have unsaved edits — if the pull changes them you will be asked again.` : '');
  const r = await askChoice('Pull ' + inf.branch, msg, [{ label: 'pull', value: 'ok', primary: true }, { label: 'cancel', value: 'cancel' }]);
  if (r !== 'ok' && !(r && r.value === 'ok')) return;
  await runPull(repo, unsaved, false);
}
async function runPull(repo, unsaved, allow) {
  tbBusy(true);
  let r;
  try { r = await postJson('/api/git/pull', { repo: repo.root, unsaved, allow_unsaved: allow }); }
  finally { tbBusy(false); }
  const d = r.data || {};
  if (d.need_confirm === 'unsaved') {
    const a = await askChoice('Pull changes files you are editing',
      `The pull changes ${d.files.length} file(s) that have unsaved edits in ReadO:\n` + d.files.slice(0, 12).map(f => '  ' + f).join('\n') +
      (d.files.length > 12 ? `\n  … ${d.files.length - 12} more` : '') +
      '\n\nPull anyway? The editor keeps your unsaved text; saving it later overwrites the pulled version.',
      [{ label: 'pull anyway', value: 'ok', primary: true }, { label: 'cancel', value: 'cancel' }]);
    if (a === 'ok' || (a && a.value === 'ok')) return runPull(repo, unsaved, true);
    return;
  }
  if (d.ok && d.updated) {
    showToast(`pulled ${d.commits} commit${d.commits === 1 ? '' : 's'} into ${(d.info || {}).branch || 'the branch'} · ${d.files} file${d.files === 1 ? '' : 's'} changed`);
    return refreshSource(repo);
  }
  if (d.ok) showToast('pull: already up to date');
  else await gitFailDialog('Pull stopped — nothing changed', d, repo, d.error === 'local_changes' ? [{ label: 'Stash Changes… (AgentO)', value: 'stash' }] : []);
  await tbAfterChange(repo);
}
// Fetch: git fetch --prune (remote-tracking branches only; the working tree stays as it is)
async function gitFetch(repo) {
  repo = repo || TB.repo;
  if (TB.busy || !repo) return;
  tbBusy(true);
  let r;
  try { r = await postJson('/api/git/fetch', { repo: repo.root }); }
  finally { tbBusy(false); }
  const d = r.data || {};
  if (d.ok) showToast(`fetched${d.remote ? ' ' + d.remote : ''}` + (d.upstream ? ` · ${d.upstream}: ↑${d.ahead} ↓${d.behind}` : '') +
    (d.behind ? ' — Pull brings them in' : ''));
  else await gitFailDialog('Fetch failed', d, repo);
  await tbAfterChange(repo);
}
// Checkout: git switch to a local branch, or a new local branch tracking a remote-only one
// (gitview.checkout). Never forced: when local changes are in the way git's refusal is shown.
async function gitCheckout(repo, ref) {
  if (TB.busy || !repo) return;
  const name = refName(ref);
  const dirty = dirtyDocsIn(repo);
  if (dirty.length) {
    const v = choiceOf(await askChoice('Unsaved edits — check out ' + name + '?',
      `${dirty.length} file(s) in ${repo.name} have unsaved edits:\n` + dirty.slice(0, 12).map(d => '  ' + d.key).join('\n') +
      (dirty.length > 12 ? `\n  … ${dirty.length - 12} more` : '') +
      '\n\nSave them first? Saved edits are local changes: git keeps them across the checkout, or refuses it when the other branch changes the same files.',
      [{ label: 'save all and check out', value: 'save', primary: true }, { label: 'cancel', value: 'cancel' }]));
    if (v !== 'save') return;
    for (const d of dirty) if (!(await saveDoc(d)) || d.dirty) return showToast('checkout cancelled: ' + baseName(d.key) + ' was not saved', true);
  }
  tbBusy(true);
  let r;
  try { r = await postJson('/api/git/checkout', { repo: repo.root, ref, unsaved: unsavedIn(repo) }); }
  finally { tbBusy(false); }
  const d = r.data || {};
  if (d.ok && !d.updated) return showToast(`already on ${d.branch}`);
  if (d.ok) {
    showToast(`switched to ${d.branch}` + (d.created ? ` (new local branch tracking ${d.tracking})` : '') + ` · ${d.files} file${d.files === 1 ? '' : 's'} differ from ${d.from || 'before'}`);
    return refreshSource(repo);
  }
  if (d.error === 'local_exists') {
    const v = choiceOf(await askChoice('Check out ' + name,
      `A local branch ${d.branch} already exists and ${d.upstream ? 'tracks ' + d.upstream : 'tracks no remote branch'}, not ${d.remote_branch}.\nReadO does not reset or rename it.`,
      [{ label: 'check out local ' + d.branch, value: 'local', primary: true }, { label: 'cancel', value: 'cancel' }]));
    if (v === 'local') return gitCheckout(repo, 'refs/heads/' + d.branch);
    return;
  }
  if (d.need_confirm) return showToast('checkout stopped: save the edited files first', true);
  await gitFailDialog('Checkout of ' + name + ' refused — nothing changed', d, repo,
    d.error === 'local_changes' ? [{ label: 'Stash Changes… (AgentO)', value: 'stash' }] : []);
  await tbAfterChange(repo);
}
// Commit / Push: ReadO never runs these — a request goes to AgentO (agento://dispatch, docs/GIT-DESIGN.md §14)
function tbCommitDialog(repo, files, unsaved) {
  return new Promise(resolve => {
    const bg = el('div', 'gx-bg');
    const b = (TB.st && TB.st.branch) || {};
    bg.innerHTML = `<div class="gx-dlg gtb-dlg"><h3>Commit — AgentO에 요청</h3>
      <div class="sub">ReadO does not commit. ${USE_DEEPLINK ? "This sends a request to AgentO, which passes it to the project's head coach." : "The instruction is copied for AgentO (paste it into the session for this repository)."}</div>
      <div class="kv"><span>Repository</span><b>${esc(repo.root.replace(/\//g, '\\'))}</b><span>Branch</span><b>${esc(b.head || '')}</b>
        <span>Files</span><b>${files.length} changed file${files.length === 1 ? '' : 's'}</b></div>
      <div class="files">${files.slice(0, 200).map(f => `<div>${esc(f)}</div>`).join('')}${files.length > 200 ? `<div>… ${files.length - 200} more</div>` : ''}</div>
      ${unsaved.length ? `<div class="warn">⚠ ${unsaved.length} file(s) have unsaved edits in ReadO — save them first so AgentO sees them.</div>` : ''}
      <input class="msg" placeholder="commit message draft (optional, ≤ 200 characters)" maxlength="200" spellcheck="false">
      <div class="row"><span class="note"></span><button data-a="cancel">cancel</button><button data-a="go" class="primary">${USE_DEEPLINK ? 'send to AgentO' : 'copy for AgentO'}</button></div></div>`;
    const close = v => { bg.remove(); document.removeEventListener('keydown', onKey, true); resolve(v); };
    const onKey = e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(null); }
      else if (e.key === 'Enter' && e.target.classList.contains('msg')) { e.preventDefault(); close({ msg: e.target.value }); } };
    document.addEventListener('keydown', onKey, true);
    bg.addEventListener('mousedown', e => { if (e.target === bg) close(null); });
    bg.querySelector('.row').addEventListener('click', e => {
      const a = e.target.dataset && e.target.dataset.a;
      if (a === 'cancel') close(null);
      if (a === 'go') close({ msg: bg.querySelector('.msg').value });
    });
    document.body.appendChild(bg);
    bg.querySelector('.msg').focus();
  });
}
async function tbRequest(kind) {
  const repo = TB.repo;
  if (!repo || !TB.st) return;
  await tbRefresh(true);
  const { b, commitable } = tbState();
  if (!b) return;
  let msg = '', files = [];
  if (kind === 'commit') {
    if (!commitable.length) return showToast('nothing to commit', true);
    const ticked = Changes.built && Changes.tree && G.repo && G.repo.root === repo.root ? Changes.tree.checkedFiles().map(f => f.path) : [];
    files = ticked.length ? ticked : commitable.map(f => f.path);
    const r = await tbCommitDialog(repo, files, unsavedIn(repo));
    if (!r) return;
    msg = r.msg.trim();
  } else {
    if (b.upstream && !b.ahead) return showToast('nothing to push (↑0)', true);
    const a = await askChoice('Push — AgentO에 요청',
      `Repository:  ${repo.root.replace(/\//g, '\\')}\nBranch:        ${b.head}${b.upstream ? '  →  ' + b.upstream + `  (↑${b.ahead})` : '  (no upstream yet)'}\n\n` +
      'ReadO does not push. ' + (USE_DEEPLINK ? 'AgentO passes the request to the head coach' : 'The instruction is copied for AgentO') + '; force push is never requested.',
      [{ label: USE_DEEPLINK ? 'send to AgentO' : 'copy for AgentO', value: 'ok', primary: true }, { label: 'cancel', value: 'cancel' }]);
    if (a !== 'ok' && !(a && a.value === 'ok')) return;
  }
  const instruction = d => `[ReadO → AgentO] ${repoLine(repo)}\n\n` +
    AGENT[kind](kind === 'commit' ? { files: (d && d.files) || files, message: msg } : { branch: (d && d.branch) || b.head, upstream: b.upstream });
  if (!USE_DEEPLINK) {  // for now: the instruction on the clipboard, AgentO brought up
    await copyQuiet(instruction());
    const o = await postJson('/api/git/agento', { path: S().agentoPath || '' });
    showToast(`AgentO에 보낼 ${kind} 지시문을 복사했습니다` + (o.ok && o.data.launched ? ' — AgentO에 붙여 넣어 주세요' : ' — AgentO를 열고 붙여 넣어 주세요'));
    return tbAfterChange(repo);
  }
  const r = await postJson('/api/git/agento-request', { repo: repo.root, kind, msg, files });
  const d = r.data || {};
  if (d.sent) showToast(`AgentO에 ${kind} 요청을 보냈습니다`);
  else if (d.fallback) {
    await copyQuiet(instruction(d));
    showToast('AgentO가 아직 agento:// 요청을 지원하지 않습니다. 지시문을 복사했습니다', true);
  } else return showToast(kind + ': ' + whyText(d), true);
  await tbAfterChange(repo);
}

// ---------- init ----------
function init() {
  S();
  registerCommands();
  buildWindow();
  Log = LogView(W.pages.log, {});
  W.gw.classList.toggle('show', !!STATE.git.open);
  const sb = document.getElementById('sbBranch');
  sb.addEventListener('click', () => branchPopup(sb));
  sb.title = 'git branch — click: branches · gutter markers: changes against HEAD';
  new MutationObserver(muts => { for (const m of muts) m.addedNodes.forEach(n => { if (n.nodeType === 1) applyDecor(n); }); })
    .observe(document.getElementById('tree'), { childList: true, subtree: true });
  const prevOpened = typeof window.onFolderOpened === 'function' ? window.onFolderOpened : null;
  window.onFolderOpened = function () {
    if (prevOpened) prevOpened();
    G.repos = []; G.repo = null; G.status = null; G.refs = null; G.fp = ''; G.decor = { files: {}, dirs: {} };
    _repoByDir.clear(); TB.key = null; TB.repo = null; TB.st = null;
    Log.reset(); Changes.reset(); Stash.reset(); closeHistory(true);
    S().repo = '';
    (async () => { await loadRepos(); if (STATE.git.open) start(); refreshDecor(); })();
  };
  window.addEventListener('focus', () => { if (G.repo) { loadStatus(true).then(() => { if (STATE.git.open && STATE.git.tab === 'changes') Changes.render(); }); refreshDecor(); } });
  (async () => {
    G.info = await api('info');
    if (!G.info.available) { if (STATE.git.open) start(); return; }
    await loadRepos();
    if (STATE.git.open) start();
    await loadStatus(false);
    refreshDecor();
  })();
  setInterval(poll, 2500);
  setInterval(hookEditors, 1000);
  // toolbar branch: follows the active file at once, re-checks the repository now and then
  setInterval(() => {
    if (document.hidden) return;
    const d = currentDoc(), k = d ? d.key : '';
    if (k !== TB.key || Date.now() - TB.t > 4000) tbRefresh();
  }, 1000);
  window.addEventListener('focus', () => tbRefresh(true));
  setInterval(() => { syncBlameWidth(); if (S().lineBlame) updateLineBlame(); }, 1500);
  // open docs: re-mark conflicts as they load / change
  setInterval(() => { G.conflicts.forEach(k => { const d = docs.get(k); if (d && !_confDecos.has(k)) markConflicts(d); }); }, 2000);
}
window.GitUI = { G, DW, get DM() { return dmFront(); }, openDiffWin, openPanelWin, closeDiffModal, closeDiffWin, diffModalOpen, toggleWindow, setTab, openHistory, toggleBlame, clearBlame, blameAt, openBlameCommit, toggleLineBlame, updateLineBlame, agentDialog, refreshAll, laneStep, get Log() { return Log; }, get History() { return History; }, Changes, Stash,
  get useDeeplink() { return USE_DEEPLINK; }, set useDeeplink(v) { USE_DEEPLINK = !!v; }, selectRepo, get S() { return S(); }, get DV() { return [...DV]; } };
init();
})();
