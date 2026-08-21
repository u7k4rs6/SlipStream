# Slipstream — Frontend Specification

**Status:** Decisions ratified 2026-08-20 · Ready to build
**Date:** 2026-08-20 · Decision log in `PRD.md` §10.
Sizing based on the measured dataset: **1,944 rows**, 233 company tokens, 5 formats.

---

## 1. Constraints that drive the design

1. **Static only.** GitHub Pages. No server, no SSR, no API of our own.
2. **Strict CSP, no CDN.** Per `security-and-access.md` §5, `script-src 'self'` — every asset
   is self-hosted and committed. This rules out pulling a framework from a CDN, and it exists
   because a write-capable PAT lives on this origin.
3. **Untrusted upstream strings.** Titles/companies are third-party. Text nodes only, never
   `innerHTML`.
4. **Must not lag.** ~2,000 rows today, plausibly ~10,000 within two years given measured
   growth (+505 rows in one month).
5. **Two data planes.** Public problem data over plain `fetch`; personal data over the GitHub
   API with a token that may be absent, expired, or offline.

## 2. Stack

| Concern | Choice | Why |
| --- | --- | --- |
| Framework | **Preact + HTM**, vendored (~4 KB gz) **(D15)** | No CDN (CSP forbids it), tiny, JSX-free so no transpile step |
| Build | **None** — plain ES modules | Boring. Add `esbuild` only if the app outgrows it |
| Search | **Hand-rolled inverted index**, prebuilt at sync time | See §5 — beats shipping a search library |
| Virtualisation | Hand-rolled windowing (~80 lines) | Only real requirement is fixed-height rows |
| State | Plain module store + IndexedDB cache | No state library needed at this scale |
| Styling | Single hand-written CSS file, CSS custom properties | Light/dark via `prefers-color-scheme` |

Total shipped JS target: **< 40 KB gzipped**.

> **DECIDED (D15): Preact + HTM, vendored, no build step.** React/Vite would add a toolchain
> for no benefit at this size, and every dependency is a file we must vendor anyway because the
> CSP that protects the PAT forbids CDN scripts.

