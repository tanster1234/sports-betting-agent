"""Data fetchers with offline-testable parsers.

Network calls use urllib only.  Every fetcher is split into ``*_url`` (build
the request), ``fetch_json`` (do the request) and ``parse_*`` (pure function
on the JSON), so the parsers are unit-tested against real captured payloads
even where the network is blocked.
"""

import json
import urllib.error
import urllib.request

USER_AGENT = "betlab/1.0 (+https://github.com/tanster1234/sports-betting-agent)"


class FetchError(RuntimeError):
    pass


def fetch_json(url: str, timeout: float = 20.0, headers: dict = None):
    """GET a URL and decode JSON.  Returns (data, response_headers)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            hdrs = {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} for {url.split('apiKey=')[0]}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise FetchError(
            f"network error for {url.split('?')[0]}: {exc}. If you are in a sandbox/cloud session the host may "
            "be blocked by the network policy — fall back to WebSearch/WebFetch or run this on your own machine."
        ) from exc
    try:
        return json.loads(body), hdrs
    except json.JSONDecodeError as exc:
        raise FetchError(f"non-JSON response from {url.split('?')[0]}") from exc
