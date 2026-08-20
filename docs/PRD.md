# Slipstream — Product Requirements

**Status:** Decisions ratified 2026-08-20 · Ready to build
**Date:** 2026-08-20 · All open questions resolved — see §10 Decision log.
**Upstream surveyed at:** `perixtar/Tech-OA-Interview-Questions` @ `d163035c` (2026-08-18)

---

## 1. Problem

The upstream repo is a single ~444 KB README containing one 1,944-row markdown table of
company OA / interview questions. It is genuinely useful and genuinely current — it syncs
**hourly** from FastPrep's catalogs — but as a personal study tool it fails in four ways:

1. **No personal state.** There is nowhere to record what I have attempted, solved, or want
   to revisit. The file is regenerated and re-sorted on every sync, so annotating it locally
   is impossible.
2. **No memory of change.** Rows are added, removed, retitled, and relinked continuously
   (measured: +505 / −57 in the month to 2026-08-01). Nothing tells me what is new since I
   last looked.
3. **Not browsable.** ~1,944 rows in one markdown table means Ctrl-F only. No filtering by
   company, format, recency, or personal status.
4. **Volatile ordering.** Rows are re-sorted newest-first on every sync, so position carries
   no information and cannot anchor anything.

## 2. Product goal

A personal, always-current tracker that mirrors upstream automatically, layers my own study
state on top, and never loses that state when upstream changes shape.

**Success = all four are true:**
- I open one page and see what is new since yesterday.
- I can filter ~2,000 rows to the ~20 I care about in under three seconds of interaction.
- My status/notes survive every upstream reformat, rename, and re-sort.
- The sync runs for months without me touching it, and fails *loudly* rather than silently.

## 3. Non-goals

- Not a public product. Single user. No accounts, no multi-tenancy, no sharing.
- Not a problem host. We never mirror problem *statements* — only company, title, link,
  format, date. (See `security-and-access.md` §4 for why this matters.)
- Not a scraper. Upstream is read exclusively through public GitHub. FastPrep's site and API
  are never fetched, despite upstream's scripts calling them.
- Not a code judge. No editor, no test runner. Solution links point at my own repo/gists.
- Not a contribution path back upstream.

## 4. What upstream actually provides

Verified against the real repo, not assumed. Full evidence in `technical-architecture.md` §2.

| Field | Available? | Notes |
| --- | --- | --- |
| Company | Yes | Bold cell, may list several companies separated by ` / ` |
| Problem title | Yes | Markdown link text |
| Link | Yes | 100% `www.fastprep.io`, four route namespaces |
| Format | Yes | `Coding` / `System design` / `Low-level design` / `AI coding` / `SQL` |
| Updated date | Yes | "latest reported sighting, else first public sync date" |
| **Role type (intern / new grad / full time)** | **NO** | **Does not exist. See §5.** |
| Difficulty | No | Not present upstream |
| Stable per-problem ID | Not published | Derivable from URL path — see §6 |

### 4.1 The role-type problem — blocking open question

The brief asks to filter by **role type (intern / new grad / full time)**. **Upstream carries
no role field, and never has.** Across the entire 1,944-row table the only occurrences of
those words are incidental prose inside a title, e.g.
`String Formation (Also for AI/ML Software Engineer Intern :)` — exactly **one** row.

There is no honest way to derive this column. Three options:

- **(A) Drop role filtering.** Filter by *format* instead (Coding / System design / LLD / AI
  coding / SQL), which upstream does provide and which correlates with interview stage.
- **(B) Make it a personal-layer field.** I tag rows with role type myself as I encounter
  them. Accurate but starts empty and stays sparse.
- **(C) Heuristic tagging.** Infer from title/company text. Coverage would be ~0.1%. Not
  recommended — it would look like data while being noise.

> **DECIDED (D1): A + B.** Format is the shipped facet. Role type exists only as an optional
> personal tag, starting empty, clearly labelled as my own annotation. We do **not** synthesise
> a role column from title text, and the UI never implies upstream has role data.

## 5. Users and use cases

Single user (repo owner). Primary loops:

- **Daily triage.** "What appeared since yesterday?" → open the diff view, mark interesting
  rows `todo`.
- **Company prep.** "I have an Amazon OA Thursday." → filter company = Amazon (369 rows),
  sort by recency, work down.
- **Format drill.** "I need system design reps." → filter format = System design (158 rows).
- **Resume work.** "What did I mark revisit?" → filter personal status.
- **Integrity check.** "Did the sync break?" → CI is red, or the changelog shows an
  implausible mass-delete.

## 6. Functional requirements

