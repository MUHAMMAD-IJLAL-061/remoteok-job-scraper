# remoteok-job-scraper

A Python scraper that fetches live job listings from the Remote OK public API, filters them by keyword, and exports the results to CSV and JSON.

---

## What It Does

- Fetches all current job listings from the Remote OK public JSON feed
- Filters listings by a keyword you provide (e.g. `python`, `data`, `automation`)
- Cleans and normalizes all fields — handles missing values, HTML fragments, and salary ranges
- Exports results to timestamped CSV and JSON files in an `output/` folder
- Respects the site's `robots.txt` policy and rate limits before making any request
- Retries automatically on transient server errors (429, 500, 503) with exponential backoff

---

## Project Structure

```
remoteok-job-scraper/
│
├── scraper.py        # Main scraper — all logic lives here
├── output/           # Auto-created on first run, holds exported files
├── requirements.txt  # Dependencies
└── README.md
```

---

## Requirements

- Python 3.10+
- `requests`
- `beautifulsoup4`

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## How to Run

**Scrape all jobs (no filter):**

```bash
python scraper.py
```

**Scrape with a keyword filter:**

```bash
python scraper.py python
python scraper.py "data engineer"
python scraper.py automation
```

**Optional arguments:**

| Argument | Default | Description |
|---|---|---|
| `keyword` | *(none)* | Filter jobs by keyword (title, company, location, salary) |
| `--output-dir` | `output/` | Folder where CSV and JSON files are saved |
| `--delay` | `1.0` | Seconds between requests (minimum 1) |
| `--max-retries` | `5` | Maximum retries on transient failures |

---

## Output

Each run creates two timestamped files inside `output/`:

```
output/
├── jobs_20250610_143022.csv
└── jobs_20250610_143022.json
```

**Fields exported:**

| Field | Description |
|---|---|
| `title` | Job title / position |
| `company` | Company name |
| `location` | Location or "Remote" |
| `salary` | Formatted salary range or empty if undisclosed |
| `job_url` | Direct link to the job listing |
| `date_posted` | ISO 8601 UTC timestamp |
| `source` | Always "Remote OK" |

**Sample terminal output:**

```
--- Scrape summary ---
Source records parsed: 847
Jobs matching filter: 63
Keyword filter: python
CSV export: output/jobs_20250610_143022.csv
JSON export: output/jobs_20250610_143022.json
Time taken: 2.41 seconds
```

---

## How It Works

The scraper hits Remote OK's public JSON API endpoint (`/api`) which returns all current listings in a single response — no pagination required.

Key design decisions:

- **`Job` is a frozen dataclass** — fields are immutable after creation, preventing accidental data mutation during export
- **Exponential backoff with jitter** — on a 429 or 503 response, the scraper waits `2^attempt + random(0–0.5)` seconds before retrying, avoiding thundering herd problems
- **`robots.txt` checked first** — the scraper reads and respects the site's crawl policy before making any data request
- **HTML sanitization** — some API fields return HTML fragments; BeautifulSoup strips tags safely before storing

---

## Ethics and Rate Limiting

- This scraper only accesses Remote OK's **public API** — no login, no private data
- A minimum 1-second delay is enforced between requests
- The site's `robots.txt` is checked and respected on every run
- Exported data includes the source name and original job URLs as required by Remote OK's attribution policy
- Do not reduce `--delay` below 1.0 — this respects the site's published `Crawl-delay` rule

---

## Libraries Used

| Library | Purpose |
|---|---|
| `requests` | HTTP requests and session management |
| `beautifulsoup4` | HTML fragment sanitization in API fields |
| `dataclasses` | Clean, immutable `Job` data structure |
| `argparse` | Command-line argument handling |
| `csv` / `json` | Standard library export |
| `urllib.robotparser` | robots.txt compliance checking |

---

## Author
M ijlal
Built as part of a Python automation and freelancing portfolio.
