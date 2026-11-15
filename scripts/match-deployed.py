#!/usr/bin/env python3
"""Which commit is actually deployed, and would deploying REV revert any of it?

``/opt/orpheus`` is an rsync tree with no Git metadata, so neither
``make show-deployed`` nor a checkout's HEAD proves what is running. This
hashes each deployed component's source files the way Git does and finds the
commits whose tree for that path is byte-for-byte identical.

    python3 scripts/match-deployed.py                      # what is deployed
    python3 scripts/match-deployed.py --against origin/main # is it all in REV?

With ``--against REV`` each component is ✅ when a commit matching the deployed
code is REV itself or one of its ancestors (deploying REV moves forward), and
❌ when none is (the station runs commits REV does not contain, so deploying REV
would revert them). It exits 1 if any component is ❌ or unmatched. The
station once ran five local-only commits that a release branch lacked.

Read-only: runs ``git hash-object`` without ``-w``, ``ls-tree``, ``rev-list``
and ``merge-base``, and writes nothing but stdout. Candidate commits are every
ref in the repository (``--all``, including e.g. imported refs) unless
``--revs`` narrows them. Python 3.8+, standard library only.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SKIP_PARTS = ("__pycache__", ".egg-info")
SKIP_SUFFIXES = (".pyc", ".pyo")


def run_git(repo: Path, *args: str, stdin: Optional[str] = None, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], input=stdin, capture_output=True, text=True, check=check
    )


def git_out(repo: Path, *args: str) -> str:
    return run_git(repo, *args).stdout


def skipped(rel: str) -> bool:
    parts = rel.split("/")
    return any(any(s in p for s in SKIP_PARTS) for p in parts) or rel.endswith(SKIP_SUFFIXES)


def components(prefix: Path) -> Dict[str, Path]:
    """Repo path -> deployed path, for every component the layout knows."""
    found = {
        "platform/orpheus-common/src": prefix / "platform/orpheus-common/src",
        "services/orpheus_ui/backend/src": prefix / "ui/src",
    }
    for kind in ("agents", "services"):
        base = prefix / kind
        if base.is_dir():
            for d in sorted(base.iterdir()):
                # An unreadable component is still listed, so it is reported
                # instead of silently missing from the answer.
                if (d / "src").is_dir() if os.access(d, os.R_OK | os.X_OK) else d.is_dir():
                    found[f"{kind}/{d.name}/src"] = d / "src"
    return found


def deployed_hashes(repo: Path, root: Path) -> Dict[str, str]:
    files: List[Tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not skipped(d))
        for f in sorted(filenames):
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if not skipped(rel):
                files.append((rel, p))
    if not files:
        return {}
    # With filters, as `git add` would store them: Git LFS files (*.wav, model
    # weights) are committed as pointer blobs, which only the clean filter
    # reproduces. Without git-lfs installed those files cannot match.
    res = run_git(repo, "hash-object", "--stdin-paths", stdin="\n".join(p for _, p in files), check=True)
    return dict(zip((rel for rel, _ in files), res.stdout.split()))


def ignored_paths(repo: Path, path: str, rels: List[str]) -> set:
    """Deployed files Git ignores at this path, e.g. the UI's built static/."""
    if not rels:
        return set()
    res = run_git(repo, "check-ignore", "--no-index", "--stdin", stdin="\n".join(f"{path}/{r}" for r in rels))
    return {line[len(path) + 1:] for line in res.stdout.splitlines()}


def tree_hashes(repo: Path, commit: str, path: str) -> Dict[str, str]:
    out = {}
    for line in git_out(repo, "ls-tree", "-r", commit, "--", path).splitlines():
        meta, p = line.split("\t", 1)
        rel = p[len(path) + 1:] if p.startswith(path + "/") else p
        if not skipped(rel):
            out[rel] = meta.split()[2]
    return out


def label(repo: Path, commit: str) -> str:
    return git_out(repo, "log", "-1", "--format=%h %ad %s", "--date=short", commit).strip()


