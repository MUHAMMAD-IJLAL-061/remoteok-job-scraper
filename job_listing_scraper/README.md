# Job Listing Scraper (VS Code)

A small, maintainable Python scraper for Remote OK's public JSON feed. It uses Requests for HTTP, BeautifulSoup for text cleanup of HTML fragments, dataclasses for the `Job` model, and CSV + JSON exports.

## Requirements

- Python 3.10+
- Internet access
- VS Code with the Python extension (recommended)

## Setup in VS Code

Open this folder in VS Code, then open **Terminal → New Terminal**.

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, use `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`, then run with `.\.venv\Scripts\python.exe main.py python`.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Run

```bash
python main.py python
python main.py data
python main.py automation
python main.py
python main.py python --output-dir exports --delay 1.5
```

The keyword is a case-insensitive substring match across title, company, location, and salary. Omit it to export all records returned by the feed.

## Output

Each run creates timestamped files under `output/` by default:

- `jobs_YYYYMMDD_HHMMSS.csv`
- `jobs_YYYYMMDD_HHMMSS.json`

Fields: `title`, `company`, `location`, `salary`, `job_url`, `date_posted`, `source`.

## Architecture / maintenance

- `Job`: normalized, stable output model.
- `JobScraper`: robots policy, HTTP/retry behavior, parsing, filtering, and exports.
- `main()`: CLI, summary, and lifecycle.
- All source mappings and operational settings are at the top of `main.py`.

### Important pagination note

Remote OK's documented `/api` feed is a current snapshot and does not provide a documented page/offset parameter. This implementation processes every record returned by that feed and deduplicates records; it does not pretend the endpoint has pagination. If you need multi-page historical collection, add a separately verified, permitted paginated source (for example, a board's public HTML listing pages) behind a source adapter.

### If the scraper breaks

1. Open `https://remoteok.com/api` and verify the response is a JSON array.
2. Inspect `position`, `company`, `location`, `salary_min`, `salary_max`, `date`, `epoch`, and `url` in the response.
3. Update the field mapping in `JobScraper.parse_job()`, `_salary()`, or `_date_posted()` as appropriate.
4. Check `https://remoteok.com/robots.txt` and `https://remoteok.com/legal` before changing request behavior.
5. Do not bypass access-denied responses or anti-bot controls. The scraper stops rather than attempting evasion.

### Polite use and attribution

The script checks `robots.txt`, enforces a minimum one-second interval, retries transient errors with exponential backoff and jitter, and respects `Retry-After`. Remote OK asks users of its feed to mention Remote OK as the source and link directly to original job listings with a normal followable link when republishing/reusing data. Review the site's current terms before redistribution.

## Scope

The feed may contain only a limited set of current listings. A missing salary is exported as an empty string; zero salary bounds are treated as undisclosed rather than as an unpaid role. This script does not crawl individual job detail pages.
