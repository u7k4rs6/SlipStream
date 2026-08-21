# Slipstream — Technical Architecture

**Status:** Decisions ratified 2026-08-20 · Ready to build
**Date:** 2026-08-20 · Decision log in `PRD.md` §10.
**Upstream surveyed:** `perixtar/Tech-OA-Interview-Questions` (repo id `687227685`, default
branch `master`) @ commit `d163035c2bb54ae9a5f14182ff6d756e6cdfecd0`, 2026-08-18 00:28 UTC.
README sha256 `42c0684fca770844ef1242f14baaa17700fe02d8b7264724cb03135c92fc7c7f`.

---

## 1. Step 0 findings (measured, not assumed)

### 1.1 Repository shape

```
README.md                     443,709 B · 2,083 lines · 1,944 data rows
formats/
  coding.md                   366,483 B · 1,735 rows
  system-design.md             38,860 B ·   158 rows
  low-level-design.md           7,422 B ·    29 rows
  ai-coding.md                  5,134 B ·    20 rows
  sql.md                          676 B ·     2 rows
scripts/
  refresh-freshness.py          sorts table, recomputes 🔥/🆕 markers, enforces size cap
  sync-practice-formats.py      pulls FastPrep APIs, regenerates README + formats/
  test_sync_practice_formats.py upstream's own unit tests
assets/
  company-domains.json        156 entries, company → domain
.github/workflows/sync-question-bank.yml   cron "17 * * * *"  (HOURLY, not daily)
CONTRIBUTING.md
(no LICENSE file — GitHub API reports license: null)
```

`formats/` is **not** a structured export. There is **no CSV and no JSON** anywhere in the
repo except `assets/company-domains.json`. `formats/*.md` are markdown projections of the
same table: 1,735 + 158 + 29 + 20 + 2 = **1,944**, exactly the README row count.

### 1.2 Table columns and schema consistency

Current README header (line 123):

```
| Company | OA / Interview Question | Format | Practice | Updated |
| :--     | :--                     | :--    | :-:      | :--     |
```

**Within this snapshot the schema is perfectly consistent:** all 1,944 data rows have exactly
5 cells; all 1,944 question cells match `[title](url)` exactly; all 1,944 company cells are
`**bold**`-wrapped.

**Across time it is not.** Distinct headers in git history:

| First seen | Header | Cols |
| --- | --- | --- |
| 2023-09-04 | `Company OA \| Last Updated Time` | 2 |
| 2023-09-04 | `Company \| OA Question \| Last Updated Time` | 3 |
| 2023-11-13 | `… \| Practice (Beta) \| Last Updated Time` | 4 |
| 2024-09-26 | `… \| Practice (Beta) \| Uploaded Time` | 4 |
| 2025-03-23 | `… \| Practice (Beta) \| Updated Time` | 4 |
| 2026-07-09 | `… \| Practice \| Updated Time` | 4 |
| 2026-07-09 | `… \| Practice \| Updated` | 4 |
| 2026-07-27 | `Company \| OA / Interview Question \| Practice \| Updated` | 4 |
| 2026-07-31 | `… \| Practice format \| Practice \| Updated` | 5 |
| 2026-07-31 | `… \| Format \| Practice \| Updated` | 5 |

**Ten schema revisions; four in the last six weeks.** Upstream's own code carries
`OLD_TABLE_HEADER` and `LEGACY_TABLE_HEADER` constants — it expects to keep migrating. Any
parser pinned to one header will break, probably within weeks. This is the single most
important design input.

`formats/*.md` use a **different, 4-column** schema (no Format column — implied by filename):
`| Company | OA / Interview Question | Practice | Updated |`.

### 1.3 Column semantics

- **Company** — bold. 30 rows list multiple companies joined by ` / `. 2 rows are the
  sentinel `**Unattributed**`. 233 distinct tokens under naive splitting, but see §3.2.
- **OA / Interview Question** — `[title](url)`. 100% of links are `www.fastprep.io`. Route
  namespaces: `/problems/` (1,737), `/system-design/` (158), `/low-level-design/` (29),
  `/project-coding/` (20).
