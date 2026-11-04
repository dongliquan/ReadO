// ===== Tree =====
async function loadTree(rel, ulEl) {
  if (!ulEl) return;
  let data;
  try {
    const r = await fetch('/api/tree?path=' + encodeURIComponent(rel), { cache: 'no-store' });
    if (!r.ok) {
      ulEl.innerHTML = '<div style="padding:12px;color:var(--text-mute);font-size:11px;">tree load failed (HTTP ' + r.status + ')</div>';
      return;
    }
    data = await r.json();
  } catch (e) {
    ulEl.innerHTML = '<div style="padding:12px;color:var(--down);font-size:11px;">' + escapeHtml(e.message) + '</div>';
    return;
  }
  if (data.no_folder) {
    ulEl.innerHTML = '<div class="tree-empty">No folder open.<br><button onclick="openFolderDialog()">Open Folder…</button></div>';
    return;
  }
  if (data.error) {
    ulEl.innerHTML = '<div style="padding:12px;color:var(--down);font-size:11px;">' + escapeHtml(data.error) + '</div>';
    return;
  }
  ulEl.innerHTML = '';
  if (!data.items || !data.items.length) {
    ulEl.innerHTML = '<div class="tree-empty">empty folder</div>';
    return;
  }
  for (const it of data.items) {
    const childPath = rel ? rel + '/' + it.name : it.name;
    const node = document.createElement('div');
    node.className = 'node' + (it.binary ? ' bin' : '');
    node.dataset.path = childPath;
    node.dataset.dir = it.is_dir ? '1' : '0';
    node.innerHTML = `
      <span class="caret">${it.is_dir ? '▸' : ' '}</span>
      <span class="ic">${it.is_dir ? FOLDER_SVG : fileBadge(it.name)}</span>
      <span class="name">${escapeHtml(it.name)}</span>
    `;
    ulEl.appendChild(node);
    if (it.is_dir) {
      const childContainer = document.createElement('div');
      childContainer.className = 'children';
      childContainer.style.display = 'none';
      ulEl.appendChild(childContainer);
      node.addEventListener('click', e => {
        e.stopPropagation();
        const isOpen = childContainer.style.display === 'block';
        if (isOpen) {
          childContainer.style.display = 'none';
          node.querySelector('.caret').textContent = '▸';
        } else {
          node.querySelector('.caret').textContent = '▾';
          childContainer.style.display = 'block';
          if (!childContainer.dataset.loaded) {
            loadTree(childPath, childContainer);
            childContainer.dataset.loaded = '1';
          }
        }
      });
    } else {
      node.addEventListener('click', e => {
        e.stopPropagation();
        if (it.binary) { showToast(`${it.name}: binary file — ReadO opens text files only`, true); return; }
        openFile(childPath);
      });
    }
  }
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ===== File open (opens in active pane) =====
async function openFile(path, gotoLine, term) {
  return openFileInPane(activePaneIdx, path, gotoLine, term);
}

// Put the cursor on `line`, selecting the match of `find` there and only
// highlighting the others. (It used to multi-select every case-insensitive
// match, so the first one — often line 1 — became the cursor; with editing on,
// typing would also have replaced all of them.)
// find: {term, regex, caseS, word} or a plain string (literal, case-sensitive).
const WORD_SEPARATORS = '`~!@#$%^&*()-=+[{]}\\|;:\'",.<>/?';
function gotoInEditor(line, find) {
  const p = currentPane();
  const ed = p && p.editor;
  const model = ed && ed.getModel();
  if (!model) return;
  if (typeof find === 'string') find = { term: find, caseS: true };
  line = Math.max(1, Math.min(line, model.getLineCount()));
  let range = new monaco.Range(line, 1, line, 1);
  const decos = [];
  if (find && find.term) {
    let matches = [];
    try {
      matches = model.findMatches(find.term, false, !!find.regex, !!find.caseS,
                                  find.word ? WORD_SEPARATORS : null, false, 5000);
    } catch (e) {}
    if (matches.length) {
      const dist = m => Math.abs(m.range.startLineNumber - line);
      range = matches.reduce((best, m) => dist(m) < dist(best) ? m : best).range;
      for (const m of matches) {
        decos.push({ range: m.range, options: {
          inlineClassName: 'reado-hit',
          overviewRuler: { color: '#e5c07b', position: monaco.editor.OverviewRulerLane.Center },
        } });
      }
    }
  }
  if (p.hits) p.hits.clear();
  p.hits = ed.createDecorationsCollection(decos);
  ed.setSelection(range);
  ed.revealRangeInCenter(range);
  ed.focus();
}

function cssEscape(s) { return s.replace(/(["\\])/g, '\\$1'); }

async function revealInTree(path) {
  if (!path) return;
  document.querySelectorAll('.node.active').forEach(n => n.classList.remove('active'));
  if (isAbsKey(path)) return;  // outside base_dir: not in the tree
  const parts = path.split('/');
  let parent = document.getElementById('tree');
  let curr = '';
  for (let i = 0; i < parts.length; i++) {
    curr = curr ? curr + '/' + parts[i] : parts[i];
    const node = parent.querySelector(`:scope > .node[data-path="${cssEscape(curr)}"]`);
    if (!node) return;
    if (i < parts.length - 1) {
      // folder — expand if not yet
      const childContainer = node.nextElementSibling;
      if (childContainer && childContainer.classList.contains('children')) {
        if (childContainer.style.display !== 'block') {
          childContainer.style.display = 'block';
          node.querySelector('.caret').textContent = '▾';
        }
        if (!childContainer.dataset.loaded) {
          await loadTree(curr, childContainer);
          childContainer.dataset.loaded = '1';
        }
        parent = childContainer;
      } else {
        return;
      }
    } else {
      node.classList.add('active');
      node.scrollIntoView({ block: 'nearest' });
    }
  }
}

function renderCrumbs(path) {
  const parts = path.split(/[\\/]/);
  const last = parts.pop();
  const prefix = parts.map(escapeHtml).join('<span class="sep">/</span>');
  return (prefix ? prefix + '<span class="sep">/</span>' : '') + `<span class="file" title="double-click: source full width (sidebar away) / back">${escapeHtml(last)}</span>`;
}

