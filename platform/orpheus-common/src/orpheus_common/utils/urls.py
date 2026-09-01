"""
URL utilities for Orpheus.

Connection URLs routinely carry credentials in their userinfo section
(``rtsp://user:pass@camera``, ``nats://user:pass@broker``). Those URLs end up
in logs and diagnostic payloads, so redaction has to happen at every emission
point rather than being left to the caller to remember.
"""

import re

# scheme://[userinfo@]rest — userinfo is everything before the LAST '@' in the
# authority, so passwords containing '@' still redact cleanly.
_USERINFO_RE = re.compile(r"^(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)(?P<userinfo>[^/]*@)")

REDACTED = "***"


def redact_url_credentials(url: str) -> str:
    """Return ``url`` with any userinfo credentials replaced by a placeholder.

    Non-URL strings and URLs without credentials are returned unchanged, so
    this is safe to apply unconditionally at a logging site.

        >>> redact_url_credentials("rtsp://alice:hunter2@cam-1/stream")
        'rtsp://***@cam-1/stream'
    """
    if not url:
        return url
    return _USERINFO_RE.sub(rf"\g<scheme>{REDACTED}@", url, count=1)