- **Format** — exactly 5 values: `Coding` 1,735 · `System design` 158 · `Low-level design` 29
  · `AI coding` 20 · `SQL` 2. **Not inferable from the URL**: SQL and Coding rows both live
  under `/problems/`.
- **Practice** — `[![Practice][p]](url)`, a badge whose URL always duplicates the question
  URL. **Zero information.** Ignore it (but count it — upstream's validator requires exactly
  two URLs per row).
- **Updated** — `[🔥|🆕 ]Mon DD, YYYY`. Upstream's README states this is "the latest reported
  sighting when available, otherwise the first public sync date". **It is not a creation
  date and it moves.** Markers are purely derived: 🔥 ≤14 days, 🆕 ≤45 days, computed at sync
  time from that date (`refresh-freshness.py`, `FIRE_DAYS=14, NEW_DAYS=45`). Distribution:
  1,416 bare · 436 🆕 · 92 🔥. **Strip and recompute; they carry no independent signal.**

**Row order is not stable.** `refresh-freshness.py` re-sorts the whole table newest-first on
every run. Line numbers are meaningless as identity.

### 1.4 Commit cadence (last 90 days)

- **160 commits across 50 distinct days** in the trailing 90 days.
- Recent 30 days: commits on **26 of 28** days — effectively daily or better.
- Monthly: 2026-04 → 18, 2026-05 → 30, 2026-06 → 40, 2026-07 → 56, 2026-08 → 58 (partial).
- The repo was **dormant** 2025-07 → 2026-02 (1 commit in 7 months), then reactivated.
- Workflow cron is `17 * * * *` — **hourly**, committing only when content changed.

Growth, measured by monthly snapshot: 1,051 rows (2025-07) → 1,293 (2026-07-02) → 1,741
(2026-08-01) → 1,944 (now). **Accelerating.**

### 1.5 Stable identifier — the key question

**There is no published per-problem ID.** No numeric key, no data attribute, no anchor.

**But the URL slug is an excellent derived ID.** Measured slug churn between monthly
snapshots (schema-agnostic parse across full history):

| Transition | kept | added | removed | retitled | relinked |
| --- | --- | --- | --- | --- | --- |
| 2025-06-01 → 2025-07-08 | 1,025 | 26 | 0 | 0 | 0 |
| 2026-05-04 → 2026-06-01 | 1,096 | 59 | 0 | 1 | 0 |
| 2026-06-01 → 2026-07-02 | 1,154 | 139 | 1 | 4 | 0 |
| 2026-07-02 → 2026-08-01 | 1,236 | 505 | 57 | 2 | 4 |

Slugs are highly persistent. Titles change **under a stable slug** (retitles), which is
exactly the case that would orphan title-keyed data — confirming the slug is the right key.

One caveat: only **6.2%** of the original 2023-11 slugs survive to today. That is **not**
ongoing instability — it was a one-time host migration, `fastprep.gitbook.io` →
`www.fastprep.io`, completed by 2024-03. Since then the host has been constant. A future host
migration would look the same, which is why we need aliases (§3.4).

**Decision: `id = sha1(namespace + "/" + slug)[:12]`, where namespace/slug come from the URL
path.** Human-readable secondary key `problems/amazon-buy-volumes` retained for debugging.

### 1.6 Other findings

- **Upstream is ~2 weeks from breaking its own README.** `README_MAX_BYTES = 500_000` is
  hard-coded in *both* scripts and `sys.exit`s / returns 2 above it. Current size 443,709 B →
  **56,291 B headroom ÷ 224 B average row ≈ 251 rows.** Last month added 505. Upstream will
  be *forced* to split or truncate the README, very soon. **Architectural consequence: do not
  make README the sole source of truth.**
- **No licence.** `license: null`, no LICENSE file. Default copyright applies. See
  `security-and-access.md` §4.
- **The repo has been renamed once.** Badges still point at `perixtar/2026-Tech-OA-by-FastPrep`,
  which now 301s. Pin the immutable repo id `687227685`.
- **Duplicate rows exist.** 12 rows share 6 URLs — 6 exact byte-duplicates, 6 same-URL /
  different-title pairs.