## 3. Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  Slipstream          [ search…                    ]   ⟳ synced 06:12 │
│                                                        ● 12 new today │
├────────────────┬─────────────────────────────────────────────────────┤
│ FILTERS        │  1,944 problems · 37 shown                sort ▾    │
│                │ ┌─────────────────────────────────────────────────┐ │
│ Status         │ │ ● Amazon        Buy Volumes                     │ │
│  ☐ todo    12  │ │   Coding · updated Nov 23 2024 · seen Aug 20     │ │
│  ☐ attempted 5 │ │   [todo ▾] ★★★☆☆  ↗ practice   ✎ notes           │ │
│  ☐ solved  31  │ ├─────────────────────────────────────────────────┤ │
│  ☐ revisit  8  │ │ ● Airtable/Meta  Design a Backend Search Engine  │ │
│  ☐ untracked   │ │   System design · updated Aug 16 2026  🔥NEW     │ │
│                │ │   [— ▾]     ☆☆☆☆☆  ↗ practice   ✎ notes         │ │
│ Format         │ ├─────────────────────────────────────────────────┤ │
│  ☐ Coding 1735 │ │ …virtualised…                                   │ │
│  ☐ System d 158│ └─────────────────────────────────────────────────┘ │
│  ☐ LLD      29 │                                                     │
│  ☐ AI cod   20 │                                                     │
│  ☐ SQL       2 │                                                     │
│                │                                                     │
│ Company     ▾  │                                                     │
│  [filter…    ] │                                                     │
│  ☐ Amazon  369 │                                                     │
│  ☐ Google   99 │                                                     │
│  ☐ IBM      83 │                                                     │
│  … 230 more    │                                                     │
│                │                                                     │
│ First seen  ▾  │                                                     │
│  ○ today       │                                                     │
│  ○ 7 days      │                                                     │
│  ○ 30 days     │                                                     │
│  ○ all         │                                                     │
│                │                                                     │
│ Tags        ▾  │                                                     │
│ [clear all]    │                                                     │
└────────────────┴─────────────────────────────────────────────────────┘
```

Views: **Browse** (above), **What's new** (§7), **Stats** (optional, §11).

## 4. Filters

| Filter | Control | Source | Notes |
| --- | --- | --- | --- |
| Free text | Search box | title + company | §5 |
| Personal status | Multi-select checkbox | personal layer | Includes `untracked` |
| Format | Multi-select | upstream | The 5 measured values |
| Company | Searchable multi-select | upstream | 233 tokens — needs its own filter box |
| First seen | Radio: today / 7d / 30d / all | our `first_seen` | Not upstream's `Updated` |
| Upstream updated | Date range (collapsed) | upstream | Secondary |
| Tags | Multi-select | personal layer | Union of user tags |
| Difficulty | Range | personal layer | Only if rated |
| Show removed | Toggle **(D17)** | tombstones | Rows I have personal data on are shown by default and badged "removed upstream"; the rest are hidden behind the toggle |

**Semantics:** AND across filter *groups*, OR within a group. Facet counts reflect other
active filters. All state is serialised to the URL query string so a filtered view is
bookmarkable and shareable across devices.

**Role type is deliberately absent as an upstream facet** — upstream has no such field
(PRD §4.1). Per **D1** it appears only as an optional **personal tag**, grouped with Tags and
visually marked as my own annotation, so it can never be mistaken for upstream data. It starts
empty and stays sparse; that is expected and honest.

## 5. Search — performance

Requirement: no perceptible lag on ~2,000 rows, headroom to ~10,000.

**Approach: prebuilt inverted index, shipped as `index.json`.**

At sync time, tokenize `title` + `companies`, lowercase, strip punctuation, and emit
`{token: [rowIdx,…]}` plus a prefix map for tokens ≥3 chars. Measured corpus is small — 1,944
titles averaging ~5 words — so the index is on the order of tens of KB gzipped.

At query time: tokenize input, intersect posting lists, AND across terms, prefix-match the
final term for as-you-type. Then apply facet filters over the resulting index set.

Why not a library: MiniSearch/Lunr/Fuse would each be a vendored dependency under the no-CDN
CSP, and all are heavier than a purpose-built index over 5-word strings. A hand-rolled
intersection over sorted arrays is microseconds here.

**Budgets:**

| Action | Budget |
| --- | --- |
| Keystroke → repaint | < 50 ms (target < 16 ms) |
| Filter toggle → repaint | < 50 ms |
| Cold load → interactive | < 1.5 s on 3G |
| Payload (data + index + app, gz) | < 250 KB |

**Techniques:** virtualised list (render ~40 visible rows of 1,944); filter over `Int32Array`
index sets, not object arrays; debounce input 120 ms; `content-visibility: auto` on rows;
never re-parse JSON after first load.

Fallback if scale ever demands it: shard `problems.json` by format and lazy-load. Not needed
at 1,944 rows; documented as a threshold (~10,000).

## 6. Rendering rules

- **Every upstream string is set via `textContent`.** No `innerHTML`, ever.
- Outbound links: `https:` only, `rel="noopener noreferrer"`, `target="_blank"`.
- Multi-company rows render each company as a separate chip (using the resolved company list
  from the parser, so `Zomato / Eternal` is **one** chip, not two).
- 🔥/🆕 are **recomputed client-side** from `upstream_updated` — upstream's markers are
  stripped at parse time because they are derived, not data.
- Distinguish clearly: **"first seen"** (ours) vs **"updated"** (upstream's sighting date).
  These mean different things and conflating them would mislead.
- Removed/tombstoned rows: struck through, muted, hidden by default, with a "removed upstream
  on DATE" note — never silently disappeared.

### 6.1 Open links

The upstream link goes to fastprep.io, which asks for an account before showing the question,
so it is never the primary action. The detail panel offers, in order:

1. **Solve on LeetCode ↗** when `origins.json` holds a confident match — labelled
   *LeetCode Premium* when the target is paywalled, because a link that swaps one sign-in
   wall for another has to say so.
2. **Find it on the web ↗** otherwise — a search seeded with the title, first company, and
   `leetcode` or `interview question` depending on format. Built client-side; the artifact
   carries only real matches.
3. **Source ↗** always, styled quietly. It is the only place the question is guaranteed to
   exist verbatim, so it is demoted rather than dropped.

`origins.json` is loaded optionally: a missing or stale one degrades to the search fallback
rather than breaking the panel.

In the list, a resolvable row carries a small `LC` badge (tooltip: LeetCode's own title for it),
and the sidebar offers a **Where I can solve it → On LeetCode** filter with a live count. The
badge is styled quietly on purpose: it marks the ~5% that have a direct link, and must not read
as a defect on the 95% that simply have no original anywhere else.

Where the two titles differ — upstream retitles freely — the panel spells out *"Same question on
LeetCode as X"*, so the match is checkable rather than something you have to take on trust.

## 7. "What's new" view

Reads `data/changes/latest.json`, grouped by change type:

- **Added** (N) — new problems, with company/format, one-click "mark todo".
- **Removed** (N) — tombstoned; highlighted if I had personal data on them.
- **Retitled** (N) — old → new title, same problem.
- **Relinked** (N) — URL changed; flags any that needed manual alias confirmation.
- **Company changed** (N) — measured at 15/month.

A date picker walks back through `changes/`. A badge in the header shows today's added count.
Ambiguous relinks surface here as an explicit **"confirm these are the same problem"** prompt
rather than being auto-merged.

## 8. Personal layer interactions

Inline on each row, no modal for the common case:

- **Status** — cycling control / dropdown: `— · todo · attempted · solved · revisit`.
- **Difficulty** — 5-star, clearable. (My rating; upstream has none.)
- **Notes** — expandable textarea. **Plain text (D18)**, stored and rendered as text. No
  markdown rendering, so no sanitizer sits in the path of a page that holds a write token.
- **Solution link** — URL input, validated `https:`.
- **Tags** — free-text chips with autocomplete over existing tags.

### 8.1 Save pipeline

```
edit → optimistic UI update → IndexedDB write (immediate)
     → debounce 10 s idle
     → GET current blob SHA → PUT contents API with that SHA
        ├─ 200 → store new SHA, mark "saved 12:04"
        └─ 409 → GET remote, per-ID three-way merge, retry once, else prompt
