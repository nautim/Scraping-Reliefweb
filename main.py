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
from api import search_disasters
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
        print(f"    ✗  {e['category']} / {e['year']} / {e['name']}: {e['error']}")

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