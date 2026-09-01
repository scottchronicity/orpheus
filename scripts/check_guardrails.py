#!/usr/bin/env python3
"""Static guardrails for the non-negotiables that a machine can actually check.

Several AGENTS.md rules describe *drift* that only bites weeks later — a new agent
that CI never learned to test (#5), a design doc that fell out of the published site,
a non-negotiable list that says "12" in one file and lists 11 in another. Humans miss
these in review because nothing is *wrong* in the diff; the wiring is just absent.

This script encodes the mechanically-checkable subset as fast, dependency-free checks
(stdlib only — runs in pre-commit and CI with no venv). It does NOT try to enforce the
judgement rules (#6 schema round-trips, #7 no invented mids); those need the tests and
a human. It catches the boring, verifiable rot:

  1. Agent wiring (#5): every agents/orpheus-agent-* is in the Makefile build set,
     ships a systemd unit + Makefile, and is referenced by the CI workflow.
  2. Docs-site drift (#12 adjacent): every docs/designs/*.md and docs/adr/*.md is
     wired into mkdocs.yml, so a shipped design/decision can't silently 404.
  3. Non-negotiable count coherence (#11): AGENTS.md's "The N non-negotiables"
     matches the numbered list in AGENTS.md and in 00-non-negotiables.md.

Exit 0 = clean, 1 = violations (printed as `path: problem`). It reads the tree and
changes nothing. Wiring: `make guardrails` locally/pre-commit, and the always-on
`guardrails` CI job — which ci-complete requires, so a red guardrail BLOCKS merge
(drift checks that can't gate a merge catch nothing).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable, List, Tuple

REPO = Path(__file__).resolve().parent.parent

# Design/ADR docs that are intentionally NOT nav entries (indexes, meta). Keep this
# list tiny + commented — every addition is a deliberate "this isn't a page" call.
NAV_EXEMPT = {
    "docs/designs/README.md",  # folder index, not a page
    "docs/adr/README.md",  # folder index, not a page
    "docs/adr/template.md",  # the ADR template, not a decision
}


def _read(rel: str) -> str:
    p = REPO / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def check_agent_wiring() -> List[str]:
    """#5: a new agent that isn't in the build set + CI is invisible until it rots."""
    problems: List[str] = []
    agents = sorted(p for p in (REPO / "agents").glob("orpheus-agent-*") if p.is_dir())
    makefile = _read("Makefile")
    ci = _read(".github/workflows/pr-tests.yml")
    for agent in agents:
        name = agent.name  # e.g. orpheus-agent-crow-detection
        rel = f"agents/{name}"
        if not (agent / "Makefile").exists():
            problems.append(f"{rel}/Makefile: missing (every agent needs one — #5)")
        if not list(agent.glob("systemd/*.service")):
            problems.append(f"{rel}/systemd/*.service: missing systemd unit (#5)")
        if name not in makefile:
            problems.append(f"Makefile: '{name}' absent — add it to PYTHON_PROJECTS (#5)")
        if name not in ci:
            problems.append(
                f".github/workflows/pr-tests.yml: '{name}' absent — CI won't test it (#5)"
            )
    return problems


def check_manifest_catalog() -> List[str]:
    """#5-adjacent: an agent missing from manifest_gen's CATALOG generates an
    orpheus.target that silently never starts it. Parse the CATALOG agent names from
    source (stdlib-only, no import) and assert every shipped agent is covered."""
    problems: List[str] = []
    src = _read("platform/orpheus-common/src/orpheus_common/manifest_gen.py")
    if not src:
        return ["platform/orpheus-common/src/orpheus_common/manifest_gen.py: missing"]
    # CATALOG entries look like: Component("audio-motion", "agent", _audio_on),
    cataloged = set(re.findall(r'Component\("([^"]+)",\s*"agent"', src))
    agents_dir = REPO / "agents"
    for agent in sorted(agents_dir.glob("orpheus-agent-*")):
        if not agent.is_dir() or not list(agent.glob("systemd/*.service")):
            continue
        bare = agent.name[len("orpheus-agent-"):]
        if bare not in cataloged:
            problems.append(
                f"manifest_gen.py CATALOG: '{bare}' absent — a generated orpheus.target "
                f"would never start it (#5)"
            )
    return problems


