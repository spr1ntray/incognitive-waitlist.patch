from __future__ import annotations

import re

import httpx

from plugin.proxy import proxy_to_url

WAITLIST_URL = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLSdJiT7Z5651_3pOfzfcjLWiXT7ANomAH2ymlT0ql1m9UxKGCA/formResponse"
)
WAITLIST_FIELD = "entry.1176626166"
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


class SafeRequestError(Exception):
    """Network/proxy failure without secret-bearing message text."""

    def __init__(self, code: str = "request_failed") -> None:
        self.code = code
        super().__init__(code)


def normalize_email(raw: str) -> str:
    email = (raw or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise ValueError("invalid_email")
    return email


def submit_waitlist(*, email: str, proxy: str, timeout_seconds: int) -> int:
    """POST email to the Incognitive Google Form via account proxy.

    Returns HTTP status code only. Never returns body, URL, or proxy material.
    httpx errors are mapped to SafeRequestError so proxy credentials in
    library messages cannot reach Hub logs/results.
    """
    email = normalize_email(email)
    proxy_url = proxy_to_url(proxy)
    timeout = httpx.Timeout(timeout_seconds)

    try:
        with httpx.Client(
            proxy=proxy_url,
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/150.0.0.0 Safari/537.36"
                ),
                "Referer": "https://incognitive.ai/",
                "Origin": "https://incognitive.ai",
            },
        ) as client:
            response = client.post(
                WAITLIST_URL,
                data={WAITLIST_FIELD: email},
            )
            status_code = int(response.status_code)
            # Do not read response.text / content — unused and may be large.
            return status_code
    except httpx.TimeoutException:
        raise SafeRequestError("timeout") from None
    except httpx.ProxyError:
        raise SafeRequestError("proxy_error") from None
    except httpx.HTTPError:
        # Covers connect/network/protocol; message may embed proxy URL.
        raise SafeRequestError("request_failed") from None
