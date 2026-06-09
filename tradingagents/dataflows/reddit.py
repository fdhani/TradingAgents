"""Reddit search fetcher for ticker-specific discussion posts.

Uses Reddit's OAuth API (``oauth.reddit.com``) via the app-only
client-credentials grant when ``REDDIT_CLIENT_ID`` / ``REDDIT_CLIENT_SECRET``
are set. Authenticated requests are tied to your Reddit app rather than
anonymous-IP reputation, so they keep working from IPs where Reddit now
blocks unauthenticated ``.json`` access (HTTP 403 "Blocked").

If no credentials are configured it falls back to the legacy public
``reddit.com/r/{sub}/search.json`` endpoint, which Reddit increasingly
blocks. Either way the module degrades gracefully — it returns a
placeholder string rather than raising, so callers never have to
special-case missing data.

Set up: create a "script" app at https://www.reddit.com/prefs/apps, then
export ``REDDIT_CLIENT_ID`` and ``REDDIT_CLIENT_SECRET``.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_OAUTH_API = "https://oauth.reddit.com/r/{sub}/search?{qs}"
_ANON_API = "https://www.reddit.com/r/{sub}/search.json?{qs}"
# Reddit asks for a unique, descriptive User-Agent; bare/generic agents get
# rate-limited or blocked. Override via REDDIT_USER_AGENT if desired.
_UA = os.environ.get(
    "REDDIT_USER_AGENT",
    "python:tradingagents:0.2 (+https://github.com/TauricResearch/TradingAgents)",
)

# Cache the app-only bearer token (valid ~1h) across calls within a run.
_token_cache: dict = {"token": None, "expires_at": 0.0}

# Default subreddits ordered roughly by signal density for ticker-specific
# discussion. wallstreetbets has the most volume but most noise; stocks /
# investing trend more measured. Caller can override.
DEFAULT_SUBREDDITS = ("wallstreetbets", "stocks", "investing")


def _get_token(timeout: float) -> str | None:
    """Return a cached or freshly-fetched app-only OAuth bearer token, or
    ``None`` if credentials are unset or the token request fails."""
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]

    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urlencode({"grant_type": "client_credentials"}).encode()
    req = Request(
        _TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {creds}",
            "User-Agent": _UA,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read())
    except (HTTPError, URLError, json.JSONDecodeError, TimeoutError) as exc:
        logger.warning("Reddit OAuth token request failed: %s", exc)
        return None

    token = payload.get("access_token")
    if not token:
        logger.warning("Reddit OAuth token response missing access_token")
        return None
    expires_in = payload.get("expires_in", 3600)
    # Refresh a minute early to avoid using a token mid-expiry.
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + float(expires_in) - 60
    return token


def _fetch_subreddit(
    ticker: str,
    sub: str,
    limit: int,
    timeout: float,
    token: str | None,
) -> list[dict]:
    qs = urlencode({
        "q": ticker,
        "restrict_sr": "true",
        "sort": "new",
        "t": "week",  # last 7 days
        "limit": limit,
    })
    if token:
        url = _OAUTH_API.format(sub=sub, qs=qs)
        headers = {"Authorization": f"bearer {token}", "User-Agent": _UA}
    else:
        url = _ANON_API.format(sub=sub, qs=qs)
        headers = {"User-Agent": _UA, "Accept": "application/json"}
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read())
    except (HTTPError, URLError, json.JSONDecodeError, TimeoutError) as exc:
        logger.warning("Reddit fetch failed for r/%s · %s: %s", sub, ticker, exc)
        return []
    children = (payload.get("data") or {}).get("children") or []
    return [c.get("data", {}) for c in children if isinstance(c, dict)]


def fetch_reddit_posts(
    ticker: str,
    subreddits: Iterable[str] = DEFAULT_SUBREDDITS,
    limit_per_sub: int = 5,
    timeout: float = 10.0,
    inter_request_delay: float = 0.4,
) -> str:
    """Fetch recent Reddit posts mentioning ``ticker`` across finance
    subreddits and return them as a formatted plaintext block.

    ``inter_request_delay`` keeps us under Reddit's rate limit (OAuth allows
    ~100 req/min; the public endpoint ~10 req/min) even if the caller queries
    many subreddits.
    """
    subreddits = list(subreddits)
    token = _get_token(timeout)
    if token is None and (os.environ.get("REDDIT_CLIENT_ID") or os.environ.get("REDDIT_CLIENT_SECRET")):
        logger.warning(
            "Reddit credentials set but token unavailable; falling back to "
            "unauthenticated requests (likely to be blocked)."
        )

    blocks = []
    total_posts = 0
    for i, sub in enumerate(subreddits):
        if i > 0:
            time.sleep(inter_request_delay)
        posts = _fetch_subreddit(ticker, sub, limit_per_sub, timeout, token)
        total_posts += len(posts)
        if not posts:
            blocks.append(f"r/{sub}: <no posts found mentioning {ticker.upper()} in the past 7 days>")
            continue

        lines = [f"r/{sub} — {len(posts)} recent posts mentioning {ticker.upper()}:"]
        for p in posts:
            title = (p.get("title") or "").replace("\n", " ").strip()
            score = p.get("score", 0)
            comments = p.get("num_comments", 0)
            created = p.get("created_utc")
            created_str = (
                time.strftime("%Y-%m-%d", time.gmtime(created)) if created else "?"
            )
            selftext = (p.get("selftext") or "").replace("\n", " ").strip()
            if len(selftext) > 240:
                selftext = selftext[:240] + "…"
            lines.append(
                f"  [{created_str} · {score:>4}↑ · {comments:>3}c] {title}"
                + (f"\n    body excerpt: {selftext}" if selftext else "")
            )
        blocks.append("\n".join(lines))

    if total_posts == 0:
        return (
            f"<no Reddit posts found mentioning {ticker.upper()} across "
            f"{', '.join(f'r/{s}' for s in subreddits)} in the past 7 days>"
        )
    return "\n\n".join(blocks)
