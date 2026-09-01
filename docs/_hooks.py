"""Build-time link fixups for the docs site — single-source, source files unchanged.

The root-pinned files (AGENTS.md, README.md, CODING_AGENT_CONTEXT.md, …) are
inlined into stub pages via mkdocs-include-markdown. Their links are written to
work from the repo root, where agents and github.com readers see them, and two
kinds of them break once inlined into a site page:

1. ``](docs/agent-instructions/10-tooling.md)`` — correct from the repo root,
   wrong from a built page, because ``docs_dir`` IS the site root.
2. ``](AGENTS.md)`` / ``](../CONTRIBUTING.md)`` — a link from one root file to
   another. Most of those root files are themselves published, as stub pages
   under different names, so the link has a correct site destination; it just
   is not the one written in the source.

Both are rewritten here, on the stub pages only. The root files are never
edited, so they keep working when read from the repo or on github.com.

Hooks run after declared plugins for ``on_page_markdown``, so this sees the
content already inlined by include-markdown.
"""

from __future__ import annotations

import re

# Stub pages that inline a repo-root file (see mkdocs.yml nav + docs/*.md stubs).
_STUBS = {
    "agents-index.md",
    "project-readme.md",
    "contributing.md",
    "code-of-conduct.md",
    "changelog.md",
    "project-security-policy.md",
}

# Root file -> the stub page that publishes it. A root file with no site page
# (CODING_AGENT_CONTEXT.md) is deliberately absent: it stays a source pointer.
_ROOT_PAGES = {
    "AGENTS.md": "agents-index.md",
    "CONTRIBUTING.md": "contributing.md",
    "README.md": "project-readme.md",
    "CHANGELOG.md": "changelog.md",
    "SECURITY.md": "project-security-policy.md",
    "CODE_OF_CONDUCT.md": "code-of-conduct.md",
}

_GITHUB_BLOB = "https://github.com/scottchronicity/orpheus/blob/main/"

# include-markdown rewrites relative URLs in the included content before this hook
# sees it, so a root file's ``](docs/adr/)`` arrives here already reduced to
# ``](adr/)``. That is correct for a link MkDocs recognises — a ``.md`` path is
# resolved against the stub's SOURCE location (the docs root) and rewritten to the
# right site URL. A bare **directory** is not a documentation file, so MkDocs
# leaves it untouched and it reaches the HTML verbatim; the browser then resolves
# it against the stub's URL — /docs/contributing/ — and lands at
# /docs/contributing/adr/. The ``../`` puts it back at /docs/adr/.
#
# ``](docs/…)`` is still handled below for any content include-markdown did not
# rewrite (a page that sets rewrite_relative_urls false, or a hand-written stub).
_DIR_LINK = re.compile(r"\]\((?!\.{1,2}/|https?://|/)([A-Za-z0-9_][A-Za-z0-9_./-]*/)\)")
_ROOT_REL_DIR = re.compile(r"\]\(\.?/?docs/([^)]*/)\)")
_ROOT_REL_FILE = re.compile(r"\]\(\.?/?docs/")

# Repo-root files that are not published anywhere on the site. Relative is right
# for a checkout and for github.com; the site needs the repo.
_REPO_FILES = re.compile(r"\]\((?:\.{1,2}/)*(LICENSE)\)")

# ``](AGENTS.md)``, ``](./AGENTS.md)``, ``](../AGENTS.md)`` — with an optional
# #fragment, which is preserved.
_ROOT_LINK = re.compile(
    r"\]\((?:\.{1,2}/)*(" + "|".join(re.escape(n) for n in _ROOT_PAGES) + r")(#[^)]*)?\)"
)

# Root files that are NOT published anywhere on the site. Point at the repo so
# the link resolves from the site as well as from a checkout.
_UNPUBLISHED = re.compile(r"\]\((?:\.{1,2}/)*(CODING_AGENT_CONTEXT\.md)(#[^)]*)?\)")


def on_page_markdown(markdown: str, *, page, config, files) -> str:
    if page.file.src_path not in _STUBS:
        return markdown
    markdown = _ROOT_REL_DIR.sub(r"](../\1)", markdown)
    markdown = _ROOT_REL_FILE.sub("](", markdown)
    markdown = _DIR_LINK.sub(r"](../\1)", markdown)
    markdown = _REPO_FILES.sub(lambda m: f"]({_GITHUB_BLOB}{m.group(1)})", markdown)
    markdown = _ROOT_LINK.sub(
        lambda m: f"]({_ROOT_PAGES[m.group(1)]}{m.group(2) or ''})", markdown
    )
    markdown = _UNPUBLISHED.sub(
        lambda m: f"]({_GITHUB_BLOB}{m.group(1)}{m.group(2) or ''})", markdown
    )
    return markdown
