/* Slipstream UI.
 *
 * Two rules run through all of it:
 *   - Every upstream string is set as text, never as markup. Titles and company
 *     names come from a third party and are never trusted as HTML.
 *   - Personal state is keyed by the derived problem ID and written only in
 *     response to a deliberate edit, so a data reload can never clobber it.
 */

import { h, render } from '../vendor/preact.mjs';
import { useCallback, useEffect, useMemo, useRef, useState } from '../vendor/hooks.mjs';
import htm from '../vendor/htm.mjs';
import {
  STATUSES, STATUS_LABEL, allTags, daysSince, emptyEntry, exportPersonal,
  freshness, importPersonal, isTouched, loadData, loadPersonal, loadTheme,
  migrate, savePersonal, saveTheme,
} from './store.js';
import { search } from './search.js';

const html = htm.bind(h);
const ROW_H = 46;
const OVERSCAN = 8;
const TODAY = new Date();
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const FORMATS = ['Coding', 'SQL', 'System design', 'Low-level design', 'AI coding'];
const AGES = [
  ['all', 'Any time'], ['1', 'Today'], ['7', 'Last 7 days'], ['30', 'Last 30 days'],
];
const SORTS = [
  ['updated', 'Recently updated'], ['first_seen', 'Recently added'],
  ['title', 'Title A–Z'], ['company', 'Company A–Z'],
];

function shortDate(iso) {
  if (!iso) return '—';
  const [y, m, d] = iso.split('-');
  const month = MONTHS[+m - 1];
  return +y === TODAY.getUTCFullYear() ? `${month} ${+d}` : `${month} '${y.slice(2)}`;
}

function fmtDate(iso) {
  if (!iso) return '—';
  const [y, m, d] = iso.split('-');
  return `${MONTHS[+m - 1]} ${+d}, ${y}`;
}

/* ---------------------------------------------------------------- filters */

function useFilters() {
  const [state, setState] = useState({
    query: '', formats: [], companies: [], statuses: [], tags: [],
    age: 'all', untouchedOnly: false, showRemoved: false, sort: 'updated',
  });
  const patch = useCallback((next) => setState((s) => ({ ...s, ...next })), []);
  const toggleIn = useCallback((key, value) => setState((s) => {
    const list = s[key];
    return { ...s, [key]: list.includes(value) ? list.filter((v) => v !== value) : [...list, value] };
  }), []);
  return [state, patch, toggleIn];
}

function applyFilters(rows, index, f, personal) {
  const hits = search(index, f.query);
  const allowed = hits === null ? null : new Set(hits);
  const wantFormat = new Set(f.formats);
  const wantCompany = new Set(f.companies);
  const wantStatus = new Set(f.statuses);
  const wantTags = new Set(f.tags);
  const maxAge = f.age === 'all' ? Infinity : Number(f.age);

  const out = [];
  for (let i = 0; i < rows.length; i += 1) {
    if (allowed && !allowed.has(i)) continue;
    const row = rows[i];
    const entry = personal[row.id];

    // Removed rows stay visible when personal work references them (D17):
    // silently hiding something I took notes on is the one thing worse than
    // showing a dead link.
    if (row.state === 'removed' && !f.showRemoved && !isTouched(entry)) continue;
    if (wantFormat.size && !wantFormat.has(row.format)) continue;
    if (wantCompany.size && !row.companies.some((c) => wantCompany.has(c))) continue;
    if (wantStatus.size && !wantStatus.has(entry && entry.status)) continue;
    if (wantTags.size && !(entry && (entry.tags || []).some((t) => wantTags.has(t)))) continue;
    if (f.untouchedOnly && isTouched(entry)) continue;
    if (maxAge !== Infinity && daysSince(row.first_seen, TODAY) >= maxAge) continue;
    out.push(row);
  }

  const dir = {
    updated: (a, b) => (b.upstream_updated || '').localeCompare(a.upstream_updated || ''),
    first_seen: (a, b) => (b.first_seen || '').localeCompare(a.first_seen || ''),
    title: (a, b) => a.title.localeCompare(b.title),
    company: (a, b) => (a.companies[0] || '~').localeCompare(b.companies[0] || '~'),
  }[f.sort];
  return out.sort(dir);
}

