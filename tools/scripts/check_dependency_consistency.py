#!/usr/bin/env python3
"""
Validate that all requirements.txt files in the monorepo use consistent
dependency versions as defined in requirements-constraints.txt.

Usage:
    python tools/scripts/check_dependency_consistency.py
    
Exit codes:
    0 - All dependencies are consistent
    1 - Inconsistencies found
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ANSI color codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


def parse_requirement(line: str) -> Optional[Tuple[str, str]]:
    """Parse a requirement line into (package_name, version_spec).
    
    Returns None for comments, blank lines, or non-version lines like -e or -c.
    """
    line = line.strip()
    
    # Skip comments, blank lines, and special directives
    if not line or line.startswith('#') or line.startswith('-'):
        return None
    
    # Handle package with version specifier
    # Matches: package>=1.0.0, package==1.0.0, package>=1.0.0,<2.0.0, etc.
    match = re.match(r'^([a-zA-Z0-9_-]+(?:\[[a-zA-Z0-9_,-]+\])?)\s*((?:[><=!~]+[^,\s]+,?\s*)+)?', line)
    if match:
        package = match.group(1).lower()
        # Remove extras like [standard] for comparison
        package = re.sub(r'\[.*\]', '', package)
        version_spec = match.group(2) or ''
        return (package, version_spec.strip())
    
    return None


def load_constraints(constraints_path: Path) -> Dict[str, str]:
    """Load the constraints file and return a dict of package -> version_spec."""
    constraints = {}
    
    if not constraints_path.exists():
        print(f"{RED}Error: Constraints file not found: {constraints_path}{RESET}")
        sys.exit(1)
    
    with open(constraints_path) as f:
        for line in f:
            result = parse_requirement(line)
            if result:
                package, version_spec = result
                constraints[package] = version_spec
    
    return constraints


def load_requirements(req_path: Path) -> Dict[str, str]:
    """Load a requirements.txt file and return a dict of package -> version_spec."""
    requirements = {}
    
    with open(req_path) as f:
        for line in f:
            result = parse_requirement(line)
            if result:
                package, version_spec = result
                requirements[package] = version_spec
    
    return requirements


def check_consistency(
    constraints: Dict[str, str],
    requirements: Dict[str, str],
    req_path: Path
) -> List[str]:
    """Check if requirements match constraints. Returns list of issues."""
    issues = []
    
    for package, req_version in requirements.items():
        if package in constraints:
            constraint_version = constraints[package]
            if req_version != constraint_version:
                issues.append(
                    f"  {package}: has '{req_version}' but constraint says '{constraint_version}'"
                )
    
    return issues


def main():
    repo_root = Path(__file__).parent.parent.parent
    constraints_path = repo_root / "requirements-constraints.txt"
    
    # Find all requirements.txt files. Every package the constraints
    # file pins must be consistent across every project that depends
    # on it — the dashboard-removal PR taught us that "swap path A for
    # path B" in this list without running ``make check-deps`` lets
    # asymmetries through (pytest-asyncio>=0.23 vs >=0.24).
    requirements_files = [
        repo_root / "platform" / "orpheus-common" / "requirements.txt",
        repo_root / "agents" / "orpheus-agent-audio-motion" / "requirements.txt",
        repo_root / "agents" / "orpheus-agent-audio-playback" / "requirements.txt",
        repo_root / "agents" / "orpheus-agent-audio-events" / "requirements.txt",
        repo_root / "agents" / "orpheus-agent-bird-detection" / "requirements.txt",
        repo_root / "agents" / "orpheus-agent-crow-detection" / "requirements.txt",
        repo_root / "agents" / "orpheus-agent-event-correlator" / "requirements.txt",
        repo_root / "agents" / "orpheus-agent-video-motion" / "requirements.txt",
        repo_root / "agents" / "orpheus-agent-video-snapshotter" / "requirements.txt",
        repo_root / "agents" / "orpheus-agent-video-timelapser" / "requirements.txt",
        repo_root / "services" / "orpheus_ui" / "backend" / "requirements.txt",
        repo_root / "services" / "orpheus-backplane" / "requirements.txt",
        repo_root / "services" / "orpheus-gps" / "requirements.txt",
        repo_root / "services" / "orpheus-bluetooth-autoconnect" / "requirements.txt",
    ]
    # Skip any files that don't exist (services that may not have a
    # requirements.txt yet) so the check still runs end-to-end — but say so,
    # so a renamed/moved file can't silently drop out of coverage (this
    # happened with the orpheus-mqtt → orpheus-backplane rename).
    for missing in (p for p in requirements_files if not p.exists()):
        print(f"  (skipping {missing.relative_to(repo_root)} — not present)")
    requirements_files = [p for p in requirements_files if p.exists()]
    
    print(f"{BOLD}Checking dependency consistency across monorepo...{RESET}")
    print(f"Constraints file: {constraints_path}")
    print()
    
    constraints = load_constraints(constraints_path)
    print(f"Loaded {len(constraints)} constraints from requirements-constraints.txt")
    print()
    
    all_issues = {}
    
    for req_path in requirements_files:
        if not req_path.exists():
            print(f"{YELLOW}⚠ Skipping (not found): {req_path.relative_to(repo_root)}{RESET}")
            continue
        
        requirements = load_requirements(req_path)
        issues = check_consistency(constraints, requirements, req_path)
        
        rel_path = req_path.relative_to(repo_root)
        
        if issues:
            all_issues[str(rel_path)] = issues
            print(f"{RED}✗ {rel_path}{RESET}")
            for issue in issues:
                print(f"  {issue}")
        else:
            print(f"{GREEN}✓ {rel_path}{RESET}")
    
    print()
    
    if all_issues:
        print(f"{RED}{BOLD}Dependency inconsistencies found!{RESET}")
        print()
        print("To fix, update the requirements.txt files to match requirements-constraints.txt")
        print("or update requirements-constraints.txt if the new version should be the standard.")
        return 1
    else:
        print(f"{GREEN}{BOLD}✓ All dependencies are consistent!{RESET}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