```

Never blind-overwrites. Per-ID merge means two devices editing *different* problems always
merge cleanly; only the same field on the same problem can conflict.

### 8.2 Token and connection states

| State | UI |
| --- | --- |
| No token | Banner: "Personal tracking is read-only. [Connect]" — browsing works fully |
| Token valid | Quiet "synced HH:MM" indicator |
| Token expired / 401 | Persistent banner, edits still cached locally, "Reconnect" |
| Offline | "Offline — N changes pending", queue flushes on reconnect |
| Merge conflict | Inline diff, "keep mine / keep theirs / keep both in notes" |

Edits **never** block on the network. IndexedDB is the write-through cache, so a lapsed token
or a flight offline loses nothing.

**Setup flow:** a `/connect` panel explains exactly which token to create — fine-grained,
`slipstream-personal` only, Contents read+write, **90-day expiry (D13)** — with a link to the GitHub
token page and a **"Forget token"** button. Mirrors `security-and-access.md` §3.1 so the two
docs cannot drift.

## 9. Accessibility and interaction

- Full keyboard path: `/` focus search, `j`/`k` move, `s` cycle status, `Enter` open problem,
  `Esc` clear. Discoverable via `?`.
- Real `<table>` semantics or ARIA grid roles on the virtualised list; virtualisation must not
  break screen readers (`aria-rowcount` on the full set).
- Visible focus rings, WCAG AA contrast, status conveyed by **text/shape as well as colour**.
- `prefers-reduced-motion` respected.

## 10. Responsive

- **≥1024 px** — sidebar + list as drawn.
- **640–1024 px** — filters collapse to a top drawer.
- **<640 px** — single column, cards; filters in a sheet; sticky search. Usable one-handed for
  triage on a phone.

## 11. Out of scope for v1

Charts/stats dashboard · spaced repetition · in-browser code editor · cross-referencing
LeetCode · export to Anki · sharing. All are additive later.

## 12. Ratified decisions affecting this document

| # | Decision | Where it lands |
| --- | --- | --- |
| D1 | Role type is a **personal tag only**, never an upstream facet | §4 |
| D4 | Practice links surfaced on every row | §6, §6.1 |
| D15 | **Preact + HTM**, vendored, no build step | §2 |
| D16 | **Browse is the default view**; header badge shows today's added count and links to What's new | §3, §7 |
| D17 | Removed rows: shown by default **only** where I have personal data, badged "removed upstream"; others behind a toggle | §4, §6 |
| D18 | Notes are **plain text** | §8 |
| D19 | **IndexedDB cache only** — no service worker / PWA in v1 | §8.1 |
| D20 | **Compact rows by default**; selecting a row expands it into the roomier detail + edit panel | §3, below |

### D20 — density

The §3 sketch shows the *expanded* state. The default is a compact single-line row:

```
● Amazon              Buy Volumes                     Coding    Nov 23 2024   [todo ▾] ★★★☆☆
● Airtable · Meta     Design a Backend Search Engine  Sys des   Aug 16 2026 🔥 [— ▾]   ☆☆☆☆☆
```

Selecting a row expands it in place to reveal notes, solution link, tags, and the full date
pair (first seen vs upstream updated). Rationale: with ~2,000 rows the dominant action is
*scanning*, and compact rows put roughly three times as many candidates on screen. Fixed row
height is also what makes the virtualiser in §5 simple.

A density toggle is deferred — ship one good default first.