def check_docs_nav() -> List[str]:
    """#12-adjacent: a design/ADR not in mkdocs.yml ships as a dead link on the site."""
    problems: List[str] = []
    nav = _read("mkdocs.yml")
    if not nav:
        return ["mkdocs.yml: missing — cannot verify docs-site wiring"]
    docs = sorted(
        list((REPO / "docs" / "designs").glob("*.md"))
        + list((REPO / "docs" / "adr").glob("*.md"))
    )
    for doc in docs:
        rel = doc.relative_to(REPO).as_posix()
        if rel in NAV_EXEMPT:
            continue
        # mkdocs nav paths are relative to docs/ (e.g. "designs/foo.md").
        nav_path = rel[len("docs/"):]
        if nav_path not in nav:
            problems.append(f"{rel}: not wired into mkdocs.yml nav (would 404 on the site)")
    return problems


def _max_numbered(text: str, pattern: str) -> int:
    nums = [int(m) for m in re.findall(pattern, text, flags=re.MULTILINE)]
    return max(nums) if nums else 0


def check_nonnegotiable_count() -> List[str]:
    """#11: the count of non-negotiables must agree across the two canonical files."""
    problems: List[str] = []
    agents_md = _read("AGENTS.md")
    nn_md = _read("docs/agent-instructions/00-non-negotiables.md")

    m = re.search(r"The (\d+) non-negotiables", agents_md)
    if not m:
        return ["AGENTS.md: can't find 'The N non-negotiables' heading"]
    stated = int(m.group(1))

    # AGENTS.md lists them as "1. ", "2. " ... at line start.
    agents_max = _max_numbered(agents_md, r"^(\d+)\. \*\*")
    # 00-non-negotiables.md lists them as "## 1. ", "## 2. " ...
    nn_max = _max_numbered(nn_md, r"^## (\d+)\. ")

    if agents_max != stated:
        problems.append(
            f"AGENTS.md: heading says {stated} non-negotiables but the list goes to {agents_max}"
        )
    if nn_max != stated:
        problems.append(
            f"docs/agent-instructions/00-non-negotiables.md: has {nn_max} numbered items, "
            f"AGENTS.md says {stated}"
        )
    return problems


def check_roadmap_counts() -> List[str]:
    """README's roadmap table must match docs/backlog.json.

    The table restates numbers that live in the ledger, so every story added or
    retired silently falsifies the front page — it drifted three times in one
    branch before this check existed.
    """
    import json as _json

    problems: List[str] = []
    ledger_raw = _read("docs/backlog.json")
    readme = _read("README.md")
    if not ledger_raw or not readme:
        return ["docs/backlog.json or README.md: missing — cannot verify roadmap counts"]
    try:
        issues = _json.loads(ledger_raw).get("issues", [])
    except ValueError as exc:
        return [f"docs/backlog.json: not valid JSON ({exc})"]

    total = len(issues)
    claimed_total = re.search(r"(\d+)\s+open stories", readme)
    if not claimed_total:
        problems.append("README.md: can't find the 'N open stories' line")
    elif int(claimed_total.group(1)) != total:
        problems.append(
            f"README.md says {claimed_total.group(1)} open stories; "
            f"docs/backlog.json holds {total}"
        )

    per_theme: dict = {}
    for issue in issues:
        milestone = issue.get("milestone")
        if milestone:
            per_theme[milestone] = per_theme.get(milestone, 0) + 1
    # Table rows read: | **Theme** | description | N |
    for name, count in sorted(per_theme.items()):
        row = re.search(
            r"^\|\s*\*\*" + re.escape(name) + r"\*\*\s*\|[^|]*\|\s*(\d+)\s*\|",
            readme,
            re.MULTILINE,
        )
        if not row:
            problems.append(f"README.md: no roadmap row for theme '{name}'")
        elif int(row.group(1)) != count:
            problems.append(
                f"README.md row '{name}' says {row.group(1)}; ledger holds {count}"
            )
    return problems


CHECKS: Tuple[Tuple[str, Callable[[], List[str]]], ...] = (
    ("agent wiring (#5)", check_agent_wiring),
    ("manifest catalog (#5)", check_manifest_catalog),
    ("docs-site nav (#12)", check_docs_nav),
    ("non-negotiable count (#11)", check_nonnegotiable_count),
    ("roadmap counts (#12)", check_roadmap_counts),
)


def main() -> int:
    all_problems: List[str] = []
    for label, check in CHECKS:
        problems = check()
        status = "OK" if not problems else f"{len(problems)} problem(s)"
        print(f"  [{'✓' if not problems else '✗'}] {label}: {status}")
        all_problems.extend(f"    {p}" for p in problems)
    if all_problems:
        print("\nGuardrail violations:")
        print("\n".join(all_problems))
        print(
            "\nThese are drift checks (see AGENTS.md). Fix the wiring, or if a doc is "
            "intentionally not a page, add it to NAV_EXEMPT in scripts/check_guardrails.py."
        )
        return 1
    print("\nAll guardrails pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