### FR-1 — Scheduled sync
- Daily GitHub Actions cron, plus manual `workflow_dispatch`.
- Reads upstream through public GitHub only (raw fetch or shallow clone). No credentials.
- **Idempotent:** re-running on an unchanged upstream produces zero commits.
- Records the exact upstream commit SHA consumed in every sync.
- Upstream pushes hourly; daily is a deliberate choice (see `technical-architecture.md` §6).

### FR-2 — Normalized dataset
Parse into a typed record per problem: `id`, `title`, `url`, `companies[]`, `format`,
`upstream_updated`, `first_seen`, `last_seen`, `status` (`active` / `removed`).

- `first_seen` is **our** observation date, not upstream's `Updated`, which means something
  different and moves backwards and forwards.
- Company cell splits into multiple companies — with a documented exception (§6.1).

### FR-3 — Stable derived ID
- ID derived from the URL path (`/problems/amazon-buy-volumes` → namespace + slug).
- Measured stable: 1,236 / 1,293 slugs survived the largest observed monthly churn.
- Alias mechanism so a relinked problem carries its personal data forward (FR-5).

### FR-4 — Personal layer
Fields: `status` (`todo` / `attempted` / `solved` / `revisit`), `difficulty` (1–5), `notes`
(free text), `solution_url`, `tags[]`, plus timestamps.

**Hard requirements:**
- Lives in its own file, keyed by derived ID. **Never** merged into mirrored content.
- The sync job has **no write path** to it. A parser crash cannot corrupt it.
- Entries persist for problems removed upstream (tombstoned, not deleted).
- Survives across devices.

> **DECIDED (D2): Option A** — `personal.json` in a separate **private** repo
> (`slipstream-personal`), written from the browser via the GitHub Contents API using a
> fine-grained PAT. Full evaluation and conditions in `technical-architecture.md` §7; token
> scoping and leak analysis in `security-and-access.md` §3.

### FR-5 — Daily diff
Classify each sync into: **added**, **removed**, **retitled** (same ID, new title),
**relinked** (same identity, new URL), **recompanied** (company set changed — measured: 15
rows in one month).

- Written to `CHANGELOG.md` (append-only, newest first) and a machine-readable
  `data/changes/YYYY-MM-DD.json`.
- Surfaced in the UI as a "What's new" view.
- A relink that is confidently matched writes an alias so personal data follows.

### FR-6 — Static frontend
GitHub Pages. Filters: company, format, date added, personal status, tags. Free-text search
across title + company. Must stay responsive at ~2,000 rows growing to ~10,000.
Full spec in `frontend-spec.md`.

### FR-7 — Fail loudly
- Parser test suite with fixtures pinned to real upstream snapshots (`d163035c` and
  historical schema variants).
- CI asserts the upstream table header matches a known-good list. An unknown header fails the
  build rather than silently yielding zero rows.
- Sync aborts and opens an issue if row count drops more than a configured threshold.

### 6.1 Known data hazards (measured, must be handled)

| Hazard | Evidence | Requirement |
| --- | --- | --- |
| Company slash ambiguity | `Zomato / Eternal` is **one** company; `Zomato / Eternal / Amazon` is **two** | Split using upstream's own 210-name company list + `assets/company-domains.json` (which keys `"Zomato / Eternal"` whole) as vocabulary — never naive `split('/')` |
| Case-variant companies | `Infosys` and `infosys` both listed; `MathWorks` / `Mathworks` | Case-insensitive canonicalization with a display-name map |
| Duplicate URLs | 12 rows share 6 URLs; 6 are byte-identical dupes, 6 are same-URL-different-title | Dedupe on ID; keep the newest `Updated`; log the collision |
| `Unattributed` company | 2 rows | Treat as a sentinel, not a company |
| Format not inferable from URL | SQL and Coding both live under `/problems/` | Read the Format column; do not infer from route |
| Fire/new emoji | 🔥 ≤14d, 🆕 ≤45d — **derived from the date** | Strip and recompute; carries no independent information |

## 7. Constraints

- Public GitHub reads only. No third-party scraping. No upstream credentials.
- Idempotent, re-runnable sync. Partial parse must never destroy the personal layer.
- Personal data in its own file, never merged with mirrored content.
- Pinned-fixture parser tests; upstream format change fails CI.
- Boring, free stack. No paid tier for normal operation.

## 8. Risks

