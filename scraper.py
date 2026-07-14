# =============================================================================
#  scraper.py  —  Fetches disasters + reports, downloads PDFs, writes scraped JSON
# =============================================================================

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import config
from api import search_disasters, get_disaster_reports, disaster_start_date
from downloader import download_reports_pdfs


# ---------------------------------------------------------------------------
# Filename / path helpers
# ---------------------------------------------------------------------------

def _safe_name(text: str, max_len: int = 60) -> str:
    """Turn arbitrary text into a filesystem-safe string."""
    text = re.sub(r"[^\w\s\-]", "", text).strip()
    text = re.sub(r"[\s]+", "_", text)
    return text[:max_len] or "unnamed"


def event_dir(category: str, year: int, event_name: str) -> Path:
    """
    Results/<Category>/<Year>/<Event Name>/
    """
    return config.OUTPUT_BASE_DIR / _safe_name(category) / str(year) / _safe_name(event_name)


# ---------------------------------------------------------------------------
# Per-event scrape
# ---------------------------------------------------------------------------

def _extract_report_meta(report: dict, downloaded_files: list[dict]) -> dict:
    """Flatten a raw API report into a clean metadata record."""
    fields    = report.get("fields", {})
    report_id = str(report.get("id", ""))

    date_obj = fields.get("date", {})
    if not isinstance(date_obj, dict):
        date_obj = {}

    def to_list(v):
        return v if isinstance(v, list) else ([v] if v else [])

    def _sources(lst):
        return [
            {
                "id":        s.get("id"),
                "name":      s.get("name", ""),
                "shortname": s.get("shortname", ""),
                "longname":  s.get("longname", ""),
                "homepage":  s.get("homepage", ""),
                "type": (
                    s.get("type", {}).get("name", "")
                    if isinstance(s.get("type"), dict) else ""
                ),
            }
            for s in to_list(lst)
            if isinstance(s, dict)
        ]

    def _countries(lst):
        return [
            {
                "id":        c.get("id"),
                "name":      c.get("name", ""),
                "shortname": c.get("shortname", ""),
                "iso3":      c.get("iso3", ""),
                "primary":   c.get("primary", False),
            }
            for c in to_list(lst)
            if isinstance(c, dict)
        ]

    lang      = fields.get("language", {})
    lang_info = None
    if isinstance(lang, dict):
        lang_info = {"id": lang.get("id"), "name": lang.get("name", ""), "code": lang.get("code", "")}
    elif isinstance(lang, list) and lang:
        first = lang[0]
        lang_info = {
            "id":   first.get("id")   if isinstance(first, dict) else None,
            "name": first.get("name", "") if isinstance(first, dict) else str(first),
            "code": first.get("code", "") if isinstance(first, dict) else "",
        }

    return {
        "reliefweb_id": report_id,
        "title":        fields.get("title", ""),
        "date":         {
            "created":  date_obj.get("created",  ""),
            "changed":  date_obj.get("changed",  ""),
            "original": date_obj.get("original", ""),
        },
        "url":           fields.get("url",       ""),
        "url_alias":     fields.get("url_alias", ""),
        "sources":       _sources(fields.get("source",  [])),
        "countries":     _countries(fields.get("country", [])),
        "disasters": [
            {"id": d.get("id"), "name": d.get("name", ""), "glide": d.get("glide", "")}
            for d in to_list(fields.get("disaster", []))
            if isinstance(d, dict)
        ],
        "disaster_types": [
            {"id": dt.get("id"), "name": dt.get("name", "")}
            for dt in to_list(fields.get("disaster_type", []))
            if isinstance(dt, dict)
        ],
        "themes":  [{"id": t.get("id"), "name": t.get("name", "")} for t in to_list(fields.get("theme",  [])) if isinstance(t, dict)],
        "formats": [{"id": f.get("id"), "name": f.get("name", "")} for f in to_list(fields.get("format", [])) if isinstance(f, dict)],
        "language": lang_info,
        "content":  {
            "body_text": fields.get("body",      ""),
            "body_html": fields.get("body-html", ""),
        },
        "files": downloaded_files,
    }


def scrape_event(
    disaster: dict,
    category: str,
    year: int,
    country_iso3: str | None = None,
    time_window: int | str | None = None,
    oldest_first: bool = False,
) -> Path:
    """
    Full scrape pipeline for one disaster event:
      1. Determine output paths.
      2. Fetch linked reports.
      3. Download PDFs.
      4. Write *_scraped.json.

    Returns the event directory path.
    """
    fields = disaster.get("fields", {})
    name   = fields.get("name", f"unknown_{disaster.get('id', '')}")
    dis_id = disaster.get("id")

    ev_dir  = event_dir(category, year, name)
    pdf_dir = ev_dir / "pdf"
    ev_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    safe  = _safe_name(name)
    out_path = ev_dir / f"{safe}_scraped.json"

    # Skip if already scraped
    if out_path.exists():
        print(f"  [SKIP] Already scraped: {out_path.relative_to(config.OUTPUT_BASE_DIR)}")
        return ev_dir

    print(f"\n{'='*70}")
    print(f"  EVENT  : {name}")
    print(f"  ID     : {dis_id}")
    print(f"  OUT    : {ev_dir}")
    print(f"{'='*70}")

    start_dt  = disaster_start_date(disaster)
    reports   = get_disaster_reports(dis_id, start_dt, country_iso3=country_iso3, time_window=time_window,
                                      oldest_first=oldest_first)

    # Download PDFs and enrich reports
    enriched  = download_reports_pdfs(reports, pdf_dir)

    # Build list of clean report metadata
    clean_reports: list[dict] = []
    for r in enriched:
        downloaded = r.pop("_downloaded_files", [])
        clean_reports.append(_extract_report_meta(r, downloaded))
        time.sleep(0)

    # Disaster-level metadata
    date_obj = fields.get("date", {}) or {}
    event_metadata: dict[str, Any] = {
        "reliefweb_disaster_id": dis_id,
        "name":          name,
        "category":      category,
        "year":          year,
        "glide":         fields.get("glide", ""),
        "status":        fields.get("status", ""),
        "url":           fields.get("url",    ""),
        "date": {
            "event":   date_obj.get("event",    ""),
            "created": date_obj.get("created",  ""),
            "changed": date_obj.get("changed",  ""),
        },
        "countries": [
            {"name": c.get("name", ""), "iso3": c.get("iso3", "")}
            for c in (fields.get("country") or [])
            if isinstance(c, dict)
        ],
        "types": [
            t.get("name", "") for t in (fields.get("type") or []) if isinstance(t, dict)
        ],
    }

    scraped: dict[str, Any] = {
        "event_metadata":      event_metadata,
        "reports":             clean_reports,
        "n_reports":           len(clean_reports),
        "n_pdfs":              sum(len(r["files"]) for r in clean_reports),
        "processing_metadata": {
            "processing_date": datetime.now().isoformat(),
            "time_window":     config.TIME_WINDOW,
            "pdf_directory":   str(pdf_dir),
        },
    }

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(scraped, fh, ensure_ascii=False, indent=2)

    print(f"\n  [SCRAPE] Saved → {out_path}")
    print(f"  [SCRAPE] Reports: {scraped['n_reports']} | PDFs: {scraped['n_pdfs']}")

    return ev_dir
