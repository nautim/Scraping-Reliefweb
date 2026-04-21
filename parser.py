# =============================================================================
#  parser.py  —  PDF text extraction and parsed-JSON assembly
# =============================================================================

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pdfplumber

import config


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------

_CAPTION_RE = re.compile(
    r"^\s*(Figure|Fig\.?|Table|Tabella|Tbl\.?|Immagine|Image|Photo|Foto)\s*\d+",
    re.IGNORECASE,
)
_SOURCE_RE = re.compile(r"^\s*(Source|Fonte)\s*:", re.IGNORECASE)


def _filter_lines(lines: list[str], table_texts: set[str] | None = None) -> list[str]:
    filtered = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if _CAPTION_RE.match(line):
            continue
        if _SOURCE_RE.match(line):
            continue
        if table_texts:
            words = line.split()
            if words:
                hits = sum(1 for w in words if w.strip() in table_texts)
                if hits / len(words) > config.TABLE_WORD_THRESHOLD:
                    continue
        filtered.append(line)
    return filtered


def extract_text_from_pdf(pdf_path: Path) -> tuple[str, list[dict]]:
    """
    Extract body text and tables from a PDF with pdfplumber.

    Returns:
        (full_text_str, list_of_table_dicts)
    """
    text_pages: list[str] = []
    all_tables:  list[dict] = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                tables       = page.extract_tables() or []
                table_texts: set[str] = set()

                for t_idx, table in enumerate(tables):
                    if not table:
                        continue
                    all_tables.append(
                        {"page": page_num, "table_number": t_idx + 1, "data": table}
                    )
                    for row in table:
                        if row:
                            for cell in row:
                                if cell and isinstance(cell, str):
                                    table_texts.add(cell.strip())

                page_text = page.extract_text(layout=False)
                if page_text:
                    lines    = page_text.split("\n")
                    filtered = _filter_lines(lines, table_texts if tables else None)
                    if filtered:
                        text_pages.append("\n".join(filtered))

    except Exception as exc:
        print(f"    [PARSE] Error reading {pdf_path.name}: {exc}")
        return "", []

    return "\n\n".join(text_pages), all_tables


# ---------------------------------------------------------------------------
# Report → article dict
# ---------------------------------------------------------------------------

def _names(lst: list, key: str = "name") -> list[str]:
    return [item.get(key, "") for item in (lst or []) if isinstance(item, dict)]


def _lang_name(lang: Any) -> str:
    if isinstance(lang, dict):
        return lang.get("name", "")
    if isinstance(lang, list) and lang:
        first = lang[0]
        return first.get("name", "") if isinstance(first, dict) else str(first)
    return ""


def report_to_article(
    report: dict,
    pdf_filename: str = "",
    pdf_text:     str = "",
    pdf_tables:   list[dict] | None = None,
) -> dict:
    """Convert a raw ReliefWeb report dict to the standard article record."""
    date_info = report.get("date", {})
    if not isinstance(date_info, dict):
        date_info = {}

    return {
        "pdf_filename":    pdf_filename,
        "has_pdf":         bool(pdf_filename),
        "pdf_text":        pdf_text,
        "pdf_text_length": len(pdf_text),
        "pdf_tables":      pdf_tables or [],
        "reliefweb_id":    report.get("reliefweb_id", ""),
        "title":           report.get("title", ""),
        "date": {
            "created":  date_info.get("created",  ""),
            "changed":  date_info.get("changed",  ""),
            "original": date_info.get("original", ""),
        },
        "url":       report.get("url_alias", ""),
        "sources":   report.get("sources",   []),
        "countries": report.get("countries", []),
        "disasters": report.get("disasters", []),
        "language":  _lang_name(report.get("language")),
        "body_text": report.get("content", {}).get("body_text", ""),
    }


# ---------------------------------------------------------------------------
# Main parsing function
# ---------------------------------------------------------------------------

