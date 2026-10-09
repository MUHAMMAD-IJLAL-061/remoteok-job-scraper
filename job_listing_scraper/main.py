"""Remote OK job scraper with filtering, normalization, retries, and CSV/JSON exports."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from requests import Response
from requests.exceptions import RequestException

# ------------------------------ Configuration ------------------------------

BASE_URL = "https://remoteok.com"
API_URL = f"{BASE_URL}/api"
ROBOTS_URL = f"{BASE_URL}/robots.txt"
USER_AGENT = "JobListingResearchBot/1.0 (polite public-feed client)"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT_SECONDS = 25
MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 1.0
DEFAULT_DELAY_SECONDS = 1.0
OUTPUT_DIR = Path("output")
FIELDS = ["title", "company", "location", "salary", "job_url", "date_posted", "source"]


@dataclass(frozen=True)
class Job:

    title: str
    company: str
    location: str
    salary: str
    job_url: str
    date_posted: str
    source: str = "Remote OK"

    def matches(self, keyword: str) -> bool:
        needle = keyword.strip().casefold()
        if not needle:
            return True
        haystack = " ".join((self.title, self.company, self.location, self.salary)).casefold()
        return needle in haystack


class JobScraper:

    def __init__(
        self,
        keyword: str = "",
        output_dir: Path = OUTPUT_DIR,
        max_retries: int = MAX_RETRIES,
        delay_seconds: float = DEFAULT_DELAY_SECONDS,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        self.keyword = keyword.strip()
        self.output_dir = output_dir
        self.max_retries = max(0, max_retries)
        self.delay_seconds = max(1.0, delay_seconds)  # robots.txt publishes Crawl-delay: 1
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._last_request_at = 0.0
        self._robots = self._load_robots_policy()

    def _load_robots_policy(self) -> RobotFileParser:
        parser = RobotFileParser()
        parser.set_url(ROBOTS_URL)
        try:
            response = self.session.get(ROBOTS_URL, timeout=self.timeout)
            response.raise_for_status()
            parser.parse(response.text.splitlines())
        except RequestException as exc:
            # Fail closed if the policy cannot be checked.
            logging.error("Could not retrieve robots.txt; refusing to scrape: %s", exc)
            raise RuntimeError("Unable to verify robots.txt policy; stopping.") from exc
        return parser

    def _pace_request(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self.delay_seconds - elapsed
        if wait > 0:
            time.sleep(wait)

    @staticmethod
    def _retry_after_seconds(response: Response | None) -> float | None:
        if response is None:
            return None
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                retry_date = parsedate_to_datetime(value)
                if retry_date.tzinfo is None:
                    retry_date = retry_date.replace(tzinfo=timezone.utc)
                return max(0.0, (retry_date - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return None

    def _get(self, url: str) -> Response:
        if not self._robots.can_fetch(USER_AGENT, url):
            raise PermissionError(f"robots.txt disallows this URL: {url}")

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._pace_request()
            response: Response | None = None
            try:
                response = self.session.get(url, timeout=self.timeout)
                self._last_request_at = time.monotonic()

                if response.status_code in (429, 500, 502, 503, 504):
                    if attempt >= self.max_retries:
                        response.raise_for_status()
                    retry_after = self._retry_after_seconds(response)
                    delay = retry_after if retry_after is not None else (
                        BACKOFF_BASE_SECONDS * (2 ** attempt) + random.uniform(0, 0.5)
                    )
                    logging.warning(
                        "Transient HTTP %s for %s; retry %d/%d in %.1fs",
                        response.status_code, url, attempt + 1, self.max_retries, delay,
                    )
                    time.sleep(delay)
                    continue
                
                if response.status_code in (401, 403, 404):
                    response.raise_for_status()
                response.raise_for_status()
                return response
            except RequestException as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                delay = BACKOFF_BASE_SECONDS * (2 ** attempt) + random.uniform(0, 0.5)
                logging.warning(
                    "Request failed (%s); retry %d/%d in %.1fs",
                    exc, attempt + 1, self.max_retries, delay,
                )
                time.sleep(delay)

        raise RuntimeError(f"Request failed after retries: {url}") from last_error

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple, set)):
            value = ", ".join(str(item) for item in value if item is not None)
        # BeautifulSoup handles any HTML fragments safely; plain strings remain plain text.
        text = BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _salary(record: dict[str, Any]) -> str:
        """Format explicit salary fields; zero/absent bounds mean undisclosed."""
        raw_salary = JobScraper._clean_text(record.get("salary"))
        if raw_salary:
            return raw_salary
        minimum = record.get("salary_min")
        maximum = record.get("salary_max")
        try:
            low = float(minimum) if minimum not in (None, "") else 0.0
            high = float(maximum) if maximum not in (None, "") else 0.0
        except (TypeError, ValueError):
            return ""
        if low <= 0 and high <= 0:
            return ""
        currency = JobScraper._clean_text(record.get("salary_currency")) or "USD"
        period = JobScraper._clean_text(record.get("salary_period"))
        def amount(number: float) -> str:
            return f"{number:,.0f}" if number.is_integer() else f"{number:,.2f}"
        if low > 0 and high > 0:
            result = f"{currency} {amount(low)}–{amount(high)}"
        elif low > 0:
            result = f"From {currency} {amount(low)}"
        else:
            result = f"Up to {currency} {amount(high)}"
        return f"{result} / {period}" if period else result

    @staticmethod
    def _date_posted(record: dict[str, Any]) -> str:
        raw = record.get("date")
        if raw:
            try:
                parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
            except ValueError:
                pass
        epoch = record.get("epoch")
        if epoch not in (None, ""):
            try:
                return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat(timespec="seconds")
            except (TypeError, ValueError, OverflowError, OSError):
                pass
        return ""

    @classmethod
    def parse_job(cls, record: Any) -> Job | None:
        """Map one feed object into the stable Job schema; skip non-job/malformed objects."""
        if not isinstance(record, dict):
            return None
        # Remote OK's first feed item is a legal/API notice, not a job.
        if record.get("legal") or not (record.get("position") or record.get("id") or record.get("url")):
            return None

        title = cls._clean_text(record.get("position") or record.get("title"))
        company = cls._clean_text(record.get("company") or record.get("company_name"))
        url = cls._clean_text(record.get("url") or record.get("apply_url"))
        if url and url.startswith("//"):
            url = "https:" + url
        if url and urlparse(url).scheme not in ("http", "https"):
            url = ""

        return Job(
            title=title,
            company=company,
            location=cls._clean_text(record.get("location")),
            salary=cls._salary(record),
            job_url=url,
            date_posted=cls._date_posted(record),
        )

    def fetch_jobs(self) -> list[Job]:
        """Fetch the public feed. Remote OK's feed is a snapshot, not offset-paginated."""
        logging.info("Fetching Remote OK public feed")
        response = self._get(API_URL)
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Remote OK returned invalid JSON.") from exc
        if not isinstance(payload, list):
            raise RuntimeError("Unexpected feed schema: expected a JSON array.")

        jobs: list[Job] = []
        seen: set[str] = set()
        for index, record in enumerate(payload):
            try:
                job = self.parse_job(record)
                if job is None:
                    continue
                identity = job.job_url or f"{job.company.casefold()}|{job.title.casefold()}|{job.date_posted}"
                if identity in seen:
                    continue
                seen.add(identity)
                jobs.append(job)
            except (TypeError, ValueError, AttributeError) as exc:
                logging.warning("Skipping malformed record at index %d: %s", index, exc)
        logging.info("Parsed %d unique job records", len(jobs))
        return jobs

    def filter_jobs(self, jobs: Iterable[Job]) -> list[Job]:
        return [job for job in jobs if job.matches(self.keyword)]

    def export(self, jobs: list[Job]) -> tuple[Path, Path]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = self.output_dir / f"jobs_{stamp}.csv"
        json_path = self.output_dir / f"jobs_{stamp}.json"

        with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            for job in jobs:
                writer.writerow(asdict(job))

        with json_path.open("w", encoding="utf-8") as handle:
            json.dump([asdict(job) for job in jobs], handle, ensure_ascii=False, indent=2)

        return csv_path, json_path

    def close(self) -> None:
        self.session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape and filter Remote OK job listings.")
    parser.add_argument("keyword", nargs="?", default="", help='Keyword filter, e.g. "python" or "data"')
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Export directory (default: output)")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS, help="Seconds between requests (minimum 1)")
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES, help="Maximum retries for transient failures")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    started = time.perf_counter()
    scraper = JobScraper(
        keyword=args.keyword,
        output_dir=args.output_dir,
        max_retries=args.max_retries,
        delay_seconds=args.delay,
    )
    try:
        all_jobs = scraper.fetch_jobs()
        matching_jobs = scraper.filter_jobs(all_jobs)
        csv_path, json_path = scraper.export(matching_jobs)
        elapsed = time.perf_counter() - started

        print("\n--- Scrape summary ---")
        print(f"Source records parsed: {len(all_jobs)}")
        print(f"Jobs matching filter: {len(matching_jobs)}")
        print(f"Keyword filter: {args.keyword or '(none)'}")
        print(f"CSV export: {csv_path}")
        print(f"JSON export: {json_path}")
        print(f"Time taken: {elapsed:.2f} seconds")
        print("Attribution: Remote OK — retain the source name and original job links when reusing data.")
        return 0
    except (RuntimeError, PermissionError, RequestException) as exc:
        logging.exception("Scrape failed: %s", exc)
        return 1
    finally:
        scraper.close()


if __name__ == "__main__":
    raise SystemExit(main())