- **`assets/company-domains.json` is a usable vocabulary** — and critically, it keys
  `"Zomato / Eternal"` as a single entry, proving the slash-ambiguity is real and giving us
  the data to resolve it. Covers 144 of the 210 curated names.
- Raw fetch works unauthenticated and returns a strong `ETag` + `cache-control: max-age=300` —
  enabling cheap conditional requests.

---

## 2. System overview

Three isolated planes. The critical property is that **the sync plane cannot write to the
personal plane.**

```
┌─ UPSTREAM (read-only, public) ────────────────────────────────┐
│  github.com/perixtar/Tech-OA-Interview-Questions              │
│  raw README.md + formats/*.md + assets/company-domains.json   │
└───────────────────────────┬───────────────────────────────────┘
                            │ daily cron · conditional GET (ETag)
                            ▼
┌─ SYNC PLANE (GitHub Actions, write: data/ only) ──────────────┐
│  fetch → parse (dual source) → reconcile → normalize          │
│  → diff vs previous → write data/ + CHANGELOG.md              │
│  GUARDRAILS: header assert · row-count floor · schema tests   │
└───────────────────────────┬───────────────────────────────────┘
                            ▼
┌─ PUBLIC REPO: slipstream ─────────────────────────────────────┐
│  data/meta.json        upstream SHA + file hashes consumed    │
│  data/problems.json    normalized dataset                     │
│  data/archive.json     permanent tombstone archive            │
│  data/changes/*.json   per-day diffs                          │
│  data/origins.json     login-free link per resolvable problem │
│  CHANGELOG.md                                                 │
│  site/            static frontend → GitHub Pages              │
└───────────────────────────┬───────────────────────────────────┘
                            │ browser fetch (public)
                            ▼
┌─ BROWSER ─────────────────────────────────────────────────────┐
│  loads problems.json + changes  ⟵ public                      │
│  loads/saves personal.json      ⟷ GitHub API + fine-grained   │
│                                   PAT (see §7)                │
└───────────────────────────┬───────────────────────────────────┘
                            ▼
┌─ PRIVATE REPO: slipstream-personal ───────────────────────────┐
│  personal.json    status · difficulty · notes · solution · tags│
│  NEVER written by the sync job. Git history = free undo.      │
└───────────────────────────────────────────────────────────────┘
```

## 3. Parsing

### 3.1 Dual-source strategy

Because the README will imminently hit its size cap, and because `formats/` is only three
weeks old, **neither source is safe alone.** Parse both:

1. **Primary: `formats/*.md`** — five smaller files, uncapped, format implied by filename.
2. **Secondary: `README.md`** — the historically canonical table, carries the Format column.
3. **Reconcile.** Union by derived ID. Expect exact agreement (today: 1,944 = 1,944).
   - **Any** divergence → take the union and log a warning (today it is exactly 0, so any
     drift is signal, not noise).
   - Divergence above **max(25 rows, 1% of total)** **(D9)** → **fail the sync**, open an
     issue, keep yesterday's data.
   - Either source missing entirely → proceed on the other, warn loudly.

This survives *either* the README being split *or* `formats/` being deleted.

### 3.2 Company splitting — the `Zomato / Eternal` problem

Naive `split(" / ")` invents a phantom company "Eternal" and corrupts the company facet.
Resolution, in order:

1. Build a vocabulary from upstream's own curated 210-name list (the `<details>` block) plus
   the 156 keys of `assets/company-domains.json`. Both contain `"Zomato / Eternal"` verbatim.
2. **Longest-match-first** against that vocabulary before splitting on the remaining ` / `.
3. Canonicalize case-insensitively (`Infosys`/`infosys`, `MathWorks`/`Mathworks`) to one
   display name.
4. `Unattributed` → empty company list, flagged, never a facet entry.
5. Unknown token → keep verbatim, emit a warning (it may be a genuinely new company).

### 3.3 Normalized record

```jsonc
{
  "id": "a3f8c21b9e04",                    // sha1(namespace/slug)[:12] — stable
  "key": "problems/amazon-buy-volumes",    // human-readable
  "title": "Buy Volumes",
  "url": "https://www.fastprep.io/problems/amazon-buy-volumes",
  "companies": ["Amazon"],
  "format": "Coding",
  "upstream_updated": "2024-11-23",        // markers stripped
  "first_seen": "2026-08-20",              // OUR observation — never upstream's
  "last_seen": "2026-08-20",
  "state": "active",                       // active | removed
  "aliases": [],                           // prior ids after a relink
  "source": ["formats/coding.md", "README.md"],
  "upstream_sha": "d163035c…"
}
```

