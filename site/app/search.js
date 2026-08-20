/* Query the prebuilt inverted index.
 *
 * The index ships as {token: [rowIdx]} plus a prefix map pointing at tokens, so
 * as-you-type matching unions the postings of every token sharing the typed
 * prefix. Intersecting sorted arrays of ~2,000 ints is microseconds; no search
 * library is vendored because none would be faster on five-word titles.
 */

export function tokenize(text) {
  return (text.toLowerCase().match(/[a-z0-9]+/g) || []);
}

function postingsFor(index, token, isLast) {
  const exact = index.tokens[token];
  if (!isLast) return exact || [];

  // The final term is a live prefix: union everything it could still become.
  const expansions = token.length >= index.min_prefix ? (index.prefixes[token] || []) : [];
  if (!exact && !expansions.length) {
    // Below the prefix floor, fall back to scanning token keys. Only reachable
    // for one- and two-character terms, where the candidate set is tiny.
    if (token.length >= index.min_prefix) return [];
    const merged = new Set();
    for (const key of Object.keys(index.tokens)) {
      if (key.startsWith(token)) for (const row of index.tokens[key]) merged.add(row);
    }
    return [...merged].sort((a, b) => a - b);
  }
  const merged = new Set(exact || []);
  for (const word of expansions) {
    for (const row of index.tokens[word] || []) merged.add(row);
  }
  return [...merged].sort((a, b) => a - b);
}

function intersect(a, b) {
  const out = [];
  let i = 0, j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { out.push(a[i]); i += 1; j += 1; }
    else if (a[i] < b[j]) i += 1;
    else j += 1;
  }
  return out;
}

/** Row indices matching every term, or null when the query is empty. */
export function search(index, query) {
  const terms = tokenize(query);
  if (!terms.length) return null;
  let rows = null;
  for (let t = 0; t < terms.length; t += 1) {
    const postings = postingsFor(index, terms[t], t === terms.length - 1);
    rows = rows === null ? postings : intersect(rows, postings);
    if (!rows.length) return [];
  }
  return rows;
}
