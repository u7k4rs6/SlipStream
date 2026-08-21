/* Data loading and the personal study layer.
 *
 * The personal layer is keyed by the derived problem ID, never by title or URL,
 * because upstream retitles questions under stable slugs -- title-keyed notes
 * would silently detach from their problem. When a relink does move an ID, the
 * new record lists the old one in `aliases`, and migrate() carries the entry
 * across so nothing is orphaned.
 */

const STORAGE_KEY = 'slipstream.personal.v1';
const THEME_KEY = 'slipstream.theme';

export const STATUSES = ['todo', 'attempted', 'solved', 'revisit'];
export const STATUS_LABEL = {
  todo: 'To do', attempted: 'Attempted', solved: 'Solved', revisit: 'Revisit',
};

/* Upstream derives these markers from the date, so they carry no independent
 * information and are recomputed here rather than parsed out of the table. */
export const FIRE_DAYS = 14;
export const NEW_DAYS = 45;

export async function loadData(base = 'data') {
  const [problems, index, latest, meta, origins] = await Promise.all([
    getJSON(`${base}/problems.json`),
    getJSON(`${base}/index.json`),
    getJSON(`${base}/changes/latest.json`).catch(() => null),
    getJSON(`${base}/meta.json`).catch(() => null),
    getJSON(`${base}/origins.json`).catch(() => null),
  ]);
  return {
    rows: problems.problems,
    index,
    latest,
    meta,
    // Optional by design: origins.json is regenerated against a third party on
    // its own schedule, so a missing or stale one must degrade to the search
    // fallback rather than take the app down with it.
    origins: (origins && origins.origins) || {},
  };
}

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: ${response.status} ${response.statusText}`);
  return response.json();
}

export function daysSince(iso, today = new Date()) {
  if (!iso) return Infinity;
  const then = Date.parse(`${iso}T00:00:00Z`);
  if (Number.isNaN(then)) return Infinity;
  return Math.floor((today.getTime() - then) / 86400000);
}

export function freshness(row, today) {
  const age = daysSince(row.upstream_updated, today);
  if (age <= FIRE_DAYS) return 'fire';
  if (age <= NEW_DAYS) return 'new';
  return null;
}

/* ---- where to actually solve it ---------------------------------------- */

/* Upstream's own link goes to fastprep.io, which asks for an account before it
 * will show the question. `origins.json` carries a direct link for the ~5% of
 * the bank that exists on LeetCode under a title we can match with certainty;
 * everything else is a fastprep-original OA write-up that exists nowhere else,
 * so the best honest offer is a search seeded with what we know about it.
 *
 * The query is built here rather than baked into the artifact: ~1,800 search
 * URLs would be a large file carrying nothing the client cannot derive. */
const CODE_FORMATS = ['Coding', 'SQL'];

export function originFor(row, origins) {
  return (origins && origins[row.id]) || null;
}

export function searchUrl(row) {
  const parts = [`"${row.title}"`];
  if (row.companies.length) parts.push(row.companies[0]);
  parts.push(CODE_FORMATS.includes(row.format) ? 'leetcode' : 'interview question');
  return `https://www.google.com/search?q=${encodeURIComponent(parts.join(' '))}`;
}

/* ---- personal layer ---------------------------------------------------- */

export function emptyEntry() {
  return { status: null, difficulty: 0, notes: '', solution_url: '', tags: [] };
}

export function loadPersonal() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (err) {
    // A corrupt blob must never take the app down with it, and must never be
    // overwritten silently either -- so it is kept and reported.
    console.error('personal data could not be read', err);
    return {};
  }
}

export function savePersonal(personal) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(personal));
    return true;
  } catch (err) {
    console.error('personal data could not be saved', err);
    return false;
  }
}

/* Follow relink aliases so personal work survives a URL change upstream. */
export function migrate(rows, personal) {
  let moved = 0;
  const next = { ...personal };
  for (const row of rows) {
    if (next[row.id]) continue;
    for (const oldId of row.aliases || []) {
      if (next[oldId]) {
        next[row.id] = { ...next[oldId], migrated_from: oldId };
        delete next[oldId];
        moved += 1;
        break;
      }
    }
  }
  return { personal: next, moved };
}

export function isTouched(entry) {
  if (!entry) return false;
  return Boolean(
    entry.status || entry.notes || entry.solution_url ||
    (entry.difficulty || 0) > 0 || (entry.tags || []).length,
  );
}

export function allTags(personal) {
  const seen = new Map();
  for (const entry of Object.values(personal)) {
    for (const tag of entry.tags || []) seen.set(tag, (seen.get(tag) || 0) + 1);
  }
  return [...seen.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

export function exportPersonal(personal) {
  return JSON.stringify(
    { schema: 'slipstream.personal.v1', exported: new Date().toISOString(), entries: personal },
    null, 2,
  );
}

export function importPersonal(text) {
  const parsed = JSON.parse(text);
  const entries = parsed && parsed.entries ? parsed.entries : parsed;
  if (!entries || typeof entries !== 'object') throw new Error('not a Slipstream export');
  return entries;
}

/* ---- theme ------------------------------------------------------------- */

export function loadTheme() {
  return localStorage.getItem(THEME_KEY) || 'dark';
}

export function saveTheme(theme) {
  localStorage.setItem(THEME_KEY, theme);
  document.documentElement.dataset.theme = theme;
}
