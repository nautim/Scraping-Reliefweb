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
) -> list[dict]:
    """
    Fetch reports linked to a specific disaster, applying TIME_WINDOW filtering.

    disaster_start_date: ISO date string 'YYYY-MM-DD' (or None to skip window filter).
    Returns filtered list of raw report items.
    """
    filter_conditions: list[dict] = [
        {"field": "disaster.id", "value": str(disaster_id)},
    ]
    if config.EXCLUDE_MAPS:
        filter_conditions.append(
            {"field": "format.name", "value": "Map", "negate": True}
        )

    # Date window
    if isinstance(config.TIME_WINDOW, int) and disaster_start_date:
        try:
            start_dt   = datetime.strptime(disaster_start_date, "%Y-%m-%d")
            cutoff_dt  = start_dt + timedelta(weeks=config.TIME_WINDOW)
            date_from  = start_dt.strftime("%Y-%m-%dT00:00:00+00:00")
            date_to    = cutoff_dt.strftime("%Y-%m-%dT23:59:59+00:00")
            filter_conditions.append(
                {"field": "date.original", "value": {"from": date_from, "to": date_to}}
            )
            print(f"    [TIME_WINDOW] {config.TIME_WINDOW} weeks: {disaster_start_date} → {cutoff_dt.date()}")
        except ValueError:
            print(f"    [TIME_WINDOW] Warning: could not parse date '{disaster_start_date}' — skipping window filter")

    payload: dict[str, Any] = {
        "limit": min(config.MAX_REPORTS, 1000),
        "preset": "latest",
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