| Risk | Likelihood | Evidence | Mitigation |
| --- | --- | --- | --- |
| **Upstream README hits its own 500 KB cap and is restructured** | **High — weeks away** | README is 443,709 B; upstream's script hard-fails above 500,000 B. Headroom ≈ 251 rows; last month added 505 | Parse `formats/*.md` as primary source (uncapped), README as cross-check |
| Upstream schema change | **High** | Header changed **10 times**, 4 of them in the last 6 weeks | Multi-schema parser + header assertion + pinned fixtures |
| `formats/` removed | Medium | Only introduced 2026-07-31 | Dual-source reconciliation; either source alone is sufficient |
| Upstream repo renamed/deleted | Medium | Already renamed once (`2026-Tech-OA-by-FastPrep` → current; old name 301s) | Pin immutable repo ID `687227685`; follow redirects; we hold a full mirror |
| Link rot to fastprep.io | Medium | Single host for 100% of links | Mirror metadata; never depend on the target resolving |
| Personal-layer write conflict | Low | Single user, multi-device | Optimistic concurrency on blob SHA (§ architecture) |
| **No upstream licence** | **Certain** | GitHub API reports `license: null`; no LICENSE file | See `security-and-access.md` §4 — affects what we may mirror |

## 9. Acceptance criteria

1. Sync runs unattended daily; re-run on unchanged upstream = no commit, exit 0.
2. Corrupting the upstream fixture fails CI; personal-layer file byte-identical after.
3. Personal entry survives an upstream retitle *and* relink of the same problem.
4. `CHANGELOG.md` correctly classifies a synthetic add/remove/retitle/relink fixture.
5. Frontend filters 2,000 rows with <100 ms interaction latency on a mid-range laptop.
6. Personal state set on device A is visible on device B without manual file copying.
7. All 1,944 current rows parse with zero unclassified rows.

## 10. Decision log

All questions raised at review are resolved. Ratified 2026-08-20.

| # | Question | Decision | Rationale |
| --- | --- | --- | --- |
| D1 | Role type (absent upstream) | Ship **format** as the facet; role type is an optional personal tag | Upstream has no role field in any of 1,944 rows; inventing one would be noise dressed as data |
| D2 | Personal-state storage | Fine-grained PAT → private repo via Contents API | Free permanently, git history as undo, and the sync job holds no credential that can reach it |
| D3 | Personal layer visibility | **Private** repo, separate from the public site repo | Notes may be candid; separation is structural, not procedural |
| D4 | Surface "Practice" links | **Yes** | The outbound link is the attribution; traffic keeps flowing to the source |
| D5 | Licence posture | **Metadata only** — company, title, URL, format, dates. Never problem statements | Upstream carries no licence; metadata + link-out is the thinnest defensible use |
| D6 | Sync cadence | **Daily**, `0 6 * * *` UTC, plus manual dispatch | Matches the "what's new today" loop; upstream's hourly commits rarely change content materially |
| D7 | Tombstone retention | Keep **forever** if any personal data references the ID; otherwise drop from `problems.json` after **180 days**. All tombstones retained permanently in `data/archive.json` | Personal work is never orphaned, while the hot dataset stays small (~57 removals/month) |
| D8 | Mirror verbatim? | **No** — store the upstream commit SHA + our normalized data | Keeps git history lean and is the lightest-touch option given D5 |
| D9 | Abort thresholds | Row-count drop **>10%** aborts. Source divergence: warn on any, abort above **max(25 rows, 1%)** | Today divergence is exactly 0, so any drift is signal |
| D10 | Relink auto-merge | Only on an exact `(title, companies, format)` match; everything else is surfaced for manual confirmation | Silently merging the wrong pair would corrupt personal data |
| D11 | Browser-held PAT accepted | **Yes**, with 90-day expiry and single-repo scope | Blast radius analysed in `security-and-access.md` §3.2 |
| D12 | Public Pages republication | **Yes**, metadata-only with prominent attribution | Free-tier Pages requires public; D5 keeps the exposure minimal |
| D13 | PAT expiry | **90 days** | Forces rotation without being a nuisance |
| D14 | Encrypt notes at rest | **No** — plaintext in a private repo | Keeps data diffable and recoverable; keep notes non-sensitive instead |
| D15 | Frontend stack | **Preact + HTM**, vendored | Tiny, no CDN (CSP forbids it), no transpile step |
| D16 | Default view | **Browse**, with a new-count badge linking to What's new | Daily triage is one click away without hiding the main tool |
| D17 | Removed rows visible by default | Only those **with personal data**; the rest hidden | Never silently lose work I invested in |
| D18 | Notes format | **Plain text** | No sanitizer needed under strict CSP |
| D19 | Offline support | **IndexedDB cache only** for v1; no service worker | Enough to survive a lapsed token or a flight |
| D20 | Visual density | **Compact rows** by default; expand a row for the roomier detail + editing panel | ~2,000 rows means scanning matters more than roominess |

### Deferred, not forgotten
- Sharding `problems.json` by format — revisit at ~10,000 rows.
- Migration to a hosted DB — schema is ID-keyed, so this stays a loader swap (D2 is not a one-way door).
- PWA / service worker (D19), stats dashboard, spaced repetition.