`first_seen` is ours because upstream's `Updated` is a *sighting* date that moves in both
directions and is unusable as "when did this appear".

### 3.4 Diff and alias resolution

Compare today's ID set against yesterday's:

- **added** — new ID. `first_seen` = today.
- **removed** — ID absent. **Tombstone** (`state: "removed"`), never delete. Personal data
  survives. 57 removals in one month makes this load-bearing.
  **Retention (D7):** a tombstone stays in `problems.json` forever if any personal entry
  references its ID; otherwise it ages out after **180 days**. Every tombstone is appended
  permanently to `data/archive.json` regardless, so nothing is ever truly lost.
- **retitled** — same ID, different title. Personal data unaffected (this is the whole point
  of slug-keying).
- **relinked** — URL changed → new ID. Attempt to match a just-removed ID whose
  `(title, companies, format)` is identical. On confident match: write an alias, migrate the
  personal entry, record `relinked` rather than add+remove.
- **recompanied** — company set changed (15 rows in one month).

**DECIDED (D10):** a relink is auto-merged **only** on an exact `(title, companies, format)`
match. Anything less certain is never auto-merged — it is reported for manual confirmation in
the What's-new view. Silently merging the wrong pair would corrupt personal data, which is the
one failure this whole design exists to prevent.

### 3.5 Guardrails (FR-7)

- Header assertion against a known-good list including all 10 historical variants. Unknown
  header → **fail**, do not emit zero rows.
- Row-count floor **(D9)**: a drop of **more than 10%** aborts the sync and opens an issue.
- Unclassified-row check: any row that parses to a null format fails CI (mirrors upstream's
  own `unclassified row` guard).
- Zero-row result is always a failure, never a valid "everything was deleted".

## 4. Test strategy

Fixtures are **real upstream bytes**, committed and pinned:

| Fixture | Purpose |
| --- | --- |
| `readme@d163035c.md` (2026-08-18) | Current 5-col schema; asserts exactly 1,944 rows |
| `readme@2026-07-27.md` | 4-col `OA / Interview Question` schema |
| `readme@2025-03-23.md` | 4-col `Practice (Beta) / Updated Time` |
| `readme@2024-09-26.md` | 4-col `Uploaded Time` |
| `readme@2023-11-13.md` | 3-col, gitbook.io hosts |
| `formats/*@d163035c.md` | 4-col format-page schema |
| synthetic `add/remove/retitle/relink` pair | Diff classifier |
| synthetic `unknown-header.md` | **Must fail** |
| synthetic `truncated.md` | **Must fail**, personal layer untouched |

Property tests: parse is idempotent; ID is stable under re-sorting; personal file is
byte-identical after any parse failure.

## 5. Frontend data contract

Sync emits, into `site/data/`:
- `problems.json` — full dataset (~2,000 records, est. 300–400 KB raw, ~60 KB gzipped).
- `index.json` — prebuilt search index (see `frontend-spec.md`).
- `changes/YYYY-MM-DD.json` + `changes/latest.json`.
- `meta.json` — upstream SHA, sync timestamp, row counts, warnings.
- `origins.json` — problem ID → a link that opens without an account (see §5.1).

At ~10,000 rows this is still ~2 MB raw / ~300 KB gzipped — acceptable. Beyond that, shard by
format. Not needed now; noted as a threshold.

### 5.1 Origin links

Every upstream URL points at fastprep.io, which asks for an account before it will show the
question — so following the link the dataset carries is not, on its own, a way to solve
anything. `origins.py` resolves what it can against LeetCode's public catalogue and emits
`origins.json`, keyed by problem ID.

Three properties are deliberate:

- **Separate artifact, not a field on `Problem`.** It depends on a third party moving on its
  own schedule, so it must never be able to fail or stall the upstream sync; and a new field
  would rewrite all ~1,900 records the day it landed, burying that day's real diff.