/* ------------------------------------------------------------------- app */

function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [personal, setPersonal] = useState(() => loadPersonal());
  const [view, setView] = useState('browse');
  const [openId, setOpenId] = useState(null);
  const [filters, patch, toggleIn] = useFilters();
  const [theme, setTheme] = useState(() => loadTheme());
  const searchRef = useRef(null);

  useEffect(() => { saveTheme(theme); }, [theme]);

  useEffect(() => {
    loadData().then((loaded) => {
      setData(loaded);
      setPersonal((current) => {
        const { personal: moved, moved: count } = migrate(loaded.rows, current);
        if (count) savePersonal(moved);
        return moved;
      });
    }).catch(setError);
  }, []);

  const update = useCallback((id, changes) => {
    setPersonal((current) => {
      const entry = { ...emptyEntry(), ...(current[id] || {}), ...changes, updated_at: new Date().toISOString() };
      const next = { ...current, [id]: entry };
      if (!isTouched(entry)) delete next[id];
      savePersonal(next);
      return next;
    });
  }, []);

  useEffect(() => {
    const onKey = (event) => {
      const typing = /^(INPUT|TEXTAREA)$/.test(event.target.tagName);
      if (event.key === '/' && !typing) { event.preventDefault(); searchRef.current && searchRef.current.focus(); }
      else if (event.key === 'Escape') {
        if (typing) event.target.blur();
        else if (openId) setOpenId(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [openId]);

  const visible = useMemo(
    () => (data ? applyFilters(data.rows, data.index, filters, personal) : []),
    [data, filters, personal],
  );

  if (error) {
    return html`<div class="empty" style="padding-top:80px">
      <b>Could not load the dataset</b>
      ${String(error.message || error)}
      <div style="margin-top:10px;font-size:12px">
        Serve this directory over HTTP — <code>python3 -m http.server</code> —
        rather than opening the file directly.
      </div>
    </div>`;
  }
  if (!data) return html`<div class="boot">Loading question bank…</div>`;

  const solved = Object.values(personal).filter((e) => e.status === 'solved').length;
  const bootstrap = Boolean(data.latest) && data.latest.counts.added >= data.rows.length;
  const newCount = data.latest && !bootstrap ? (data.latest.counts.added || 0) : 0;

  return html`<div class="app">
    <${Header} ...${{ view, setView, filters, patch, searchRef, theme, setTheme,
                      solved, total: data.rows.length, newCount }} />
    <div class="body">
      ${view === 'browse' && html`<${Sidebar} ...${{ rows: data.rows, filters, patch, toggleIn, personal }} />`}
      <main>
        ${view === 'browse' && html`<${Browse} ...${{ visible, total: data.rows.length, filters, patch,
                                                      personal, update, openId, setOpenId }} />`}
        ${view === 'new' && html`<${WhatsNew} latest=${data.latest} meta=${data.meta} personal=${personal} bootstrap=${bootstrap} />`}
        ${view === 'stats' && html`<${Stats} rows=${data.rows} personal=${personal} meta=${data.meta}
                                             setPersonal=${setPersonal} />`}
      </main>
    </div>
  </div>`;
}

function Header({ view, setView, filters, patch, searchRef, theme, setTheme, solved, total, newCount }) {
  const pct = total ? Math.round((solved / total) * 100) : 0;
  return html`<header class="bar">
    <div class="brand"><span class="dot">🌀</span> Slipstream <small>${total.toLocaleString()} questions</small></div>
    <div class="tabs" role="tablist">
      <button role="tab" aria-selected=${view === 'browse'} onClick=${() => setView('browse')}>Browse</button>
      <button role="tab" aria-selected=${view === 'new'} onClick=${() => setView('new')}>
        What's new${newCount ? html`<span class="badge">${newCount}</span>` : null}
      </button>
      <button role="tab" aria-selected=${view === 'stats'} onClick=${() => setView('stats')}>Progress</button>
    </div>
    <div class="search">
      <span class="icon">⌕</span>
      <input ref=${searchRef} type="search" placeholder="Search titles and companies…"
             value=${filters.query} onInput=${(e) => patch({ query: e.target.value })} />
      ${!filters.query && html`<kbd>/</kbd>`}
    </div>
    <div class="spacer"></div>
    <div class="progress-pill" title="Problems you have marked solved">
      <b>${solved}</b> solved
      <span class="meter"><i style=${`width:${pct}%`}></i></span>
    </div>
    <button class="icon-btn" title="Toggle theme"
            onClick=${() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
      ${theme === 'dark' ? '☀' : '☾'}
    </button>
  </header>`;
}

/* --------------------------------------------------------------- sidebar */

function Sidebar({ rows, filters, patch, toggleIn, personal }) {
  const [companyQuery, setCompanyQuery] = useState('');

  const companies = useMemo(() => {
    const counts = new Map();
    for (const row of rows) {
      if (row.state === 'removed') continue;
      for (const c of row.companies) counts.set(c, (counts.get(c) || 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [rows]);

  const formatCounts = useMemo(() => {
    const counts = new Map();
    for (const row of rows) if (row.state !== 'removed') counts.set(row.format, (counts.get(row.format) || 0) + 1);
    return counts;
  }, [rows]);

  const tags = useMemo(() => allTags(personal), [personal]);
  const needle = companyQuery.trim().toLowerCase();
  const shown = needle ? companies.filter(([c]) => c.toLowerCase().includes(needle)) : companies.slice(0, 40);
  const active = filters.formats.length + filters.companies.length + filters.statuses.length
    + filters.tags.length + (filters.age !== 'all' ? 1 : 0) + (filters.untouchedOnly ? 1 : 0);

  return html`<aside>
    <h3>Format</h3>
    <div class="chips">
      ${FORMATS.map((f) => html`
        <button class="chip" aria-pressed=${filters.formats.includes(f)} onClick=${() => toggleIn('formats', f)}>
          ${f}<span class="n">${formatCounts.get(f) || 0}</span>
        </button>`)}
    </div>

    <h3>My status</h3>
    <div class="chips">
      ${STATUSES.map((s) => html`
        <button class="chip" aria-pressed=${filters.statuses.includes(s)} onClick=${() => toggleIn('statuses', s)}>
          ${STATUS_LABEL[s]}
        </button>`)}
      <button class="chip" aria-pressed=${filters.untouchedOnly}
              onClick=${() => patch({ untouchedOnly: !filters.untouchedOnly })}>Untouched</button>
    </div>

    ${tags.length > 0 && html`
      <h3>My tags</h3>
      <div class="chips">
        ${tags.map(([tag, n]) => html`
          <button class="chip" aria-pressed=${filters.tags.includes(tag)} onClick=${() => toggleIn('tags', tag)}>
            ${tag}<span class="n">${n}</span>
          </button>`)}
      </div>`}

    <h3>First seen</h3>
    <div class="chips">
      ${AGES.map(([value, label]) => html`
        <button class="chip" aria-pressed=${filters.age === value} onClick=${() => patch({ age: value })}>${label}</button>`)}
    </div>

    <h3>Company</h3>
    <input class="co-search" placeholder="Filter companies…" value=${companyQuery}
           onInput=${(e) => setCompanyQuery(e.target.value)} />
    <div class="co-list">
      ${shown.map(([name, n]) => html`
        <button aria-pressed=${filters.companies.includes(name)} onClick=${() => toggleIn('companies', name)}>
          <span>${name}</span><span class="n">${n}</span>
        </button>`)}
      ${!needle && companies.length > 40 && html`
        <button style="color:var(--faint)" disabled>…${companies.length - 40} more, type to find</button>`}
    </div>

    <h3>Removed upstream</h3>
    <label class="toggle">
      <input type="checkbox" checked=${filters.showRemoved}
             onChange=${(e) => patch({ showRemoved: e.target.checked })} />
      Show removed questions
    </label>

    ${active > 0 && html`
      <button class="clear-all" onClick=${() => patch({
        formats: [], companies: [], statuses: [], tags: [], age: 'all', untouchedOnly: false,
      })}>Clear ${active} filter${active > 1 ? 's' : ''}</button>`}
  </aside>`;
}

/* ---------------------------------------------------------------- browse */

function Browse({ visible, total, filters, patch, personal, update, openId, setOpenId }) {
  const scroller = useRef(null);
  const cycleStatus = (id) => {
    const current = (personal[id] || {}).status;
    const at = STATUSES.indexOf(current);
    update(id, { status: at === STATUSES.length - 1 ? null : STATUSES[at + 1] });
  };
  const [scrollTop, setScrollTop] = useState(0);
  const [height, setHeight] = useState(800);

  useEffect(() => {
    const element = scroller.current;
    if (!element) return undefined;
    const measure = () => setHeight(element.clientHeight);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // Virtualised: ~40 rows exist in the DOM regardless of how many match.
  const first = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN);
  const last = Math.min(visible.length, Math.ceil((scrollTop + height) / ROW_H) + OVERSCAN);
  const slice = visible.slice(first, last);
  const open = openId ? visible.find((r) => r.id === openId) : null;

  return html`
    <div class="list-head">
      <span><b>${visible.length.toLocaleString()}</b> of ${total.toLocaleString()}</span>
      <div class="spacer"></div>
      <label>Sort
        <select value=${filters.sort} onChange=${(e) => patch({ sort: e.target.value })}>
          ${SORTS.map(([value, label]) => html`<option value=${value}>${label}</option>`)}
        </select>
      </label>
    </div>
    <div class="scroller" ref=${scroller} onScroll=${(e) => setScrollTop(e.target.scrollTop)}>
      ${visible.length === 0
        ? html`<div class="empty"><b>Nothing matches</b>Try clearing a filter or searching for something else.</div>`
        : html`<div class="rows" style=${`height:${visible.length * ROW_H}px`}>
            ${slice.map((row, i) => html`
              <${Row} key=${row.id} row=${row} top=${(first + i) * ROW_H}
                      entry=${personal[row.id]} open=${openId === row.id}
                      onOpen=${() => setOpenId(openId === row.id ? null : row.id)}
                      onCycle=${() => cycleStatus(row.id)} />`)}
          </div>`}
    </div>
    ${open && html`<${Detail} row=${open} entry=${personal[openId] || emptyEntry()}
                              update=${update} close=${() => setOpenId(null)} />`}`;
}

function Row({ row, top, entry, open, onOpen, onCycle }) {
  const mark = freshness(row, TODAY);
  const status = entry && entry.status;
  return html`
    <div class=${`row${open ? ' is-open' : ''}${row.state === 'removed' ? ' removed' : ''}`}
         style=${`top:${top}px`} onClick=${onOpen}>
      <button class=${`stat-dot${status ? ` ${status}` : ''}`}
              title=${`${status ? STATUS_LABEL[status] : 'Not started'} — click to cycle`}
              onClick=${(e) => { e.stopPropagation(); onCycle(); }}></button>
      <span class="title">${row.title}</span>
      ${entry && entry.notes ? html`<span class="note-dot" title="Has notes">✎</span>` : null}
      <span class="cos">${row.companies.slice(0, 3).map((c) => html`<span class="co">${c}</span>`)}</span>
      <span class="fmt">${row.format}</span>
      <span class="when">
        ${mark ? html`<span class=${`mark ${mark}`}>${mark === 'fire' ? 'HOT' : 'NEW'}</span>` : null}
        ${shortDate(row.upstream_updated)}
      </span>
    </div>`;
}

function Detail({ row, entry, update, close }) {
  const [tagDraft, setTagDraft] = useState('');
  if (!row) return null;

  const addTag = (raw) => {
    const tag = raw.trim().toLowerCase();
    if (!tag || (entry.tags || []).includes(tag)) return;
    update(row.id, { tags: [...(entry.tags || []), tag] });
    setTagDraft('');
  };

  return html`<div class="detail" onClick=${(e) => e.stopPropagation()}>
    <div class="detail-top">
      <div style="flex:1;min-width:0">
        <h2>${row.title}</h2>
        <div class="detail-meta">
          <span>${row.companies.join(' · ') || 'Unattributed'}</span>
          <span>${row.format}</span>
          <span>Updated ${fmtDate(row.upstream_updated)}</span>
          <span>First seen ${fmtDate(row.first_seen)}</span>
          ${row.state === 'removed' && html`<span style="color:var(--revisit)">Removed upstream ${fmtDate(row.removed_on)}</span>`}
        </div>
      </div>
      ${row.url && html`<a class="open-link" href=${row.url} target="_blank" rel="noopener noreferrer">Practice ↗</a>`}
      <button class="icon-btn" onClick=${close} title="Close (Esc)">✕</button>
    </div>

    <div class="grid">
      <div>
        <div class="field">
          <label>Notes — approach, gotchas, what tripped me up</label>
          <textarea value=${entry.notes || ''} placeholder="Sliding window; watch the empty-input case…"
                    onInput=${(e) => update(row.id, { notes: e.target.value })}></textarea>
        </div>
        <div class="field">
          <label>My solution (link to a gist, repo, or file)</label>
          <input type="url" value=${entry.solution_url || ''} placeholder="https://gist.github.com/…"
                 onInput=${(e) => update(row.id, { solution_url: e.target.value })} />
        </div>
      </div>

      <div>
        <div class="field">
          <label>Status</label>
          <div class="status-row">
            ${STATUSES.map((s) => html`
              <button class=${s} aria-pressed=${entry.status === s}
                      onClick=${() => update(row.id, { status: entry.status === s ? null : s })}>
                ${STATUS_LABEL[s]}
              </button>`)}
          </div>
        </div>
        <div class="field">
          <label>How hard did I find it</label>
          <div class="stars">
            ${[1, 2, 3, 4, 5].map((n) => html`
              <button class=${n <= (entry.difficulty || 0) ? 'on' : ''} title=${`${n} / 5`}
                      onClick=${() => update(row.id, { difficulty: entry.difficulty === n ? 0 : n })}>★</button>`)}
          </div>
        </div>
        <div class="field">
          <label>Tags</label>
          <div class="tag-row">
            ${(entry.tags || []).map((tag) => html`
              <span class="tag">${tag}
                <button onClick=${() => update(row.id, { tags: entry.tags.filter((t) => t !== tag) })}>✕</button>
              </span>`)}
            <input class="tag-input" placeholder="+ tag" value=${tagDraft}
                   onInput=${(e) => setTagDraft(e.target.value)}
                   onKeyDown=${(e) => { if (e.key === 'Enter') addTag(tagDraft); }}
                   onBlur=${() => addTag(tagDraft)} />
          </div>
        </div>
      </div>
    </div>
  </div>`;
}

/* ------------------------------------------------------------ what's new */

const CHANGE_LABEL = {
  added: 'Added', removed: 'Removed', retitled: 'Retitled',
  relinked: 'Relinked', recompanied: 'Company changed',
};

function WhatsNew({ latest, meta, personal, bootstrap }) {
  if (!latest) {
    return html`<div class="pane"><div class="empty"><b>No change log yet</b>
      The first sync has nothing to compare against.</div></div>`;
  }
  const groups = ['added', 'removed', 'retitled', 'relinked', 'recompanied']
    .map((kind) => [kind, latest.changes.filter((c) => c.kind === kind)])
    .filter(([, list]) => list.length);

  return html`<div class="pane">
    <h2>What changed on ${fmtDate(latest.date)}</h2>
    <div class="sub">
      Upstream ${meta ? meta.upstream_sha.slice(0, 8) : '—'} · synced ${meta ? meta.synced_at.replace('T', ' ').replace('+00:00', ' UTC') : '—'}
    </div>

    ${bootstrap && html`
      <div class="warn-box" style="border-color:var(--accent)">
        <h3 style="color:var(--accent)">First sync</h3>
        <div style="color:var(--muted);font-size:12.5px">
          Everything counts as new on the first run, because there was nothing to compare
          against. From tomorrow this page shows only what actually moved.
        </div>
      </div>`}

    ${latest.ambiguous_relinks && latest.ambiguous_relinks.length > 0 && html`
      <div class="warn-box">
        <h3>⚠ ${latest.ambiguous_relinks.length} relink${latest.ambiguous_relinks.length > 1 ? 's' : ''} need confirming</h3>
        <div style="color:var(--muted);font-size:12.5px;margin-bottom:8px">
          These look like the same problem under a new URL, but the match is not certain,
          so nothing was merged automatically — your notes stay where they are.
        </div>
        ${latest.ambiguous_relinks.map((a) => html`
          <div class="change"><span class="what">${a.title}</span><small>${a.reason}</small></div>`)}
      </div>`}

    ${groups.map(([kind, list]) => html`
      <div class="change-group">
        <h3>${CHANGE_LABEL[kind]}<span class="count">${list.length}</span></h3>
        ${list.slice(0, 60).map((c) => html`
          <div class="change">
            <span class="what">${c.kind === 'retitled' ? c.before.title : c.title}</span>
            ${c.kind === 'retitled' && html`<span class="arrow">→</span><span class="what">${c.after.title}</span>`}
            ${c.kind === 'recompanied' && html`<small>${(c.before.companies || []).join(', ')} → ${(c.after.companies || []).join(', ')}</small>`}
            ${c.kind === 'relinked' && html`<small>URL changed — your notes followed it</small>`}
            ${c.kind === 'removed' && isTouched(personal[c.id]) && html`<small style="color:var(--revisit)">you have notes on this</small>`}
          </div>`)}
        ${list.length > 60 && html`<div style="color:var(--faint);font-size:12px">…and ${list.length - 60} more</div>`}
      </div>`)}
  </div>`;
}

/* --------------------------------------------------------------- progress */

function Stats({ rows, personal, meta, setPersonal }) {
  const live = rows.filter((r) => r.state !== 'removed');
  const counts = { todo: 0, attempted: 0, solved: 0, revisit: 0 };
  for (const entry of Object.values(personal)) if (entry.status) counts[entry.status] += 1;
  const touched = Object.values(personal).filter(isTouched).length;

  const byCompany = new Map();
  for (const row of live) {
    const entry = personal[row.id];
    if (!entry || entry.status !== 'solved') continue;
    for (const c of row.companies) byCompany.set(c, (byCompany.get(c) || 0) + 1);
  }
  const top = [...byCompany.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12);
  const most = top.length ? top[0][1] : 1;

  const doExport = () => {
    const blob = new Blob([exportPersonal(personal)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `slipstream-personal-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const doImport = () => {
    const picker = document.createElement('input');
    picker.type = 'file';
    picker.accept = 'application/json';
    picker.onchange = async () => {
      const file = picker.files && picker.files[0];
      if (!file) return;
      try {
        const merged = { ...personal, ...importPersonal(await file.text()) };
        savePersonal(merged);
        setPersonal(merged);
      } catch (err) {
        console.error('import failed', err);
      }
    };
    picker.click();
  };

  return html`<div class="pane">
    <h2>Progress</h2>
    <div class="sub">${touched} of ${live.length.toLocaleString()} questions have something of yours on them.</div>

    <div class="stat-grid">
      <div class="stat-card"><div class="v" style="color:var(--solved)">${counts.solved}</div><div class="k">Solved</div></div>
      <div class="stat-card"><div class="v" style="color:var(--attempted)">${counts.attempted}</div><div class="k">Attempted</div></div>
      <div class="stat-card"><div class="v" style="color:var(--revisit)">${counts.revisit}</div><div class="k">Revisit</div></div>
      <div class="stat-card"><div class="v">${counts.todo}</div><div class="k">To do</div></div>
      <div class="stat-card"><div class="v">${live.length.toLocaleString()}</div><div class="k">Live questions</div></div>
      <div class="stat-card"><div class="v">${(rows.length - live.length).toLocaleString()}</div><div class="k">Removed upstream</div></div>
    </div>

    <h3 style="font-size:13px;margin:0 0 8px">Solved by company</h3>
    ${top.length === 0
      ? html`<div style="color:var(--faint);font-size:12.5px">Mark something solved and it shows up here.</div>`
      : html`<div class="bars">
          ${top.map(([name, n]) => html`
            <div class="bar-row">
              <span class="name">${name}</span>
              <span class="track"><span class="fill" style=${`width:${(n / most) * 100}%`}></span></span>
              <span class="n">${n}</span>
            </div>`)}
        </div>`}

    <h3 style="font-size:13px;margin:22px 0 6px">Your data</h3>
    <div style="color:var(--faint);font-size:12.5px">
      Notes live in this browser only, keyed by problem ID so they survive upstream retitles.
      Export to move them to another machine.
    </div>
    <div class="tools">
      <button onClick=${doExport}>Export notes</button>
      <button onClick=${doImport}>Import notes</button>
    </div>
  </div>`;
}

render(html`<${App} />`, document.getElementById('app'));