def is_ancestor(repo: Path, commit: str, rev: str) -> bool:
    return run_git(repo, "merge-base", "--is-ancestor", commit, rev).returncode == 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", type=Path, default=None, help="Git repository (default: the one containing this script)")
    parser.add_argument("--prefix", type=Path, default=Path(os.environ.get("DEPLOY_PREFIX", "/opt/orpheus")))
    parser.add_argument("--against", metavar="REV", help="report whether REV contains every deployed component")
    parser.add_argument("--revs", nargs="+", default=["--all"], help="rev-list arguments for candidates (default --all)")
    parser.add_argument("--max-count", type=int, default=3000, help="newest N candidate commits (default 3000)")
    args = parser.parse_args(argv)

    repo = args.repo or Path(__file__).resolve().parent.parent
    if run_git(repo, "rev-parse", "--git-dir").returncode != 0:
        print(f"ERROR: {repo} is not a Git repository", file=sys.stderr)
        return 2
    if not args.prefix.is_dir():
        print(f"nothing deployed at {args.prefix}")
        return 0
    against = None
    if args.against:
        against = git_out(repo, "rev-parse", "--verify", "--quiet", args.against + "^{commit}").strip()
        if not against:
            print(f"ERROR: {args.against} is not a commit in {repo}", file=sys.stderr)
            return 2

    candidates = git_out(repo, "rev-list", f"--max-count={args.max_count}", *args.revs).split()
    if against and against not in candidates:
        candidates.insert(0, against)

    print(f"Deployed at {args.prefix}, matched against {len(candidates)} commit(s) in {repo}")
    if against:
        print(f"Would deploying {args.against} ({label(repo, against)}) keep everything that is deployed?")
    bad = 0
    for path, deployed in components(args.prefix).items():
        if deployed.parent.exists() and not os.access(deployed.parent, os.R_OK | os.X_OK):
            print(f"  ❌ {path}: {deployed.parent} is not readable as this user; rerun with sudo")
            bad = 1
            continue
        if not deployed.is_dir():
            continue
        mine = deployed_hashes(repo, deployed)
        ignored = ignored_paths(repo, path, sorted(mine))
        trees: Dict[str, List[str]] = {}
        for c in candidates:
            tree_id = run_git(repo, "rev-parse", "--verify", "--quiet", f"{c}:{path}").stdout.strip()
            if tree_id:
                trees.setdefault(tree_id, []).append(c)
        scored = []
        for tree_id, commits in trees.items():
            theirs = tree_hashes(repo, commits[0], path)
            # A deployed file Git ignores and this commit does not track is a
            # build product (e.g. static assets built at install), not source.
            diff = sorted(
                k for k in set(mine) | set(theirs)
                if mine.get(k) != theirs.get(k) and not (k in ignored and k not in theirs)
            )
            scored.append((len(diff), tree_id, diff))
        scored.sort(key=lambda s: s[0])
        if not scored:
            print(f"  ❌ {path}: no candidate commit contains this path")
            bad = 1
            continue
        n, tree_id, diff = scored[0]
        commits = trees[tree_id]
        if n:
            print(f"  ❌ {path}: no exact match; closest differs in {n} file(s): "
                  + ", ".join(diff[:6]) + (" …" if len(diff) > 6 else ""))
            bad = 1
            continue
        span = label(repo, commits[-1]) if len(commits) == 1 else f"{label(repo, commits[-1])} … {label(repo, commits[0])}"
        if not against:
            print(f"  ✅ {path}: matches {len(commits)} commit(s): {span}")
            continue
        if any(c == against or is_ancestor(repo, c, against) for c in commits):
            print(f"  ✅ {path}: {args.against} contains the deployed code ({span})")
        else:
            print(f"  ❌ {path}: deployed code matches {span}, which {args.against} does not contain;"
                  " deploying it would revert those changes")
            bad = 1
    return bad


if __name__ == "__main__":
    sys.exit(main())
