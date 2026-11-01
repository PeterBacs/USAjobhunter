"""Polite HTTP client: robots.txt compliance, per-host rate limiting and a fetch log.

Every request made during a scan is written to ScanLog so the Scan Monitor can show
URL, HTTP status, crawl status, parser status, jobs discovered and errors.
"""
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from ..config import HTTP_TIMEOUT, PER_HOST_DELAY, USER_AGENT


@dataclass
class FetchResult:
    url: str
    status: int | None
    text: str
    crawl_status: str  # FETCHED | ROBOTS_BLOCKED | ERROR
    error: str | None = None
    elapsed_ms: int = 0
    final_url: str | None = None

    @property
    def ok(self) -> bool:
        return self.crawl_status == "FETCHED" and self.status is not None and 200 <= self.status < 300

    def json(self):
        import json
        return json.loads(self.text)


class PoliteClient:
    _robots: dict[str, RobotFileParser | None] = {}
    _robots_lock = threading.Lock()
    _last_hit: dict[str, float] = {}
    _rate_lock = threading.Lock()

    def __init__(self, log_fn=None):
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"},
            timeout=HTTP_TIMEOUT,
            follow_redirects=True,
        )
        self.log_fn = log_fn  # callable(FetchResult, source_name) -> ScanLog row

    def close(self):
        self.client.close()

    # ------------------------------------------------------------ robots
    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        with self._robots_lock:
            if base not in self._robots:
                rp = RobotFileParser()
                try:
                    r = self.client.get(base + "/robots.txt", timeout=15)
                    if r.status_code >= 400:
                        rp = None  # no robots.txt -> allowed
                    else:
                        rp.parse(r.text.splitlines())
                except Exception:
                    rp = None
                self._robots[base] = rp
            rp = self._robots[base]
        if rp is None:
            return True
        return rp.can_fetch(USER_AGENT, url)

    def _wait_turn(self, url: str):
        host = urlparse(url).netloc
        with self._rate_lock:
            last = self._last_hit.get(host, 0)
            wait = PER_HOST_DELAY - (time.monotonic() - last)
            self._last_hit[host] = max(time.monotonic(), last + PER_HOST_DELAY)
        if wait > 0:
            time.sleep(wait)

    # ------------------------------------------------------------ fetch
    def get(self, url: str, source_name: str | None = None, log: bool = True, api: bool = False, **kw) -> FetchResult:
        """api=True: a keyed, licensed API call (e.g. JSearch, Adzuna). robots.txt governs crawling, not
        authenticated API access, so it is not consulted; query parameters (which may hold keys) are never logged."""
        if not api and not self.allowed(url):
            res = FetchResult(url, None, "", "ROBOTS_BLOCKED", "Disallowed by robots.txt")
        else:
            self._wait_turn(url)
            t0 = time.monotonic()
            try:
                r = self.client.get(url, **kw)
                res = FetchResult(url, r.status_code, r.text, "FETCHED",
                                  None if r.status_code < 400 else f"HTTP {r.status_code}",
                                  int((time.monotonic() - t0) * 1000), url if api else str(r.url))
            except Exception as e:  # network error, timeout, TLS ...
                res = FetchResult(url, None, "", "ERROR", type(e).__name__ if api else f"{type(e).__name__}: {e}",
                                  int((time.monotonic() - t0) * 1000))
        if log and self.log_fn:
            self.log_fn(res, source_name)
        return res