- **Precision over coverage.** 103 of 1,932 rows (5.3%) resolve. The rest are
  fastprep-original OA write-ups that exist nowhere else under any title. Matching widens in
  four steps — exact title, stopword-insensitive token set, the same with upstream's
  abbreviations and plurals folded in (`Num of Good Pairs` / `Number of Good Pairs`), then
  minus a leading imperative verb (`Is Happy Number` / `Happy Number`) — and *every* step
  requires a unique hit. An ambiguous title resolves to nothing, because a wrong link sends
  you to confidently solve the wrong question and file notes against it.
- **Only `Coding` and `SQL` are eligible.** Without that gate, `Design a Web Crawler` (system
  design) resolves to LeetCode 1236 `Web Crawler`, an unrelated coding exercise that happens
  to share a name. The gate costs nothing today — no non-coding row matched anyway — and
  closes the whole class.
- **Unmatched rows get no entry.** The client derives a seeded web search from the title it
  already has; baking ~1,800 search URLs would be a large artifact carrying no information.

LeetCode Premium questions are linked but flagged, since premium is another sign-in wall and a
link that swaps one wall for another while looking like the way past it is worse than none.

**Rejected: slug matching.** Stripping the company prefix off upstream's URL slug and comparing
it to LeetCode's resolves ~47 more rows, and roughly a quarter of them are wrong — `Shopping
and Billing` → `Palindromic Substrings`, `Tool Changer` → `Split Array Largest Sum`, `Design an
Authenticated Page Presence Counter` → `Counter`. Scoring the candidates by title overlap does
not separate them: upstream's questions are frequently deliberate *variants* of a LeetCode
problem, so `Longest Palindromic Subarray` scores 0.67 against `Longest Palindromic Substring`
and `Min Cost To Collect All Points` scores 0.80 against `Min Cost to Connect All Points`. No
similarity threshold can know the difference. The measurable win was smaller and safer: those
misses were mostly *lexical* variants, which is what steps 3 and 4 above now catch — 20 further
rows, every one verified by hand, with none of the false positives.

One trap worth recording: `and` must not be treated as a stopword. LeetCode has `Maximum AND
Sum of Array`, where the AND is the bitwise operator; folding it away matched that question to
an upstream row about a plain maximum sum.

## 6. Scheduling

Daily cron (`0 6 * * *` UTC) plus `workflow_dispatch`. Upstream commits hourly, but its
*content* changes far less often, and a daily diff matches the "what's new today" use case.
Conditional GET on ETag makes a no-op run nearly free. **DECIDED (D6): daily.** Hourly remains a one-line change if the daily diff ever feels too
coarse.

Idempotence: the job computes the new dataset, compares to committed state, and **exits
without committing if identical.**

## 7. Personal-state persistence — evaluation (Q2)

Requirement: survives upstream updates, syncs across devices, free, boring, never destroyed by
a bad parse.

### Option A — JSON committed via the GitHub API from the browser (fine-grained PAT)

The site reads/writes `personal.json` in a **separate private repo** using
`PUT /repos/{owner}/{repo}/contents/personal.json` with a fine-grained PAT held in browser
`localStorage`.

**Pros** — Free, permanently. No extra vendor, no service to wake up. Git history is a free,
complete undo log. Physically separate repo makes "sync can never touch personal data" a
structural guarantee, not a convention. Blob SHA gives optimistic concurrency for free.
Trivially exportable — it is just a JSON file.

**Cons** — The PAT sits in `localStorage` on a GitHub Pages origin; any XSS on that origin
can exfiltrate it (blast radius analysed in `security-and-access.md` §3). Manual token
rotation (max 1-year expiry). Whole-file read/write, so concurrent edits on two devices are
last-write-wins unless SHA-checked. Every save is a commit — noisy history (mitigate by
debouncing).

### Option B — Hosted DB (Supabase / Turso free tier)

**Pros** — Real auth, no token pasting. Row-level writes, so no whole-file conflicts.
Proper multi-device concurrency. Queryable.

**Cons** — Adds a vendor and an account. Supabase free projects **pause after ~7 days of
inactivity** — precisely the failure mode for a study tracker used in bursts before
interviews. Free tiers change. Backup/export becomes my problem. The anon key still ships to
the browser, so it is not obviously *safer* — just differently shaped. More moving parts than
"a JSON file in git", against the "keep it boring" constraint.

### Option C — Browser-local only (IndexedDB)

Free, zero secrets, zero risk — and **fails the cross-device requirement outright.** Rejected,
but worth keeping as an offline cache layer in front of A.

### Recommendation: **Option A**, with these conditions

1. Personal data lives in a **separate private repo** (`slipstream-personal`), not the public
   Pages repo. Notes stay private and the separation is physical.
2. PAT is **fine-grained**, scoped to that **one repo**, with **Contents: read+write** and
   nothing else. Explicit expiry.
3. Optimistic concurrency: send the known blob SHA; on 409, fetch, three-way merge per-ID,
   re-submit. Never blind-overwrite.
4. IndexedDB write-through cache so the app works offline and survives a token lapse.
5. Debounce commits (~10 s idle) to avoid one commit per keystroke.

Chosen because it is the only option that is free *and* stays free, has no service that can
pause, gives version history for nothing, and structurally guarantees the sync job cannot
corrupt personal state. The XSS exposure is real but bounded — one private repo containing
study notes — and is analysed in the security doc.

**Migration path:** the schema is ID-keyed records. Moving to Option B later is a loader swap,
not a redesign. Not a one-way door.

> **DECIDED (D2, D3): Option A, with the personal layer in a private repo.** All five
> conditions above are binding requirements, not suggestions — in particular the separate
> private repo (so the sync job holds no credential that can reach personal data) and
> SHA-based optimistic concurrency (never blind-overwrite).

## 8. Stack

| Layer | Choice | Why |
| --- | --- | --- |
| Sync + parse | Python 3.12, stdlib only | Matches upstream's own tooling; no dependency drift |
| Tests | `pytest` + pinned fixtures | Only dev dependency |
| CI/CD | GitHub Actions | Free, already the scheduler |
| Hosting | GitHub Pages | Free, static |
| Frontend | See `frontend-spec.md` | — |
| Personal store | GitHub Contents API (private repo) | §7 |

Everything is free at this scale. No servers, no database, no paid tier.

## 9. Repository layout (proposed)

```
slipstream/                  (public)
├─ .github/workflows/sync.yml
├─ docs/
├─ src/slipstream/           parser · normalizer · differ · emitter
├─ tests/fixtures/upstream/  pinned real snapshots
├─ data/                     problems.json · archive.json · changes/ · meta.json · origins.json
├─ site/                     static frontend
└─ CHANGELOG.md

