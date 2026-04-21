# =============================================================================
#  config.py  —  Centralized configuration for the ReliefWeb pipeline
# =============================================================================

from pathlib import Path

# ---------------------------------------------------------------------------
# USER-DEFINED INPUTS
# ---------------------------------------------------------------------------

# Disaster categories to query (must match ReliefWeb disaster type names)
CATEGORIES: list[str] = [
    "Flood",
    
    

    # "Tropical Cyclone",
    # "Drought",
    # "Wildfire",
    # "Landslide",
]

# Calendar years to process
YEARS: list[int] = [2022]

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
