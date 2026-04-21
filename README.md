# ReliefWeb Pipeline

An autonomous, end-to-end pipeline that:

1. **Searches** the [ReliefWeb API](https://apidoc.rwlabs.org) for disaster events matching configurable categories and years.
2. **Downloads** all associated PDF reports.
3. **Parses** each PDF into clean, structured JSON.
4. **Saves** the zip with the compressed files for memory optimization

---

## Project structure

```
reliefweb_pipeline/
├── config.py          ← All user-facing settings live here
├── main.py            ← Entry point
├── api.py             ← ReliefWeb API layer
├── scraper.py         ← Fetches metadata + downloads PDFs, writes *_scraped.json
├── parser.py          ← Extracts text from PDFs, writes *_parsed.json
├── downloader.py      ← PDF download logic (retry, dedup, rate-limit)
├── requirements.txt
└── Results/           ← Auto-created output tree
    └── <Category>/
        └── <Year>/
            └── <Event Name>/
                ├── pdf/                   ← Downloaded .pdf files
                ├── <Event Name>_scraped.json
                └── <Event Name>_parsed.json
```

---

## Quick start

```bash
pip install -r requirements.txt
python main.py
```

---

## Configuration (`config.py`)

| Setting | Type | Description |
|---|---|---|
| `CATEGORIES` | `list[str]` | ReliefWeb disaster type names, e.g. `["Flood", "Earthquake"]` |
| `YEARS` | `list[int]` | Calendar years to query, e.g. `[2022, 2023]` |
| `TIME_WINDOW` | `int` or `"all"` | Weeks from disaster start date to collect reports (`"all"` = no limit) |
| `MAX_REPORTS` | `int` | Max reports per event (API hard cap: 1000) |
| `EXCLUDE_MAPS` | `bool` | Skip map-format reports |
| `ALLOWED_LANGUAGES` | `list[str]` | ISO language codes to keep; empty = all |
| `OUTPUT_BASE_DIR` | `Path` | Root output directory (default: `Results/`) |

---

## Output files

### `*_scraped.json`
Raw metadata from the ReliefWeb API: disaster info, report titles, sources,
dates, language, body text, and a record of every downloaded PDF file.

### `*_parsed.json`
Merged output: scraped metadata **+** extracted PDF text (table-filtered)
for every article/report.  Each entry in `articles[]` contains:

```json
{
  "reliefweb_id": "...",
  "title": "...",
  "pdf_filename": "...",
  "pdf_text": "...(full extracted body text)...",
  "pdf_text_length": 12345,
  "pdf_tables": [...],
  "date": { "created": "...", "changed": "...", "original": "..." },
  "url": "...",
  "sources": [...],
  "countries": [...],
  "body_text": "...(HTML body from API)..."
}
```

---

## How the pipeline works

```
main.py
  │
  ├─ api.search_disasters(category, year)
  │    └─ POST /v2/disasters  (filter: type + date range)
  │
  └─ for each disaster:
       │
       ├─ scraper.scrape_event()
       │    ├─ api.get_disaster_reports()   POST /v2/reports
       │    ├─ downloader.download_reports_pdfs()
       │    └─ writes  <Event>_scraped.json
       │
       └─ parser.build_parsed_json()
            ├─ parser.extract_text_from_pdf()   (pdfplumber)
            └─ writes  <Event>_parsed.json
```

---

## Notes

- **Idempotent scraping**: if `*_scraped.json` already exists for an event the scrape step is skipped; re-run is safe.
- **PDF deduplication**: files already present on disk are not re-downloaded.
- **Rate-limit handling**: automatic exponential back-off on HTTP 429 responses.