slipstream-personal/         (private)
└─ personal.json
```

## 10. Ratified decisions affecting this document

| # | Decision |
| --- | --- |
| D2 | Personal state via fine-grained PAT → GitHub Contents API (§7, Option A) |
| D3 | Personal layer lives in a **private** repo, `slipstream-personal` |
| D6 | **Daily** sync at `0 6 * * *` UTC + `workflow_dispatch` (§6) |
| D7 | Tombstones: forever if personal data references them, else 180 days; all archived permanently (§3.4) |
| D8 | **No verbatim `mirror/`.** Store the upstream commit SHA + normalized data only |
| D9 | Abort on >10% row drop; abort on source divergence above max(25 rows, 1%) (§3.1, §3.5) |
| D10 | Relink auto-merge only on exact `(title, companies, format)` match (§3.4) |
| D15 | Frontend: Preact + HTM, vendored (`frontend-spec.md` §2) |

### D8 changes the repo layout

§9's layout above reflects this: there is no `mirror/` directory. Instead, `data/meta.json` records the upstream commit
SHA, the file sha256s consumed, the sync timestamp, row counts, and any warnings — which is
reproducible (`git show <sha>:README.md` against upstream reconstructs the input exactly) and
avoids committing ~440 KB of no-licence third-party text on every change.

> Note: pinned **test fixtures** are still committed verbatim, because a fixture that is not
> byte-exact is not a fixture. They are a handful of historical snapshots, not a rolling
> mirror, and they are the mechanism that makes an upstream format change fail loudly.
