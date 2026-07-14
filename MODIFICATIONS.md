# Local Modifications

*Uncommitted changes in this working tree, relative to `origin/main`. These are what actually
produced the Hurricane Melissa scrape (`Results/Flood/2025/Hurricane_Melissa_-_Oct_2025/`,
run 2026-04-30) — the upstream `main` branch as committed cannot do this run, because it only
supports the category/year grid search, and Melissa cannot reliably be found that way (it is
filed under ReliefWeb category "Flood", not "Tropical Cyclone", and under a grid year that
doesn't obviously match its Oct 2025 date). `config.py`'s `TARGETS` now also queues Cyclones
Idai (2019) and Freddy (2023) for the P2 cross-event replication described in
`EVALUATION_FRAMEWORK.md`. A first attempt at running all three (2026-07-06) surfaced two more
problems on old events — disaster-search cross-contamination and unbounded report age — both now
fixed; see "Round 2" below. The Idai/Freddy scrape was aborted mid-run once these were found and
has not been redone yet with the fix.*

Files touched: `config.py`, `api.py`, `main.py`, `scraper.py`, `README.md`.

---

## High-level summary

The original pipeline could only search ReliefWeb by **disaster category + calendar year**
(e.g. "give me every Flood in 2022"). That works for a systematic sweep, but it's a poor fit
for targeting **one specific, known event** — you'd have to guess which category ReliefWeb
filed it under and which year(s) to scan.

The modification adds a **second search mode**: search by **country + approximate event date**
instead. You give it `("JAM", "2025-10-25", ±120 days)` and it asks the ReliefWeb API directly
for disasters matching that country within that date window — no need to know the category or
guess the year. Both modes can run in the same execution; Mode 2 runs after Mode 1 and shares
the same downstream scrape → parse → zip pipeline.

This is the change that made the Melissa run practical: it was found via `TARGETS = [{"country_iso3":
"JAM", "event_date": "2025-10-25", "date_tolerance_days": 120}]`, which correctly matched
disaster id `52461` ("Hurricane Melissa - Oct 2025") even though it's categorized as "Flood".
`TARGETS` now has one entry each for Melissa, Idai, and Freddy — see the in-depth `config.py`
section below for the exact values and how they were chosen.

A secondary change originally narrowed report collection to the target's country whenever a
disaster spans several countries. This turned out to be the wrong default and was **removed**
(see the `main.py`/`api.py` sections below): a live API check showed that a named cyclone is
almost always a **single shared ReliefWeb disaster record** across every country it hit — e.g.
Idai's one record (id `47733`) already lists Mozambique, Madagascar, Malawi, and Zimbabwe
together, and Freddy's (id `51486`) lists Madagascar, Malawi, Mauritius, Mozambique, Zimbabwe,
and Réunion. Narrowing report collection to just the search country would have silently dropped
every report tagged primarily to the disaster's other countries. The country in each `TARGETS`
entry is now used only to *find* the disaster; once found, every report linked to that disaster
id is collected regardless of which country it's primarily tagged to.

---

## Round 2 — disaster cross-contamination + unbounded report age (2026-07-06)

Running the scraper against the Idai target (`MOZ / 2019-03-14 / ±120d`) surfaced two problems
that don't show up on a recent, single-country event like Melissa but are severe on an old,
heavily-referenced one:

1. **The country+date search returns more than the intended disaster.** The MOZ window for Idai
   also matched **"Tropical Cyclone Kenneth - Apr 2019"** (a different cyclone that hit Mozambique
   six weeks later) and **"Mozambique: Cholera Outbreak - Mar 2019"**. The Mode 2 loop processed
   *every* disaster a search returned, not just the intended one, so it fully scraped Kenneth
   (595 reports, ~90 PDFs downloaded) before this was caught.
2. **`TIME_WINDOW = "all"` has no upper bound on report age.** A live API check found Idai's
   disaster id (`47733`) has **2,272 reports total** linked to it, vs **1,876 within one year** of
   the event — the gap is mostly multi-year retrospectives (e.g. a 2024 "Internal Displacement in
   Africa 2009–2024" overview that cites Idai among 40+ unrelated disasters spanning 15 years).
   Worse, checking the scraped Kenneth reports directly: **413 of 595** were *also* tagged to
   Idai's disaster id — the same document counted for both, since ReliefWeb tags one report to
   several disasters and there's no "primary disaster" flag to disambiguate (unlike
   `primary_country`, which does exist on country tags).

`TIME_WINDOW = "all"` itself was not changed globally and is not a bug — it's the original
upstream default, and it's necessary for Melissa, whose corpus deliberately spans **six months**
of follow-up reporting (per `METHODOLOGY.md`, the Jamaica displacement plateau is only confirmed
by OCHA reports published months after landfall; a tight window would have silently cut that
data). The fix instead adds **per-target overrides** so old and recent events can each get the
right behavior:

- **`name_contains`** (new `TARGETS` key): after the country+date search, keep only disasters
  whose name contains this substring (case-insensitive); everything else the search returned is
  skipped instead of scraped. Set to `"Idai"` / `"Freddy"` / `"Melissa"` respectively.
- **`time_window`** (new `TARGETS` key): a per-target override for `config.TIME_WINDOW`, passed
  through to `get_disaster_reports()` for that disaster only. Set to `52` (weeks) for Idai and
  Freddy — bounds report collection to about a year post-event, which keeps genuine response/
  recovery reporting while dropping years-later citations. Left unset for Melissa, which keeps
  `config.TIME_WINDOW`'s global `"all"`.

The currently-running scrape was **killed mid-run** (after Kenneth finished, before Idai's ~1,876
reports started downloading) once this was diagnosed — a full unfiltered Idai run would have taken
a long time and produced a folder with heavy Kenneth overlap and multi-year noise. The
`Tropical_Cyclone_Kenneth_-_Apr_2019` folder this produced was left on disk rather than deleted:
per `EVALUATION_FRAMEWORK.md` §4.2, Kenneth is explicitly named as Idai's real-world cause-
attribution "contaminant" (a document tagged to one cyclone but reporting figures caused by the
other), so having its corpus available is useful for that test even though it wasn't the target
of this run.

---

## In-depth, file by file

### `config.py`

- Added `TARGETS: list[dict]`, a list of explicit lookups. Each entry:
  - `country_iso3` — ISO 3166-1 alpha-3 code (e.g. `"JAM"`)
  - `event_date` — approximate event start date, `YYYY-MM-DD`
  - `date_tolerance_days` — optional, default 60; search window is `event_date ± this many days`
  - Documented with inline examples (Mozambique/Idai, Philippines/Haiyan-style entries).
- Changed `CATEGORIES` from `["Flood"]` to `["Tropical Cyclone"]` and `YEARS` from `[2022]` to
  `[]` — this effectively disables Mode 1 for the current run (empty `YEARS` means the
  category/year grid loop has nothing to iterate), so only Mode 2 (`TARGETS`) executes.
- `TARGETS` currently holds three entries, one per event needed for the paper's pilot +
  cross-event replication (`EVALUATION_FRAMEWORK.md` P2):

  ```python
  TARGETS: list[dict] = [
      {"country_iso3": "JAM", "event_date": "2025-10-25", "date_tolerance_days": 120,
       "name_contains": "Melissa"},
      {"country_iso3": "MOZ", "event_date": "2019-03-14", "date_tolerance_days": 120,
       "name_contains": "Idai", "time_window": 52},
      {"country_iso3": "MDG", "event_date": "2023-02-21", "date_tolerance_days": 120,
       "name_contains": "Freddy", "time_window": 52},
  ]
  ```

  - **Melissa** — `JAM`, unchanged from the original run, plus `name_contains: "Melissa"` added
    defensively (its search only ever returned the one disaster, but the filter costs nothing).
  - **Idai** — `MOZ`, 2019-03-14 (the Beira landfall date). Verified this resolves to the single
    shared disaster record id `47733` ("Tropical Cyclone Idai - Mar 2019"). Also added
    `name_contains: "Idai"` (the MOZ window also matches Kenneth and a cholera outbreak — see
    "Round 2" above) and `time_window: 52` (bounds to ~1 year post-event, dropping multi-year
    retrospective citations).
  - **Freddy** — `MDG`, 2023-02-21 (the storm's first landfall in Madagascar, and the disaster
    record's own primary country). Verified this resolves to id `51486` ("Tropical Cyclone
    Freddy - Feb 2023"). Malawi's flooding peak (~2023-03-12) and Mozambique's two landfalls
    (2023-02-24, 2023-03-11) are all comfortably inside the `±120` day window from this date, and
    since the record is shared, any of those countries would have found the same id — Madagascar
    was chosen simply because it's the record's listed primary country. Given the same
    `name_contains`/`time_window` treatment as Idai on the assumption its MOZ/MDG window is likely
    to hit similar neighboring-disaster noise, though this hasn't been verified against the API
    the way Idai's contamination was.
  - Only one entry per event is needed even though each cyclone hit several countries — see the
    "High-level summary" above for why adding one entry per affected country would not have
    helped (and briefly did the opposite) under the original per-target report-narrowing.

### `api.py`

- New function `search_disasters_by_country_and_date(country_iso3, event_date,
  date_tolerance_days=60, limit=1000)`:
  - Parses `event_date`, computes a `[event_date - tolerance, event_date + tolerance]` window.
  - Calls `POST /v2/disasters` with an `AND` filter on `country.iso3` and `date.event` (range),
    requesting fields `id, name, glide, country, primary_country, description, status, url,
    date, type`, sorted by `date.event:desc`.
  - Warns if `totalCount > 1000` (the API's hard cap), since results beyond that would be
    silently missing.
  - Prints a one-line diagnostic per call (`{country} ±{tol}d of {date}: {n} returned`).
- Extended `get_disaster_reports(disaster_id, disaster_start_date, country_iso3=None)`:
  - New optional `country_iso3` parameter. When provided, adds a
    `{"field": "primary_country.iso3", "value": country_iso3}` filter condition alongside the
    existing `disaster.id` (and `EXCLUDE_MAPS`) conditions — so for a multi-country disaster,
    only reports whose *primary* country matches the target are collected.
  - **This parameter is still present but is no longer used by Mode 2** (see `main.py` below) —
    it turned out to be the wrong default once it became clear that a single disaster record is
    shared across all of a cyclone's affected countries. Left in place as an opt-in narrowing
    tool for a future case where per-country report filtering is genuinely wanted, but Mode 2 now
    calls `scrape_event()` without it so nothing is dropped.
  - **New `time_window` parameter** (Round 2): `get_disaster_reports(disaster_id,
    disaster_start_date, country_iso3=None, time_window=None)`. When `None` (the default), falls
    back to `config.TIME_WINDOW` exactly as before — Melissa's behavior is unchanged. When set
    (int weeks, or `"all"`), it overrides `config.TIME_WINDOW` for that one call, so an old event
    can be bounded without touching the global default that Melissa's "all" late-reporting
    coverage depends on.

### `main.py`

- Imports the new `search_disasters_by_country_and_date` and `disaster_start_date` alongside the
  existing `search_disasters`.
- Startup banner now also prints the number of `TARGETS` entries configured.
- Added an entire new loop block, **"Mode 2: country / date targets"**, run after the existing
  category/year grid loop:
  1. For each entry in `config.TARGETS`: validate/normalize `country_iso3`, `event_date`,
     `date_tolerance_days` (falls back to 60 on bad/missing values; skips malformed entries
     with a warning).
  2. Call `search_disasters_by_country_and_date(...)`; if nothing found, log and continue to
     the next target.
  3. For each disaster returned, derive `category` (from the API's `type` field, first entry,
     else `"Unknown"`) and `year` (from `disaster_start_date()`, else falls back to the
     target's `event_date`).
  4. Run the same three pipeline stages as Mode 1 for each matched disaster:
     - **Scrape**: `scrape_event(disaster, category, year)` — **no longer** passes
       `country_iso3` through. It originally did (`scrape_event(disaster, category, year,
       country_iso3=country_iso3)`), which narrowed report collection to the search country's
       `primary_country`. That was corrected once a live API check showed named cyclones share
       one disaster record across all affected countries (see "High-level summary"): passing the
       country through would have silently excluded reports tagged to the disaster's other
       countries (e.g. an Idai run targeted via `MOZ` would have dropped Malawi- and
       Zimbabwe-primary reports). `country_iso3` is only used above, to find the disaster; it is
       deliberately not threaded into the scrape/report-fetch stage anymore.
     - **Parse**: loads the just-written `_scraped.json`, calls `build_parsed_json(...)`,
       writes `_parsed.json`.
     - **Zip & cleanup**: `_zip_and_cleanup(ev_dir)`.
  5. Appends a log entry per disaster (`mode: "country_date"`, ids, counts, `scrape_ok` /
     `parse_ok` / `zip_ok` / `error`) to the shared `run_log`, same shape as Mode 1's entries
     plus the `mode`/`country_iso3`/`event_date` fields.
  6. Sleeps `config.API_SLEEP` between targets, matching Mode 1's rate-limiting behavior.
- **Round 2 addition — name filtering:** after the search, if the target sets `name_contains`,
  `disasters` is filtered to only those whose name contains it (case-insensitive); non-matches are
  logged and skipped rather than scraped. Without this, Idai's `MOZ` search also fully scraped
  "Tropical Cyclone Kenneth - Apr 2019" before the problem was noticed.
- **Round 2 addition — time window passthrough:** `target.get("time_window")` (`None` if unset) is
  read alongside `name_contains` and passed into `scrape_event(..., time_window=time_window)`, so
  an old event can bound report collection to, e.g., ~1 year post-event without changing
  `config.TIME_WINDOW` globally (which Melissa's late-reporting coverage needs to stay `"all"`).
- Error-summary printout now labels failures by `country_iso3` when present (falls back to
  `category` for Mode 1 entries), since Mode 2 entries don't have a natural category label.
- `_run_summary.json` now also records `config.targets` alongside `categories`/`years`, so a run
  is fully reproducible from the summary file alone (this is how the Melissa run's exact config
  was recovered after the fact — see the `config` block in
  `Results/_run_summary.json`).

### `scraper.py`

- `scrape_event(disaster, category, year, country_iso3=None, time_window=None)`: added the
  `country_iso3` parameter and threads it straight into the call to `get_disaster_reports(dis_id,
  start_dt, country_iso3=country_iso3, time_window=time_window)`. No other behavior in this
  function changed — scraping, PDF download, and JSON writing are identical to Mode 1's path once
  reports are fetched.
- The `country_iso3` parameter itself is untouched, but as noted above, `main.py`'s Mode 2 loop no
  longer calls `scrape_event()` with a `country_iso3` argument, so it defaults to `None` and no
  narrowing filter is added in practice.
- **New `time_window` parameter** (Round 2), threaded straight through to `get_disaster_reports()`
  — see the `api.py` section above.

### `README.md`

- Documents both search modes with a table for `TARGETS` fields and an example block.
- Notes that results still land under `Results/<DisasterType>/<Year>/` regardless of which mode
  found the disaster, and that a disaster found by both modes in the same run is only processed
  once (existing idempotent skip-if-exists guard in the scrape step, unchanged).
- Updates the pipeline-flow ASCII diagram to show Mode 1 and Mode 2 as two branches feeding the
  same shared scrape → parse → zip stages.

---

## Net effect

With these changes, `python main.py` skips Mode 1 entirely (`YEARS = []`) and runs Mode 2 against
all three `TARGETS`. For all events, every report linked to the matched disaster id is scraped —
no `primary_country` narrowing — so reports tagged to any of the disaster's listed countries
(e.g. Idai: Mozambique/Madagascar/Malawi/Zimbabwe) are collected in one pass, and `name_contains`
keeps out unrelated disasters the country+date search also turns up.

## Results — completed run, 2026-07-06 (`Results/_run_summary.json`, 68 min elapsed)

| Event | Disaster id | Category / year (as filed) | Reports | PDFs | Output |
|---|---|---|---|---|---|
| Hurricane Melissa | `52461` | Flood / 2025 | 461 | 358 | `Results/Flood/2025/Hurricane_Melissa_-_Oct_2025.zip` (412 MB) |
| Cyclone Idai | `47733` | Flash Flood / 2019 | **1,000 (capped)** | 706 | `Results/Flash_Flood/2019/Tropical_Cyclone_Idai_-_Mar_2019.zip` (994 MB) |
| Cyclone Freddy | `51486` | Tropical Cyclone / 2023 | 552 | 435 | `Results/Tropical_Cyclone/2023/Tropical_Cyclone_Freddy_-_Feb_2023.zip` (879 MB) |

Notes:
- **Melissa grew from 269→461 reports** vs. the original April scrape — expected, since this is a
  fresh re-scrape three months later and `TIME_WINDOW="all"` picks up everything published since
  (the corpus is still actively growing as agencies keep reporting).
- **Category/year folder naming is inconsistent per event** (`Flood`, `Flash Flood`, `Tropical
  Cyclone`) — `main.py` takes the API's first-listed disaster type, not the one flagged `primary`,
  and ReliefWeb doesn't order these consistently across disaster records. Cosmetic, not a
  correctness issue, but worth knowing when locating the output folders.
- **⚠️ Idai's 1,000 reports were truncated, not complete — now fixed for the *direction* of the
  cut, not the cap itself.** `MAX_REPORTS=1000` is the ReliefWeb API's hard per-request cap, and
  this scraper still has no pagination (no offset loop), so a disaster with more in-window reports
  than that still only gets 1,000. Idai has **1,876** reports within the 52-week window, so ~876
  are always dropped either way. What changed: the fixed `"preset": "latest"` (newest-first) has
  been replaced with an explicit, per-target-controllable sort — see "Round 3" below — so the run
  above (which used the old newest-first default) is missing everything published before
  2019-04-12 (the first ~4 weeks post-landfall, containing the earliest death-toll/displacement
  sitreps). **This needs a re-scrape with `oldest_first: True`** (now set for Idai in `config.py`)
  to get those reports instead; see Round 3 for why 1,000-newest was the wrong default for a
  disaster-response corpus and pagination remains the real long-term fix.
- Freddy's in-window pool is 613 vs. 552 scraped — the gap is `EXCLUDE_MAPS` filtering out
  map-format reports, not truncation (613 is well under the 1,000 cap).
- The Kenneth/Cholera-Outbreak folders from the earlier aborted attempt are gone — this run's
  `name_contains` filter correctly kept them out from the start.

---

## Round 3 — which end of a truncated report set gets kept (2026-07-06)

The Idai truncation above raised a follow-up question: given the 1,000-report cap can't be
lifted without pagination, *which* 1,000 should be kept when the corpus can't fit? The prior
behavior (`"preset": "latest"`) always kept the **newest** reports. For a disaster-response corpus
that's backwards — the earliest sitreps (initial death tolls, first displacement estimates) are
usually the ones most worth having, and the newest reports are disproportionately later
retrospectives/updates that already restate earlier figures.

- **`api.py`**: `get_disaster_reports()` gained an `oldest_first: bool = False` parameter. The
  fixed `"preset": "latest"` was replaced with an explicit `"sort": ["date.original:asc"]` (when
  `oldest_first`) or `"date.original:desc"` (default, same effective order as the old preset).
  Verified against the live API that `date.original:asc` does return Idai's earliest report
  (2019-03-14) first.
- **`scraper.py`**: `scrape_event()` gained the same `oldest_first` parameter, threaded straight
  into `get_disaster_reports()`.
- **`main.py`**: Mode 2 reads a new optional `TARGETS` key, `oldest_first` (default `False`), and
  passes it through to `scrape_event()`.
- **`config.py`**: Idai's target now sets `"oldest_first": True` — with the corpus known to exceed
  the cap, keep the earliest reports rather than the most recent. Melissa and Freddy are left at
  the default (`False`); Freddy's in-window pool (613) is under the cap so sort direction doesn't
  matter for it, and Melissa's use case (a live, still-updating corpus) genuinely wants the newest
  reports, not the oldest.
- **This does not fix the 1,000-report cap itself** — it only changes which 1,000 are kept.
  Getting *all* 1,876 of Idai's in-window reports still requires pagination (looping over
  `offset` until a request returns fewer than `limit`), which has not been implemented. If full
  coverage is needed rather than "the earliest 1,000," that's the next step.
- The `Results/Flash_Flood/2019/Tropical_Cyclone_Idai_-_Mar_2019.zip` from the "Round 2" run above
  still reflects the **old** newest-first order and needs a re-scrape to pick up this fix — the
  zip-and-cleanup step deletes the unzipped working folder each run, so `scrape_event()`'s
  skip-if-exists guard won't fire and a plain re-run of `main.py` will redo all three targets from
  scratch (not just Idai).

None of this is committed to `origin/main` — it exists only in this local working tree.
