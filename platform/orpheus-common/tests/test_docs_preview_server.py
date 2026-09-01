"""The docs preview server's redirect, as behaviour rather than as text.

``serve_docs_preview.py`` sends anything outside the deployment prefix to its
equivalent inside it. The redirect target was built by concatenating the request
path onto the prefix, so a request path carrying CR/LF split the response and
injected headers of the attacker's choosing. It is a local preview helper that
never deploys, which bounds the damage but does not make it correct.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "scripts" / "serve_docs_preview.py"


@pytest.fixture(scope="module")
def handler_cls():
    if not SCRIPT.is_file():
        pytest.skip("serve_docs_preview.py not present in this checkout")
    spec = importlib.util.spec_from_file_location("_serve_docs_preview", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PrefixHandler


class _Recorder:
    """Captures what the handler would put on the wire."""

    def __init__(self, path):
        self.path = path
        self.prefix = "/orpheus/"
        self.headers_sent = []
        self.status = None

    def send_response(self, code):
        self.status = code

    def send_header(self, key, value):
        self.headers_sent.append((key, value))

    def send_error(self, code, message=None):
        self.status = code
        self.error_message = message

    def end_headers(self):
        pass


def _redirect(handler_cls, path):
    rec = _Recorder(path)
    handled = handler_cls._redirect_outside_prefix(rec)
    return rec, handled


@pytest.mark.parametrize(
    "hostile",
    [
        "/x\r\nSet-Cookie: session=stolen",
        "/x\nSet-Cookie: session=stolen",
        "/x\r\n\r\n<html>injected</html>",
        "/\rLocation: https://evil.example.com",
    ],
)
def test_crlf_is_refused_outright(handler_cls, hostile):
    """A line break in the path is a malformed request, not a redirect."""
    rec, handled = _redirect(handler_cls, hostile)

    assert handled is True
    assert rec.status == 400
    assert rec.headers_sent == []


@pytest.mark.parametrize("hostile", ["/x%0d%0aSet-Cookie:+a=b", "/a b", "/\u00e9t\u00e9"])
def test_anything_else_reaches_the_header_encoded(handler_cls, hostile):
    """Whatever survives the reject is still percent-encoded, never raw."""
    rec, handled = _redirect(handler_cls, hostile)

    assert handled is True
    assert rec.status == 302
    assert len(rec.headers_sent) == 1
    key, value = rec.headers_sent[0]
    assert key == "Location"
    assert "\r" not in value and "\n" not in value
    assert " " not in value


def test_an_ordinary_path_still_redirects_into_the_prefix(handler_cls):
    rec, handled = _redirect(handler_cls, "/docs/index.html")

    assert handled is True
    assert rec.headers_sent == [("Location", "/orpheus/docs/index.html")]


def test_a_query_string_survives_the_encoding(handler_cls):
    rec, _ = _redirect(handler_cls, "/search?q=nats&scope=all")

    assert rec.headers_sent == [("Location", "/orpheus/search?q=nats&scope=all")]


def test_a_path_already_inside_the_prefix_is_not_redirected(handler_cls):
    rec = _Recorder("/orpheus/docs/")

    assert handler_cls._redirect_outside_prefix(rec) is False
    assert rec.headers_sent == []
    assert rec.path == "/docs/"
