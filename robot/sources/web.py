"""A polite web client for price sources: our honest name, robots.txt first, a gap between requests, retries on 5xx.

A robots.txt that forbids a URL, answers 401/403 (a wall) or can't be read today means: don't ask (Blocked).
A missing robots.txt (404 and other 4xx) means everything is allowed, as the standard says.
"""
from __future__ import annotations

import gzip
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

USER_AGENT = "PretBun-robot/0.1 (family project)"
AGENT = "PretBun-robot"


class Blocked(Exception):
    """robots.txt (or a wall in front of it) says no: never fetched."""


class Polite:
    def __init__(self, min_interval: float = 3.0, opener=urllib.request.urlopen, sleep=time.sleep, raw_dir: str = None):
        self.min_interval, self.opener, self.sleep, self.raw_dir = min_interval, opener, sleep, raw_dir
        self.skipped, self._robots, self._last, self._n = 0, {}, None, 0

    def allowed(self, url: str) -> bool:
        parts = urllib.parse.urlsplit(url)
        host = "%s://%s" % (parts.scheme, parts.netloc)
        if host not in self._robots:
            self._robots[host] = self._read_robots(host)
        rp = self._robots[host]
        return rp is not None and rp.can_fetch(AGENT, url)

    def _read_robots(self, host: str):
        rp = urllib.robotparser.RobotFileParser()
        try:
            rp.parse(self._fetch(host + "/robots.txt", retry=False).splitlines())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403) or e.code >= 500:
                return None  # a wall, or no answer today
            rp.parse([])  # no robots.txt: everything is allowed
        except (urllib.error.URLError, OSError):
            return None
        return rp

    def get(self, url: str) -> str:
        if not self.allowed(url):
            self.skipped += 1
            raise Blocked(url)
        return self._fetch(url)

    def _fetch(self, url: str, retry: bool = True) -> str:
        for wait in ((5, 10, 20, None) if retry else (None,)):
            if self._last is not None:
                gap = self.min_interval - (time.monotonic() - self._last)
                if gap > 0:
                    self.sleep(gap)
            self._last = time.monotonic()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
            try:
                with self.opener(req, timeout=60) as r:
                    body = r.read()
                break
            except urllib.error.HTTPError as e:
                if e.code < 500 or wait is None:
                    raise
            except OSError:  # a network blip (unreachable, timeout): try again a little later
                if wait is None:
                    raise
            self.sleep(wait)
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        if self.raw_dir:
            self._n += 1
            os.makedirs(self.raw_dir, exist_ok=True)
            with open(os.path.join(self.raw_dir, "%05d.html" % self._n), "wb") as f:
                f.write(body)
        return body.decode("utf-8", "replace")
