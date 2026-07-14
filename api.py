# =============================================================================
#  api.py  —  ReliefWeb API layer
# =============================================================================

from __future__ import annotations

import time
import requests
from datetime import datetime, timedelta
from typing import Any

import config


# ---------------------------------------------------------------------------
# Session (shared across the process)
# ---------------------------------------------------------------------------

_session = requests.Session()
_session.headers.update(
    {"Content-Type": "application/json", "Accept": "application/json"}
)


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _post(endpoint: str, payload: dict, retries: int = 3) -> dict:
    """POST to the ReliefWeb API with simple retry logic for rate limits."""
    url    = f"{config.API_BASE_URL}/{endpoint}"
    params = {"appname": config.APP_NAME}

    for attempt in range(1, retries + 1):
        try:
            resp = _session.post(url, params=params, json=payload, timeout=30)
            if resp.status_code == 429:
                wait = 10 * attempt
                print(f"    [API] Rate limited — waiting {wait}s (attempt {attempt}/{retries})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as exc:
            print(f"    [API] HTTP error: {exc}")
            if attempt == retries:
                return {}
            time.sleep(2 * attempt)
        except Exception as exc:
            print(f"    [API] Unexpected error: {exc}")
            if attempt == retries:
                return {}
            time.sleep(2 * attempt)
    return {}


# ---------------------------------------------------------------------------
# Disaster search
# ---------------------------------------------------------------------------

def search_disasters(
    category: str,
    year: int,
    limit: int = 1000,
) -> list[dict]:
    """
    Fetch all ReliefWeb disasters matching a given type name and year.

    Returns a list of raw API 'data' items (each has 'id' and 'fields').
    """
    # Build date range for the whole year
    date_from = f"{year}-01-01T00:00:00+00:00"
    date_to   = f"{year}-12-31T23:59:59+00:00"

    payload: dict[str, Any] = {
        "limit": min(limit, 1000),
        "profile": "full",
        "filter": {
            "operator": "AND",
            "conditions": [
                {"field": "type.name", "value": category},
                {"field": "date.event",
                 "value": {"from": date_from, "to": date_to}},
            ],
        },
        "fields": {
            "include": [
                "id", "name", "glide", "country", "primary_country",
                "description", "status", "url", "date", "type",
            ]
        },
        "sort": ["date.event:desc"],
    }

    data = _post("disasters", payload)
    disasters = data.get("data", [])
    total     = data.get("totalCount", len(disasters))
    print(f"  [API] '{category}' {year}: {len(disasters)} returned (total: {total})")

    if total > 1000:
        print(f"  [API] Warning: API cap is 1000 — some events may be missing.")

    return disasters


def search_disasters_by_country_and_date(
    country_iso3: str,
    event_date: str,
    date_tolerance_days: int = 60,
    limit: int = 1000,
) -> list[dict]:
    """
    Fetch ReliefWeb disasters associated with a country within ±date_tolerance_days
    of event_date (YYYY-MM-DD).  Returns a list of raw API 'data' items.
    """
    try:
        event_dt = datetime.strptime(event_date, "%Y-%m-%d")
    except ValueError:
        print(f"  [API] Warning: invalid event_date '{event_date}' — skipping")
        return []

    tolerance = max(1, date_tolerance_days)
    date_from = (event_dt - timedelta(days=tolerance)).strftime("%Y-%m-%dT00:00:00+00:00")
    date_to   = (event_dt + timedelta(days=tolerance)).strftime("%Y-%m-%dT23:59:59+00:00")

    payload: dict[str, Any] = {
        "limit": min(limit, 1000),
        "profile": "full",
        "filter": {
            "operator": "AND",
            "conditions": [
                {"field": "country.iso3", "value": country_iso3.upper()},
                {"field": "date.event",   "value": {"from": date_from, "to": date_to}},
            ],
        },
        "fields": {
            "include": [
                "id", "name", "glide", "country", "primary_country",
                "description", "status", "url", "date", "type",
            ]
        },
        "sort": ["date.event:desc"],
    }

    data      = _post("disasters", payload)
    disasters = data.get("data", [])
    total     = data.get("totalCount", len(disasters))
    print(f"  [API] {country_iso3} ±{tolerance}d of {event_date}: {len(disasters)} returned (total: {total})")

    if total > 1000:
        print(f"  [API] Warning: API cap is 1000 — some events may be missing.")

    return disasters


# ---------------------------------------------------------------------------
# Report search
# ---------------------------------------------------------------------------

def _language_passes(fields: dict) -> bool:
    """Return True if the report language is in the allowlist (or filter is off)."""
    if not config.ALLOWED_LANGUAGES:
        return True
    lang = fields.get("language", {})
    codes: list[str] = []
    if isinstance(lang, dict):
        c = lang.get("code")
        if c:
            codes.append(c.lower())
    elif isinstance(lang, list):
        for item in lang:
            c = item.get("code") if isinstance(item, dict) else str(item)
            if c:
                codes.append(c.lower())
    if not codes:
        return True
    allowed = [lc.lower() for lc in config.ALLOWED_LANGUAGES]
    return any(c in allowed for c in codes)


def get_disaster_reports(
    disaster_id: int | str,
    disaster_start_date: str | None,
    country_iso3: str | None = None,
    time_window: int | str | None = None,
    oldest_first: bool = False,
) -> list[dict]:
    """
    Fetch reports linked to a specific disaster, applying TIME_WINDOW filtering.

    disaster_start_date: ISO date string 'YYYY-MM-DD' (or None to skip window filter).
    country_iso3: when provided, narrows results to that primary country.
    time_window: per-call override for config.TIME_WINDOW (int weeks, or "all"). When
    None, falls back to config.TIME_WINDOW. Useful for old events where "all" would also
    pull in reports published years later that only cite the disaster in passing (e.g. a
    multi-year regional retrospective), since date.original has no natural upper bound.
    oldest_first: when True, sorts by date.original ascending instead of the default
    "latest" preset (newest first). Matters when the disaster has more reports than
    MAX_REPORTS/the API's 1000-per-request cap: with no pagination, whichever end of the
    date range is sorted first is the end that actually gets kept, and the other end is
    silently dropped. Set this when the earliest reports (e.g. initial disaster-response
    sitreps) matter more than the most recent ones.
    Returns filtered list of raw report items.
    """
    effective_window = config.TIME_WINDOW if time_window is None else time_window

    filter_conditions: list[dict] = [
        {"field": "disaster.id", "value": str(disaster_id)},
    ]
    if country_iso3:
        filter_conditions.append(
            {"field": "primary_country.iso3", "value": country_iso3}
        )
    if config.EXCLUDE_MAPS:
        filter_conditions.append(
            {"field": "format.name", "value": "Map", "negate": True}
        )

    # Date window
    if isinstance(effective_window, int) and disaster_start_date:
        try:
            start_dt   = datetime.strptime(disaster_start_date, "%Y-%m-%d")
            cutoff_dt  = start_dt + timedelta(weeks=effective_window)
            date_from  = start_dt.strftime("%Y-%m-%dT00:00:00+00:00")
            date_to    = cutoff_dt.strftime("%Y-%m-%dT23:59:59+00:00")
            filter_conditions.append(
                {"field": "date.original", "value": {"from": date_from, "to": date_to}}
            )
            print(f"    [TIME_WINDOW] {effective_window} weeks: {disaster_start_date} → {cutoff_dt.date()}")
        except ValueError:
            print(f"    [TIME_WINDOW] Warning: could not parse date '{disaster_start_date}' — skipping window filter")

    sort_dir = "asc" if oldest_first else "desc"
    payload: dict[str, Any] = {
        "limit": min(config.MAX_REPORTS, 1000),
        "sort": [f"date.original:{sort_dir}"],
        "profile": "full",
        "filter": {"operator": "AND", "conditions": filter_conditions},
        "fields": {
            "include": [
                "id", "title", "date", "country", "primary_country",
                "disaster", "disaster_type", "source", "url", "url_alias",
                "body", "body-html", "language", "file",
                "theme", "format", "origin",
            ]
        },
    }
    if oldest_first:
        print(f"    [SORT] oldest_first=True: date.original:asc (whichever {min(config.MAX_REPORTS, 1000)} "
              f"reports fall earliest in the window are kept if the total exceeds the request cap)")

    data    = _post("reports", payload)
    reports = data.get("data", [])
    total   = data.get("totalCount", len(reports))

    print(f"    [API] Fetched {len(reports)} reports (total available: {total})")

    if config.ALLOWED_LANGUAGES:
        before  = len(reports)
        reports = [r for r in reports if _language_passes(r.get("fields", {}))]
        print(f"    [LANG] Kept {len(reports)}/{before} after language filter {config.ALLOWED_LANGUAGES}")

    return reports


# ---------------------------------------------------------------------------
# Convenience: extract a safe start-date string from a disaster item
# ---------------------------------------------------------------------------

def disaster_start_date(disaster: dict) -> str | None:
    """Return the best available date string from a disaster API item."""
    date_obj = disaster.get("fields", {}).get("date", {})
    if not isinstance(date_obj, dict):
        return None
    for key in ("event", "original", "created"):
        raw = date_obj.get(key, "")
        if raw:
            return raw.split("T")[0]
    return None
