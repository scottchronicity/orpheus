"""Serve the assembled Pages artifact under the prefix GitHub Pages will use.

``mkdocs serve`` answers at the site root, but the published site lives at
``https://scottchronicity.github.io/orpheus/docs/`` — one level down, so the
Pages root stays free for anything else that goes there. Anything resolving
against the base — the search index, asset URLs, canonical links — behaves
differently in the dev server than in production, and a subpath mistake is
invisible until the site is public.

This serves the assembled artifact (``make docs-pages``: placeholder at the
root, site under ``docs/``) at the real prefix, so a click here is the click a
reader gets. Root-level requests redirect into the prefix rather than 404,
because a reader who trims the URL should still land somewhere.

Usage: serve_docs_preview.py [--dir site-pages] [--prefix /orpheus/] [--port 8000]
"""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import sys
from pathlib import Path
from urllib.parse import quote


class PrefixHandler(http.server.SimpleHTTPRequestHandler):
    """Strip the deployment prefix before falling through to static serving."""

    prefix = "/orpheus/"

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if self._redirect_outside_prefix():
            return
        super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib naming
        if self._redirect_outside_prefix():
            return
        super().do_HEAD()

    def _redirect_outside_prefix(self) -> bool:
        """Send anything outside the prefix to its equivalent inside it."""
        if self.path.startswith(self.prefix):
            self.path = self.path[len(self.prefix) - 1 :] or "/"
            return False
        # A request path is not allowed to carry line breaks: concatenated into
        # the Location header they would end it and start headers of the
        # caller's choosing. Refuse outright rather than redirect somewhere
        # surprising, then percent-encode what remains so nothing else in the
        # path can reach the header raw either.
        if any(c in self.path for c in "\r\n\x00"):
            self.send_error(400, "Invalid request path")
            return True
        target = quote(self.path, safe="/?=&#+,;:@$!*'()~")
        self.send_response(302)
        self.send_header("Location", self.prefix.rstrip("/") + target)
        self.end_headers()
        return True

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("  %s\n" % (fmt % args))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="site-pages", help="assembled Pages artifact")
    parser.add_argument("--prefix", default="/orpheus/", help="deployment path prefix")
    parser.add_argument("--port", type=int, default=8000, help="port to listen on")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "address to bind. Loopback by default. Pass 0.0.0.0 to read the site "
            "from a phone or another machine on the same network."
        ),
    )
    args = parser.parse_args()

    root = Path(args.dir)
    if not (root / "index.html").is_file():
        print(f"No Pages artifact at {root}/ — run 'make docs-pages' first.", file=sys.stderr)
        return 1

    prefix = args.prefix if args.prefix.endswith("/") else args.prefix + "/"
    handler = functools.partial(PrefixHandler, directory=str(root))
    PrefixHandler.prefix = prefix

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((args.host, args.port), handler) as httpd:
        shown = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host
        url = f"http://{shown}:{args.port}{prefix}"
        print(f"\n  Serving the Pages artifact as it will be published: {url}")
        print(f"  The documentation itself is at {url}docs/")
        print("  This is the production layout, not the dev server — Ctrl-C to stop.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
