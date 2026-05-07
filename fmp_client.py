"""FMP HTTP client. Pure stdlib so it runs on Pyto/iOS."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import config

_last_call = 0.0


class FMPError(Exception):
    def __init__(self, status: int | None, url: str, body: str):
        self.status = status
        self.url = url
        self.body = body
        super().__init__(f"FMP {status} on {url}: {body[:200]}")


def _throttle() -> None:
    global _last_call
    elapsed = time.monotonic() - _last_call
    wait = config.FMP_REQUEST_PAUSE_S - elapsed
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def _build_url(path: str, params: dict | None, base: str | None) -> str:
    base_url = (base or config.FMP_BASE).rstrip("/")
    path = path.lstrip("/")
    query = dict(params or {})
    query["apikey"] = config.FMP_API_KEY
    return f"{base_url}/{path}?{urllib.parse.urlencode(query)}"


def get(path: str, params: dict | None = None, *, base: str | None = None) -> list | dict:
    """GET path on FMP, return parsed JSON. Default base is FMP_BASE.

    Raises FMPError(status, url, body) on persistent failure.
    """
    url = _build_url(path, params, base)
    last_status: int | None = None
    last_body = ""

    for attempt in range(config.FMP_MAX_RETRIES):
        _throttle()
        req = urllib.request.Request(url, headers={"Connection": "close"})
        try:
            with urllib.request.urlopen(req, timeout=config.FMP_TIMEOUT_S) as resp:
                raw = resp.read()
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_status = e.code
            try:
                last_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                last_body = ""
            if e.code == 429 or 500 <= e.code < 600:
                _sleep_backoff(attempt)
                continue
            raise FMPError(e.code, url, last_body) from e
        except (urllib.error.URLError, TimeoutError) as e:
            last_status = None
            last_body = str(e)
            _sleep_backoff(attempt)
            continue

    raise FMPError(last_status, url, last_body)


def _sleep_backoff(attempt: int) -> None:
    time.sleep(0.5 * (2 ** attempt))
