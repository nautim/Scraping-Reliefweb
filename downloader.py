# =============================================================================
#  downloader.py  —  PDF download logic
# =============================================================================

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

import requests

import config

# Shared session (no auth needed for public PDFs)
_dl_session = requests.Session()
_dl_session.headers.update({"User-Agent": f"reliefweb_pipeline/{config.APP_NAME}"})


def _sanitize_filename(name: str) -> str:
    """Replace unsafe characters with underscores, collapse runs."""
    name = re.sub(r'[^\w\-.]', '_', name)
    name = re.sub(r'_+', '_', name)
    return name.strip("_")


def download_pdf(
    file_info: dict,
    pdf_dir: Path,
    report_id: str,
) -> Optional[dict]:
    """
    Download a single PDF from a ReliefWeb file record.

    Args:
        file_info:  Dict from the ReliefWeb API 'file' field.
        pdf_dir:    Destination directory (will be created if needed).
        report_id:  Report ID used to prefix the filename.

    Returns:
        A metadata dict on success, or None if skipped/failed.
    """
    file_url = file_info.get("url", "")
    filename  = file_info.get("filename", "document.pdf")
    mimetype  = file_info.get("mimetype", "")
    file_id   = str(file_info.get("id", ""))

    # Accept PDFs only
    if "pdf" not in mimetype.lower() and not filename.lower().endswith(".pdf"):
        return None
    if not file_url:
        return None

    pdf_dir.mkdir(parents=True, exist_ok=True)

    base        = _sanitize_filename(Path(filename).stem)
    safe_name   = f"{report_id}_{file_id}_{base}.pdf"
    dest_path   = pdf_dir / safe_name

    if dest_path.exists():
        print(f"      [PDF] Already exists: {safe_name}")
        return {
            "saved_filename": safe_name,
            "url": file_url,
            "mimetype": mimetype,
            "file_id": file_id,
            "size_bytes": dest_path.stat().st_size,
        }

    for attempt in range(1, 4):
        try:
            resp = _dl_session.get(file_url, timeout=60, stream=True)
            if resp.status_code == 429:
                wait = 10 * attempt
                print(f"      [PDF] Rate limited — waiting {wait}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()

            size = 0
            with open(dest_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        fh.write(chunk)
                        size += len(chunk)

            print(f"      [PDF] Saved {safe_name} ({size:,} bytes)")
            time.sleep(config.PDF_SLEEP)

            return {
                "saved_filename": safe_name,
                "url": file_url,
                "mimetype": mimetype,
                "file_id": file_id,
                "size_bytes": size,
            }

        except requests.exceptions.HTTPError as exc:
            print(f"      [PDF] HTTP error ({attempt}/3): {exc}")
            if attempt == 3:
                return None
            time.sleep(3)
        except Exception as exc:
            print(f"      [PDF] Error ({attempt}/3): {exc}")
            if attempt == 3:
                return None
            time.sleep(3)

    return None


def download_reports_pdfs(reports: list[dict], pdf_dir: Path) -> list[dict]:
    """
    Download all PDFs from a list of report records, enriching each report
    with a 'downloaded_files' list.

    Returns the enriched report list.
    """
    enriched = []
    for report in reports:
        fields     = report.get("fields", {})
        report_id  = str(report.get("id", "unknown"))
        raw_files  = fields.get("file", [])
        if not isinstance(raw_files, list):
            raw_files = [raw_files] if raw_files else []

        downloaded = []
        if raw_files:
            print(f"      Downloading {len(raw_files)} file(s) for report {report_id}")
            for fi in raw_files:
                if isinstance(fi, dict):
                    result = download_pdf(fi, pdf_dir, report_id)
                    if result:
                        downloaded.append(result)

        report["_downloaded_files"] = downloaded
        enriched.append(report)

    return enriched