def build_parsed_json(
    scraped_data: dict,
    pdf_dir: Path,
) -> dict:
    """
    Walk all PDFs in pdf_dir, match them to scraped reports, extract text,
    and return a fully assembled parsed-output dict.

    Args:
        scraped_data: The dict written by the scraper (from build_scraped_json).
        pdf_dir:      Path to the pdf/ subfolder.
    """
    reports  = scraped_data.get("reports", [])
    articles: list[dict] = []
    pdf_tables_collection: list[dict] = []

    matching_stats = {
        "exact_match": 0,
        "id_prefix_match": 0,
        "no_match": 0,
    }

    # Index reports by saved_filename for O(1) lookup
    filename_index: dict[str, dict] = {}
    for r in reports:
        for fi in r.get("files", []):
            fn = fi.get("saved_filename", "")
            if fn:
                filename_index[fn.lower()] = r

    # Also index by reliefweb_id prefix (first two underscore-parts)
    prefix_index: dict[str, dict] = {}
    for r in reports:
        rid = r.get("reliefweb_id", "")
        if rid:
            for fi in r.get("files", []):
                fn = fi.get("saved_filename", "")
                if fn:
                    parts = fn.split("_")
                    if len(parts) >= 2:
                        prefix_index[f"{parts[0]}_{parts[1]}"] = r

    pdf_files = sorted(pdf_dir.glob("*.pdf")) if pdf_dir.exists() else []
    print(f"  [PARSE] Found {len(pdf_files)} PDF(s) in {pdf_dir}")

    for pdf_path in pdf_files:
        print(f"\n  [PARSE] {pdf_path.name}")
        pdf_text, pdf_tables = extract_text_from_pdf(pdf_path)

        if pdf_tables:
            pdf_tables_collection.append(
                {"pdf_filename": pdf_path.name, "tables": pdf_tables}
            )

        fn_lower = pdf_path.name.lower()
        matched  = filename_index.get(fn_lower)

        if not matched:
            parts  = pdf_path.name.split("_")
            prefix = f"{parts[0]}_{parts[1]}" if len(parts) >= 2 else ""
            matched = prefix_index.get(prefix)

        if matched:
            exact = fn_lower in filename_index
            if exact:
                matching_stats["exact_match"] += 1
                print(f"    → exact filename match: {matched.get('title', '')[:60]}")
            else:
                matching_stats["id_prefix_match"] += 1
                print(f"    → ID-prefix match: {matched.get('title', '')[:60]}")

            article = report_to_article(matched, pdf_path.name, pdf_text, pdf_tables)
        else:
            matching_stats["no_match"] += 1
            print(f"    → no match found (unlinked PDF)")
            article = {
                "pdf_filename":    pdf_path.name,
                "has_pdf":         True,
                "pdf_text":        pdf_text,
                "pdf_text_length": len(pdf_text),
                "pdf_tables":      pdf_tables,
                "reliefweb_id": "", "title": "",
                "date": {"created": "", "changed": "", "original": ""},
                "url": "", "sources": [], "countries": [],
                "disasters": [], "language": "", "body_text": "",
            }

        articles.append(article)

    # Add reports that have no downloaded PDF
    seen_ids = {a.get("reliefweb_id") for a in articles if a.get("reliefweb_id")}
    for r in reports:
        if r.get("reliefweb_id", "") not in seen_ids:
            print(f"\n  [PARSE] Adding text-only report: {r.get('title', '')[:60]}")
            articles.append(report_to_article(r))

    # Build output
    event_meta = scraped_data.get("event_metadata", {})
    output: dict[str, Any] = {
        **event_meta,
        "n_documents": len(articles),
        "articles":    articles,
        "all_pdf_tables": pdf_tables_collection,
        "processing_metadata": {
            "processing_date":     datetime.now().isoformat(),
            "pdf_directory":       str(pdf_dir),
            "total_pdfs_found":    len(pdf_files),
            "total_reports":       len(reports),
            "matching_statistics": matching_stats,
        },
    }
    return output
