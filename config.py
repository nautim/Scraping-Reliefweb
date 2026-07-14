# =============================================================================
#  config.py  —  Centralized configuration for the ReliefWeb pipeline
# =============================================================================

from pathlib import Path

# ---------------------------------------------------------------------------
# USER-DEFINED INPUTS
# ---------------------------------------------------------------------------

# Disaster categories to query (must match ReliefWeb disaster type names)
CATEGORIES: list[str] = [
    # "Flood",
    "Tropical Cyclone",
    # "Drought",
    # "Wildfire",
    # "Landslide",
]

# Calendar years to process
YEARS: list[int] = []

# Explicit country + date targets (new search mode — runs after the CATEGORIES loop).
# Each entry must have "country_iso3" (ISO 3166-1 alpha-3) and "event_date" (YYYY-MM-DD).
# "date_tolerance_days" is optional and defaults to 60.
# Example:
#   {"country_iso3": "MOZ", "event_date": "2019-03-14"},
#   {"country_iso3": "PHL", "event_date": "2013-11-08", "date_tolerance_days": 30},
#
# NOTE: a named cyclone is typically a single ReliefWeb disaster record shared across every
# country it affected (verified against the live API) — e.g. "Tropical Cyclone Idai - Mar 2019"
# (id 47733) already lists Mozambique/Madagascar/Malawi/Zimbabwe under one id, and "Tropical
# Cyclone Freddy - Feb 2023" (id 51486) lists Madagascar/Malawi/Mauritius/Mozambique/Zimbabwe/
# Réunion. One TARGETS entry per event is enough — any of its listed countries finds the same
# record — and main.py collects every report linked to that disaster id regardless of which
# country each report is primarily tagged to (see main.py's Mode 2 loop).
#
# Two more optional per-entry keys, added after discovering both problems on Idai:
#   "name_contains"  — a country+date window often returns SEVERAL unrelated disasters (Idai's
#                       MOZ window also matched "Tropical Cyclone Kenneth - Apr 2019" and
#                       "Mozambique: Cholera Outbreak - Mar 2019"). When set, only disasters
#                       whose name contains this (case-insensitive) substring are scraped —
#                       everything else the search returns is skipped.
#   "time_window"    — per-target override (int weeks, or "all") for config.TIME_WINDOW. For an
#                       old event, "all" has no upper bound on report age, so a 2024 retrospective
#                       that merely cites a 2019 disaster among 40 others gets pulled in as if it
#                       were event reporting (verified: Idai's disaster id has 2,272 reports total
#                       vs 1,876 within 1 year of the event). Bounding to ~1 year keeps genuine
#                       response/recovery reporting while dropping years-later citations.
#   "oldest_first"   — bool, default False (newest-first). When a disaster's in-window report
#                       count exceeds MAX_REPORTS/the API's 1000-per-request cap (no pagination
#                       here), whichever end of the date range is sorted first is the end that
#                       gets kept. Idai has 1,876 in-window reports vs the 1,000 cap: without this,
#                       the newest 1,000 are kept and everything before 2019-04-12 (the first ~4
#                       weeks post-landfall — the earliest death-toll/displacement sitreps) is
#                       silently dropped. Set True to keep the earliest reports instead.
TARGETS: list[dict] = [
    {"country_iso3": "JAM", "event_date": "2025-10-25", "date_tolerance_days": 120,
     "name_contains": "Melissa"},
    {"country_iso3": "MOZ", "event_date": "2019-03-14", "date_tolerance_days": 120,
     "name_contains": "Idai", "time_window": 52, "oldest_first": True},              # Cyclone Idai
    {"country_iso3": "MDG", "event_date": "2023-02-21", "date_tolerance_days": 120,
     "name_contains": "Freddy", "time_window": 52},                                  # Cyclone Freddy
]

# Time window for report collection relative to each disaster's start date.
#   "all"          → collect every report regardless of publish date
#   int (e.g. 4)   → collect only reports published within X weeks of start date
TIME_WINDOW: int | str = "all"   # e.g. 4  or  "all"

# Maximum number of reports to retrieve per disaster event (API hard cap: 1000)
MAX_REPORTS: int = 1000

# Whether to skip map-format reports
EXCLUDE_MAPS: bool = True

# Language filter (empty list = all languages accepted)
# Example: ["en", "fr"]
ALLOWED_LANGUAGES: list[str] = []

# ---------------------------------------------------------------------------
# OUTPUT PATHS
# ---------------------------------------------------------------------------

OUTPUT_BASE_DIR: Path = Path("Results")

# ---------------------------------------------------------------------------
# RELIEFWEB API
# ---------------------------------------------------------------------------

API_BASE_URL: str  = "https://api.reliefweb.int/v2"
APP_NAME: str      = "ISI_Scraping_1234BjV0393fyHx2S2OQ"

# Seconds to sleep between API calls (be a good citizen)
API_SLEEP: float   = 0.5
PDF_SLEEP: float   = 0.3

# ---------------------------------------------------------------------------
# PDF EXTRACTION
# ---------------------------------------------------------------------------

# Fraction of words in a line that must come from a table cell
# before the whole line is dropped.
TABLE_WORD_THRESHOLD: float = 0.5

# Minimum normalised title-string length for fallback filename matching
MIN_TITLE_MATCH_LENGTH: int = 10
