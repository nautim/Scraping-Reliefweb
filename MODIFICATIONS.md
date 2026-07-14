# Modifications vs. upstream

This repo ([nautim/Scraping-Reliefweb](https://github.com/nautim/Scraping-Reliefweb)) is a fork of
[idecost/Scraping-Reliefweb](https://github.com/idecost/Scraping-Reliefweb) (`upstream` remote) carrying the
changes below, committed and pushed. It's what actually produced the corpora used by the sibling
`reliefweb_temporality_vulnerability` project (Hurricane Melissa, Cyclone Idai, Cyclone Freddy).

Files touched: `config.py`, `api.py`, `main.py`, `scraper.py`, `README.md`, `.gitignore`.

---

## High-level summary

The original pipeline could only search ReliefWeb by **disaster category + calendar year** (e.g. "every Flood
in 2022") — fine for a systematic sweep, useless for targeting one specific known event, since you'd have to
guess which category ReliefWeb filed it under and which year. This fork adds a **second search mode**: search
by **country + approximate event date** instead, so a specific disaster (Melissa, Idai, Freddy) can be found
directly.

Getting that working correctly on old, heavily-referenced events (Idai, 2019) surfaced three follow-on
problems that don't show up on a fresh, single-country event like Melissa:
1. **A named cyclone is one shared disaster record across every country it hit** — so report collection must
   not be narrowed to the search country, or another country's reports get silently dropped.
2. **A country+date window can return more than the intended disaster** — Idai's Mozambique window also
   matched an unrelated cyclone and a cholera outbreak.
3. **Report age has no natural cutoff, and the API caps a single request at 1,000 reports** — for a 2019 event,
   that means multi-year-later retrospectives can crowd out genuine early response reporting.

Three new optional per-target config keys fix these: `name_contains`, `time_window`, `oldest_first` (details
below). Plus a `.gitignore` cleanup, since scraped output includes zips well over GitHub's 100MB file limit.

---

## In depth

### 1. Country + date search mode (`config.py`, `api.py`, `main.py`)

`config.TARGETS` takes `{"country_iso3": ..., "event_date": ..., "date_tolerance_days": ...}` entries.
`api.search_disasters_by_country_and_date()` queries `POST /v2/disasters` with an `AND` filter on
`country.iso3` and a `date.event` range around `event_date`. `main.py` runs this as a second loop ("Mode 2")
after the existing category/year loop, feeding matched disasters into the same scrape → parse → zip pipeline.

### 2. Report collection is not narrowed by the search country

A live API check confirmed named cyclones are typically one shared disaster record spanning every affected
country (Idai's record lists Mozambique/Madagascar/Malawi/Zimbabwe; Freddy's lists six countries). An earlier
version passed the search `country_iso3` into report collection too, filtering to that country's `primary_country`
— this would have silently dropped reports tagged to the disaster's other countries. Fixed: the country in a
`TARGETS` entry is now used only to *find* the disaster; once found, `scrape_event()` collects every report
linked to that disaster id regardless of country.

### 3. `name_contains` — disambiguate the disaster search

A country+date window can match more than one disaster (Idai's Mozambique window also returned a different
cyclone six weeks later and an unrelated cholera outbreak). `name_contains` (optional, per target) keeps only
disasters whose name contains that substring; everything else the search returns is skipped instead of scraped.

### 4. `time_window` — bound report age for old events

`TIME_WINDOW = "all"` is the upstream default and stays global-default for a reason: Melissa's own corpus
needs six months of genuine follow-up reporting. But `"all"` has no upper bound on report *age* — for a 2019
event, a 2024 report that merely cites it among 40 other disasters counts as "about" it (Idai: 2,272 reports
linked in total vs. 1,876 within a year of the event). `time_window` (optional, weeks or `"all"`, per target)
overrides the global default for one disaster via a new parameter on `get_disaster_reports()`. Set to `52` for
Idai/Freddy; left unset for Melissa.

### 5. `oldest_first` — which reports survive the 1,000-report cap

The ReliefWeb API caps a single request at 1,000 reports; this scraper has no pagination. The original sort
(`"preset": "latest"`) always kept the newest 1,000 when a disaster exceeds that — backwards for a
disaster-response corpus, where the earliest sitreps (initial death tolls, first displacement figures) matter
more than later restatements. `oldest_first` (optional bool, per target) switches the API sort to
`date.original:asc`. Set `True` for Idai (1,876 in-window reports vs. the cap); left `False` for Melissa (a
live, still-growing corpus where the newest reports are the relevant ones) and Freddy (its 613 in-window
reports are under the cap regardless).

### 6. `.gitignore` cleanup

`Results/` (scraped output — regenerable, individual zips run 400MB–1GB, over GitHub's 100MB file limit) and
stray tracked `__pycache__`/`.DS_Store` files are now excluded.

---

## Current `TARGETS`

```python
TARGETS: list[dict] = [
    {"country_iso3": "JAM", "event_date": "2025-10-25", "date_tolerance_days": 120,
     "name_contains": "Melissa"},
    {"country_iso3": "MOZ", "event_date": "2019-03-14", "date_tolerance_days": 120,
     "name_contains": "Idai", "time_window": 52, "oldest_first": True},
    {"country_iso3": "MDG", "event_date": "2023-02-21", "date_tolerance_days": 120,
     "name_contains": "Freddy", "time_window": 52},
]
```

## Results

| Event | Disaster id | Reports | PDFs | Output |
|---|---|---|---|---|
| Hurricane Melissa | `52461` | 461 | 358 | `Results/Flood/2025/Hurricane_Melissa_-_Oct_2025.zip` |
| Cyclone Idai | `47733` | 1,000 (capped) | 564 | `Results/Flash_Flood/2019/Tropical_Cyclone_Idai_-_Mar_2019.zip` |
| Cyclone Freddy | `51486` | 552 | 435 | `Results/Tropical_Cyclone/2023/Tropical_Cyclone_Freddy_-_Feb_2023.zip` |

**Known caveat — Idai is still capped at 1,000 of 1,876 in-window reports.** `oldest_first` only changes
*which* 1,000 are kept (now spanning 2019-03-08 → 2019-06-04, i.e. landfall + ~3 months of response), not the
cap itself. Getting all 1,876 needs pagination (looping over `offset`), which is not implemented. Freddy and
Melissa are unaffected — both are under the cap.

Category/year folder naming is inconsistent per event (`Flood`, `Flash Flood`, `Tropical Cyclone`) — cosmetic;
`main.py` takes the API's first-listed hazard type, not the one flagged primary, and ReliefWeb doesn't order
these consistently across disaster records.
