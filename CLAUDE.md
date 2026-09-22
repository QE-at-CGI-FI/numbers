# numbers

Experimenting with git activity numbers across a set of well-known open source
projects, plus tracking when each project adopted AI coding tools.

## Repo layout

- One folder per GitHub org/user (`LadybirdBrowser/`, `PrestaShop/`, `SeleniumHQ/`,
  `anthropics/`, `freeCodeCamp/`, `ghostty-org/`, `golang/`, `kubernetes/`,
  `langchain-ai/`, `nodejs/`, `react/`, `rust-lang/`, `tensorflow/`).
- Inside each org folder, one CSV per repo named `<repo>.csv`, holding monthly
  git activity stats for that repo (see "Collecting stats" below).
- `skipped-repos.csv` in each org folder lists repos that were deliberately
  **not** processed (columns: `repo,size_kb,size_mb,reason` — usually too
  large to clone/process). It is not itself a repo's metrics file.
- `repos-with-metrics.csv` (root) is the master index: every repo that has a
  metrics CSV, one row each, columns `org,repo,github_url,ai_adoption_date`.
- `valitut_projektit.txt` (root) is a free-form, hand-maintained Finnish note
  file with the original project shortlist and rough "ai aloitus" (AI-start)
  dates the user tracked manually before this was automated. Treat it as a
  cross-check, not a source of truth — see "Reconciliation" below.
- `aggregate.csv` / `aggregate_mh.csv` (root) are cross-repo rollups consumed
  by `index.html` (the visualizer), produced by `scripts/generate_aggregate.py`.

## Collecting stats

Per-repo monthly metrics (the CSVs inside each org folder) are produced by
`repo_month_metrics.py` against a **local clone** of the repo:

```
python3 repo_month_metrics.py /path/to/local/clone -o <OrgFolder>/<repo>.csv
```

- Output columns: `month, repos, commits, insertions, deletions,
  total_msg_chars, avg_insertions, avg_deletions, avg_msg_length,
  active_authors` (distinct commit-author names that month).
  `active_authors` was added later — existing per-repo CSVs still on the
  9-column schema keep working fine (index.html treats the column as
  optional); rerun a repo through the script to backfill it.
- `--scan DIR` auto-discovers git repos one level under `DIR` instead of
  taking explicit paths; add `--scan-recursive` to search deeper.
- `--all-branches` includes every branch, not just the checked-out one.
- `--author <substr>` filters to one author (name/email substring).
- `--include-merges-diff` diffs merge commits against their first parent so
  they contribute insertions/deletions (normally merges show 0/0).
- If a repo is too large to clone/process, add a row to that org's
  `skipped-repos.csv` instead of a per-repo CSV, with a `reason`.

For the cross-repo rollup used by the visualizer, use
`scripts/generate_aggregate.py` (9-column legacy schema: see
`scripts/generate_aggregate_old.py`) — pass one or more local repo paths and
`-o aggregate.csv`. See `README.md` for its extra columns and flags.

After adding a repo's metrics CSV, add a matching row to
`repos-with-metrics.csv` (`org,repo,github_url,ai_adoption_date`), leaving
`ai_adoption_date` blank until it's been looked up (see below).

## AI-adoption markers

We define "AI was taken into use" in a repo as the first commit that
introduces any of these paths:

- `.claude`
- `.github/skills`
- `.github/agents`
- `.github/copilot-instructions.md`
- `.cursor`
- `CLAUDE.md`
- `AGENTS.md`

`ai_adoption_date` in `repos-with-metrics.csv` is the **earliest** date across
all markers that ever appeared in the repo's history (a repo can — and often
does — add several of these around the same time; take the minimum).

### How to compute it

Use the GitHub REST API's commits-by-path endpoint, once per candidate path:

```
GET /repos/{org}/{repo}/commits?path={marker}&per_page=1
```

- Empty result → that marker never existed in this repo's history.
- Non-empty result with no `rel="last"` Link header → only one commit ever
  touched that path, so it's both the first and only hit — use its date.
- Non-empty result with a `rel="last"` Link → follow that URL (still
  `per_page=1`) to get the **oldest** commit for that path; the API always
  returns commits newest-first, so the last page holds the first appearance.

Take the minimum date across all markers with a hit; leave the cell blank if
none of the 7 paths ever appeared.

Checking current existence via the contents API
(`GET /repos/{org}/{repo}/contents/{path}`) is *not* enough on its own — it
only tells you the file is there **today**, not when it first showed up, and
misses markers that were later removed or renamed.

### Rate limits

- Unauthenticated: 60 requests/hour — not enough for more than a couple of
  repos at 2 requests/marker × 7 markers. Only use this if `gh auth` is
  broken and the user has explicitly accepted the slowdown.
- Authenticated (`gh auth token` as a Bearer token): 5000 requests/hour —
  use this whenever `gh auth status` succeeds.
- Check `gh auth status` first; if it's broken, ask the user to run
  `gh auth login` themselves (don't attempt to fix credentials yourself).

### Scope

`ai_adoption_date` is fully populated for all 995 rows (13 `repo_type=main` +
982 `repo_type=side`), completed 2026-09-22. 60 rows have a real date; the
rest are genuinely blank (no marker ever appeared in that repo's history),
except 9 `PrestaShop` rows that 404'd outright (typo'd/renamed filenames —
`ps_chackpayment`, `blockreasurrance`, `classi-theme`, `pa_customeraccountlinks`,
`ps_shoppingcarts`, `QANighltResults`, `Repositories`, `git_monthly_metrics`,
`ts-pw-d365-ce-fo` — fix the filename/repo mapping and rerun if these matter).

### Rerunning the lookup (e.g. after adding new repos)

`scripts/ai_adoption_all.py` checks every `repo_type=side` row in
`repos-with-metrics.csv` against the 7 markers above and writes results to
`scripts/ai_adoption_progress_all.json` (one entry per `org/repo`, marked
`"_complete": true` once all 7 markers are checked for that repo — the
script skips complete entries on rerun, so it's safe to stop and restart, and
cheap to rerun after adding a handful of new rows since it won't recheck
existing ones):

```
export GH_TOKEN=$(gh auth token)   # requires `gh auth status` to be logged in
python3 scripts/ai_adoption_all.py
```

It stops itself gracefully (saving progress) when the GitHub rate limit runs
low. Note: the standalone `/rate_limit` endpoint has been observed to report
a misleadingly fresh count (e.g. "5000 remaining") while the real per-request
`X-RateLimit-Remaining` header on the actual endpoint being used still shows
single digits — trust the live per-request header from an actual `commits?path=`
call, not a separate `/rate_limit` check, when deciding whether to resume.

After a run, merge newly-completed entries back into `repos-with-metrics.csv`'s
`ai_adoption_date` column by taking, per repo, the minimum date across all
markers with a hit in `scripts/ai_adoption_progress_all.json` (leave blank if
none hit, or if `status` is `repo_not_found` for every marker) — there is no
standing merge script for this yet, write one inline when needed.

## Reconciliation

`valitut_projektit.txt` has hand-written "ai aloitus <date>" notes for most
flagship repos, made before dates were computed from commit history. When a
computed `ai_adoption_date` disagrees with that note by more than ~a day
(timezone rounding aside), mark the line in `valitut_projektit.txt` rather
than silently overwriting it:

```
[NEEDS RECONCILIATION: <what the computed data actually shows>]
```

Don't delete or "correct" the original note — the mismatch itself may be
useful (e.g. the note refers to a marker path outside the 7 tracked, or to
something that was later removed from history).
