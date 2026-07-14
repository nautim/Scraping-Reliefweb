#!/usr/bin/env python3
# =============================================================================
#  main.py  —  ReliefWeb end-to-end pipeline
#              Search → Download → Parse → Zip → Cleanup
# =============================================================================

from __future__ import annotations

import json
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path

import config
from api import search_disasters, search_disasters_by_country_and_date, disaster_start_date
from scraper import scrape_event, event_dir, _safe_name
from parser import build_parsed_json


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

def _load_scraped(ev_dir: Path, event_name: str) -> dict | None:
    safe     = _safe_name(event_name)
    out_path = ev_dir / f"{safe}_scraped.json"
    if not out_path.exists():
        print(f"  [PARSE] Scraped file missing: {out_path}")
        return None
    with open(out_path, encoding="utf-8") as fh:
        return json.load(fh)


def _write_parsed(ev_dir: Path, event_name: str, parsed: dict) -> Path:
    safe     = _safe_name(event_name)
    out_path = ev_dir / f"{safe}_parsed.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(parsed, fh, ensure_ascii=False, indent=2)
    print(f"  [PARSE] Saved → {out_path}")
    return out_path


def _zip_and_cleanup(ev_dir: Path) -> Path:
    """Zip the entire event directory, then delete the original folder."""
    zip_path = ev_dir.parent / f"{ev_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in ev_dir.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(ev_dir.parent))
    shutil.rmtree(ev_dir)
    print(f"  [ZIP]   Saved → {zip_path}  (folder removed)")
    return zip_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    start_time = datetime.now()

    print("=" * 70)
    print("  ReliefWeb Pipeline")
    print(f"  Categories : {config.CATEGORIES}")
    print(f"  Years      : {config.YEARS}")
    print(f"  Targets    : {len(config.TARGETS)} explicit entries")
    print(f"  Time window: {config.TIME_WINDOW}")
    print(f"  Output dir : {config.OUTPUT_BASE_DIR}")
    print("=" * 70)

    config.OUTPUT_BASE_DIR.mkdir(parents=True, exist_ok=True)

    run_log: list[dict] = []

    for category in config.CATEGORIES:
        for year in config.YEARS:

            print(f"\n\n{'#'*70}")
            print(f"  CATEGORY={category}  YEAR={year}")
            print(f"{'#'*70}")

            disasters = search_disasters(category, year)
            if not disasters:
                print(f"  No disasters found for {category} / {year}")
                continue

            time.sleep(config.API_SLEEP)

            for i, disaster in enumerate(disasters, 1):
                name   = disaster.get("fields", {}).get("name", f"event_{i}")
                dis_id = disaster.get("id")

                print(f"\n[{i}/{len(disasters)}] {name}  (id={dis_id})")

                entry: dict = {
                    "category":    category,
                    "year":        year,
                    "name":        name,
                    "id":          dis_id,
                    "scrape_ok":   False,
                    "parse_ok":    False,
                    "zip_ok":      False,
                    "n_reports":   0,
                    "n_pdfs":      0,
                    "error":       None,
                }

                try:
                    # ── Stage 1: Scrape ──────────────────────────────────────
                    ev_dir = scrape_event(disaster, category, year)

                    # ── Stage 2: Parse ───────────────────────────────────────
                    pdf_dir      = ev_dir / "pdf"
                    scraped_data = _load_scraped(ev_dir, name)

                    if scraped_data:
                        parsed = build_parsed_json(scraped_data, pdf_dir)
                        _write_parsed(ev_dir, name, parsed)

                        entry["scrape_ok"] = True
                        entry["parse_ok"]  = True
                        entry["n_reports"] = scraped_data.get("n_reports", 0)
                        entry["n_pdfs"]    = scraped_data.get("n_pdfs",    0)
                    else:
                        entry["scrape_ok"] = True
                        entry["error"]     = "scraped file missing after scrape step"

                    # ── Stage 3: Zip & Cleanup ───────────────────────────────
                    _zip_and_cleanup(ev_dir)
                    entry["zip_ok"] = True

                except Exception as exc:
                    entry["error"] = str(exc)
                    print(f"  [ERROR] {exc}")

                run_log.append(entry)
                time.sleep(config.API_SLEEP)

    # ── Mode 2: country / date targets ───────────────────────────────────────
    for target in config.TARGETS:
        country_iso3 = target.get("country_iso3", "").strip().upper()
        event_date   = target.get("event_date",   "").strip()
        try:
            date_tolerance_days = int(target.get("date_tolerance_days", 60))
        except (TypeError, ValueError):
            date_tolerance_days = 60

        if not country_iso3 or not event_date:
            print(f"  [TARGETS] Skipping malformed entry: {target}")
            continue

        name_contains = target.get("name_contains", "").strip().lower()
        time_window   = target.get("time_window")  # None -> falls back to config.TIME_WINDOW
        oldest_first  = bool(target.get("oldest_first", False))

        print(f"\n\n{'#'*70}")
        print(f"  COUNTRY={country_iso3}  DATE={event_date}  TOL=±{date_tolerance_days}d")
        print(f"{'#'*70}")

        disasters = search_disasters_by_country_and_date(
            country_iso3, event_date, date_tolerance_days
        )
        if not disasters:
            print(f"  No disasters found for {country_iso3} / {event_date}")
            continue

        # A country+date window frequently returns several unrelated disasters (e.g. a
        # different storm or an outbreak that happens to fall in the same window). Narrow to
        # the intended one by name when the target specifies it, rather than scraping all of
        # them.
        if name_contains:
            all_names = [d.get("fields", {}).get("name", "") for d in disasters]
            disasters = [
                d for d in disasters
                if name_contains in d.get("fields", {}).get("name", "").lower()
            ]
            if not disasters:
                print(f"  [TARGETS] No disaster name contains '{name_contains}' among: {all_names} — skipping")
                continue
            skipped = [n for n in all_names if name_contains not in n.lower()]
            if skipped:
                print(f"  [TARGETS] Filtered to name containing '{name_contains}'; skipped: {skipped}")

        time.sleep(config.API_SLEEP)

        for i, disaster in enumerate(disasters, 1):
            name   = disaster.get("fields", {}).get("name", f"event_{i}")
            dis_id = disaster.get("id")

            types    = disaster.get("fields", {}).get("type") or []
            category = types[0].get("name", "Unknown") if types else "Unknown"
            raw_date = disaster_start_date(disaster) or event_date
            year     = int(raw_date[:4])

            print(f"\n[{i}/{len(disasters)}] {name}  (id={dis_id})  cat={category}  year={year}")

            entry: dict = {
                "mode":         "country_date",
                "country_iso3": country_iso3,
                "event_date":   event_date,
                "category":     category,
                "year":         year,
                "name":         name,
                "id":           dis_id,
                "scrape_ok":    False,
                "parse_ok":     False,
                "zip_ok":       False,
                "n_reports":    0,
                "n_pdfs":       0,
                "error":        None,
            }

            try:
                # ── Stage 1: Scrape ──────────────────────────────────────────
                # Note: country_iso3 is only used to *find* the disaster above; it is
                # deliberately not passed here. A single disaster record is often shared
                # across every country it affected (e.g. Idai: Mozambique/Malawi/Zimbabwe/
                # Madagascar under one id) — narrowing report collection by primary_country
                # would silently drop reports tagged to the disaster's other countries.
                # time_window, if set on the target, overrides config.TIME_WINDOW for this
                # disaster only — needed for old events where "all" would also pull in reports
                # published years later that merely cite the disaster in a retrospective.
                # oldest_first, if set, sorts report collection by date.original ascending
                # instead of the default newest-first — matters once the disaster has more
                # reports than MAX_REPORTS/the API's 1000-per-request cap, since whichever end
                # is sorted first is the end actually kept.
                ev_dir = scrape_event(disaster, category, year, time_window=time_window,
                                      oldest_first=oldest_first)

                # ── Stage 2: Parse ───────────────────────────────────────────
                pdf_dir      = ev_dir / "pdf"
                scraped_data = _load_scraped(ev_dir, name)

                if scraped_data:
                    parsed = build_parsed_json(scraped_data, pdf_dir)
                    _write_parsed(ev_dir, name, parsed)
                    entry["scrape_ok"] = True
                    entry["parse_ok"]  = True
                    entry["n_reports"] = scraped_data.get("n_reports", 0)
                    entry["n_pdfs"]    = scraped_data.get("n_pdfs",    0)
                else:
                    entry["scrape_ok"] = True
                    entry["error"]     = "scraped file missing after scrape step"

                # ── Stage 3: Zip & Cleanup ───────────────────────────────────
                _zip_and_cleanup(ev_dir)
                entry["zip_ok"] = True

            except Exception as exc:
                entry["error"] = str(exc)
                print(f"  [ERROR] {exc}")

            run_log.append(entry)
            time.sleep(config.API_SLEEP)

    # ── Summary ──────────────────────────────────────────────────────────────
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n\n{'='*70}")
    print(f"  PIPELINE COMPLETE — {elapsed:.1f}s")
    print(f"{'='*70}")

    ok = [e for e in run_log if e["parse_ok"]]
    er = [e for e in run_log if e["error"]]

    print(f"  Events processed : {len(run_log)}")
    print(f"  Fully successful : {len(ok)}")
    print(f"  Errors           : {len(er)}")

    for e in er:
        label = f"{e.get('country_iso3', e['category'])} / {e['year']} / {e['name']}"
        print(f"    ✗  {label}: {e['error']}")

    # Write run summary
    summary_path = config.OUTPUT_BASE_DIR / "_run_summary.json"
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "run_date":      start_time.isoformat(),
                "elapsed_s":     round(elapsed, 1),
                "config": {
                    "categories":   config.CATEGORIES,
                    "years":        config.YEARS,
                    "targets":      config.TARGETS,
                    "time_window":  config.TIME_WINDOW,
                    "max_reports":  config.MAX_REPORTS,
                    "exclude_maps": config.EXCLUDE_MAPS,
                },
                "events": run_log,
            },
            fh,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\n  Summary → {summary_path}")


if __name__ == "__main__":
    main()