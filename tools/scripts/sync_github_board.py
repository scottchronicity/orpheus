"""Push `docs/backlog.json` to GitHub Issues.

The ledger is the source of truth: this creates the issues it names, and for
issues that already exist it overwrites body, milestone, and labels to match.
Issues the ledger does not name are left alone — closing one is a human's call.

Matching is by title. A ledger entry may also carry `previous_titles`, the
titles it has been filed under before; an entry that matches one of those is
renamed in place rather than filed again.

Usage: sync_github_board.py [path-to-backlog.json] [--dry-run] [--allow-empty-board]

`--dry-run` reads the board and reports every change it would make without
making any of them. Reads run either way; the decision of what to do is made
once and then either executed or printed, so a rehearsal cannot reason
differently from the run it rehearses.
"""

import json
import subprocess
import sys
import os
import re
from collections import Counter

# Repository owner (used for project commands)
GITHUB_OWNER = os.getenv("GITHUB_OWNER", "scottchronicity")
GITHUB_REPO = os.getenv("GITHUB_REPO", "orpheus")

# Stamped on every issue this script touches, and named in the stale workflow's
# exempt list. A roadmap issue is meant to sit open until someone does the work;
# without an exemption the stale bot marks the whole published backlog stale at
# 60 days and closes it at 74. Applied here rather than per-entry in the ledger
# so a new story cannot be seeded without it — and included in the ledger's view
# of an issue's labels below, or the reconciling push would strip it right off
# again.
ROADMAP_LABEL = "roadmap"
PROJECT_NAME = "Orpheus Roadmap"

# Set by --dry-run. Reads run regardless; writes are described instead of made.
DRY_RUN = False

# What the run did, or would do, keyed by action name. Printed as the summary so
# the output answers "what will the board look like afterwards" on its own.
ACTIONS = Counter()


def run_gh_command(args):
    """Executes a GitHub CLI command and returns the output, or None on failure.

    A successful command with nothing to say returns an empty string, so callers
    must test against None rather than for truthiness.
    """
    try:
        result = subprocess.run(
            ["gh"] + args, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(
            "Error running command {}: {}".format(" ".join(args), e.stderr),
            file=sys.stderr,
        )
        return None


def run_gh_write(args, action, description, dry_result=""):
    """Perform a mutating `gh` call, or describe it under --dry-run.

    Every write goes through here so a rehearsal cannot miss one: there is no
    second code path that decides what to do, only a second thing done with the
    decision. ``dry_result`` stands in for the real command's output so the
    passes downstream still reason about the same shape of result.
    """
    ACTIONS[action] += 1
    if DRY_RUN:
        print("  [dry-run] {}".format(description))
        return dry_result
    return run_gh_command(args)


def fetch_existing_labels():
    """{label name} already on the repo, or None when it could not be read."""
    result = run_gh_command([
        "label", "list",
        "--repo", "{}/{}".format(GITHUB_OWNER, GITHUB_REPO),
        "--limit", "200", "--json", "name",
    ])
    if result is None:
        return None
    try:
        return {entry["name"] for entry in json.loads(result)}
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def fetch_existing_milestones():
    """{milestone title} already on the repo, or None when it could not be read."""
    result = run_gh_command([
        "api", "repos/{}/{}/milestones".format(GITHUB_OWNER, GITHUB_REPO),
        "--paginate", "-q", ".[].title",
    ])
    if result is None:
        return None
    return {line.strip() for line in result.splitlines() if line.strip()}


def find_project_number():
    """Find the project number for the Orpheus Roadmap project."""
    result = run_gh_command([
        "project", "list",
        "--owner", GITHUB_OWNER,
        "--format", "json",
    ])
    if not result:
        return None
    try:
        projects = json.loads(result)
        if isinstance(projects, dict):
            project_items = projects.get("projects", [])
        elif isinstance(projects, list):
            project_items = projects
        else:
            return None
        for project in project_items:
            if isinstance(project, dict) and project.get("title") == PROJECT_NAME:
                return project.get("number")
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return None


def parse_issue_number(url_or_output):
    """Extract the issue number from a GitHub issue URL or gh output."""
    match = re.search(r"/issues/(\d+)", url_or_output)
    if match:
        return int(match.group(1))
    # Also try plain number (some gh commands return just the number)
    match = re.search(r"^(\d+)$", url_or_output.strip())
    if match:
        return int(match.group(1))
    return None


def fetch_existing_issues():
    """Fetch every issue and return {title: {number, body, labels, milestone, state}}.

    Returns None when the board could not be read. That is not the same as an
    empty board: an auth failure, a rate limit, or a dropped connection all
    return nothing, and treating nothing as "no issues yet" would file the whole
    ledger a second time. The caller aborts on None.
    """
    print("  Fetching existing issues...")
    # Fetch up to 500 issues (paginated by gh)
    result = run_gh_command([
        "issue", "list",
        "--repo", "{}/{}".format(GITHUB_OWNER, GITHUB_REPO),
        "--state", "all",
        "--limit", "500",
        "--json", "number,title,body,labels,milestone,state"
    ])
    if result is None:
        return None
    try:
        issues = json.loads(result)
    except json.JSONDecodeError:
        print("  Could not parse the existing-issues JSON.", file=sys.stderr)
        return None

    existing = {}
    for issue in issues:
        milestone = issue.get("milestone") or {}
        existing[issue["title"]] = {
            "number": issue["number"],
            "body": issue.get("body", ""),
            "labels": [
                label["name"] for label in (issue.get("labels") or [])
            ],
            "milestone": milestone.get("title", "") if isinstance(milestone, dict) else "",
            "state": (issue.get("state") or "").upper(),
        }
    print("  Found {} existing issues.".format(len(existing)))
    return existing


def match_by_previous_title(issue, existing_issues):
    """Find an issue filed under an earlier title, and rename it in place.

    Retitling a story is otherwise a two-step: rename on GitHub, then edit the
    ledger to match. Miss the first step and the sync files a duplicate. Listing
    the old title under `previous_titles` makes the retitle one edit here.

    A rename that fails still counts as a match, so a transient error leaves the
    issue under its old title for the next run to retry rather than filing a
    second copy of the story.
    """
    for old_title in issue.get("previous_titles", []):
        match = existing_issues.get(old_title)
        if match is None:
            continue
        renamed = run_gh_write(
            [
                "issue", "edit", str(match["number"]),
                "--repo", "{}/{}".format(GITHUB_OWNER, GITHUB_REPO),
                "--title", issue["title"],
            ],
            "issue rename",
            "RENAME #{}: '{}' -> '{}'".format(
                match["number"], old_title, issue["title"]
            ),
        )
        if renamed is None:
            print(
                "  x Could not rename #{} from '{}' -- keeping the match so the "
                "next run retries.".format(match["number"], old_title),
                file=sys.stderr,
            )
        else:
            print("  ~ Renamed #{}: '{}' -> '{}'".format(
                match["number"], old_title, issue["title"]
            ))
        return match
    return None


def sync_board(json_path, allow_empty_board=False):
    if not os.path.exists(json_path):
        print("File {} not found.".format(json_path))
        sys.exit(1)

    with open(json_path, "r") as f:
        data = json.load(f)

    print("Syncing Orpheus OSS Board...")

    # =========================================================================
    # Sync Labels
    # =========================================================================
    print("\n--- Syncing Labels ---")
    # Read the board's labels first so create-vs-edit is decided from evidence
    # in both modes. An unreadable list falls back to try-create-then-edit,
    # which is what this did before and still reaches the same end state.
    existing_labels = fetch_existing_labels()
    repo_flag = ["--repo", "{}/{}".format(GITHUB_OWNER, GITHUB_REPO)]
    for label in data.get("labels", []):
        name = label["name"]
        color = label["color"]
        desc = label.get("description", "")
        create_args = ["label", "create", name] + repo_flag + [
            "--color", color, "--description", desc]
        edit_args = ["label", "edit", name] + repo_flag + [
            "--color", color, "--description", desc]

        if existing_labels is None:
            res = run_gh_write(create_args, "label create",
                               "LABEL create {}".format(name))
            if not res:
                ACTIONS["label create"] -= 1
                run_gh_write(edit_args, "label edit",
                             "LABEL edit {}".format(name))
        elif name in existing_labels:
            run_gh_write(edit_args, "label edit",
                         "LABEL edit {} (color {})".format(name, color))
        else:
            run_gh_write(create_args, "label create",
                         "LABEL create {} (color {})".format(name, color))

    # =========================================================================
    # Sync Milestones
    # =========================================================================
    print("\n--- Syncing Milestones ---")
    existing_milestones = fetch_existing_milestones()
    for ms in data.get("milestones", []):
        title = ms["title"]
        desc = ms.get("description", "")
        create_args = [
            "api", "repos/{}/{}/milestones".format(GITHUB_OWNER, GITHUB_REPO),
            "-f", "title={}".format(title),
            "-f", "description={}".format(desc),
        ]
        if existing_milestones is not None and title in existing_milestones:
            ACTIONS["milestone exists"] += 1
            print("  = Milestone exists: {}".format(title))
            continue
        res = run_gh_write(create_args, "milestone create",
                           "MILESTONE create {}".format(title))
        if not DRY_RUN and not res:
            # The POST is the existence check when the list could not be read.
            ACTIONS["milestone create"] -= 1
            ACTIONS["milestone exists"] += 1
            print("  ~ Milestone likely exists: {}".format(title))
        elif not DRY_RUN:
            print("  + Created milestone: {}".format(title))

    # =========================================================================
    # PASS 1: Create/Fetch Issues (Idempotent)
    # =========================================================================
    print("\n--- PASS 1: Creating / Fetching Issues (Idempotent) ---")
    existing_issues = fetch_existing_issues()
    ledger_issues = data.get("issues", [])

    if existing_issues is None:
        print(
            "\nAborting: the existing issues could not be read. Creating from an "
            "unknown board would file every story a second time, and a duplicate "
            "has to be cleaned up by hand.",
            file=sys.stderr,
        )
        sys.exit(1)

    if ledger_issues and not existing_issues and not allow_empty_board:
        print(
            "\nAborting: the board reports zero issues while the ledger holds {}. "
            "That is also what the wrong repository or a token without issue "
            "scope looks like. Re-run with --allow-empty-board if the board "
            "really is empty.".format(len(ledger_issues)),
            file=sys.stderr,
        )
        sys.exit(1)

    title_to_id = {}       # "Issue Title" -> issue number
    title_to_body = {}     # "Issue Title" -> original body from JSON
    title_to_labels = {}   # "Issue Title" -> labels currently on the issue
    # "Issue Title" -> the board entry it matched, keyed by the ledger's title
    # rather than the board's. An issue matched through `previous_titles` is
    # filed on the board under a name the push loop no longer knows, so looking
    # it up there again reports a rename as if it were a new issue.
    title_to_before = {}
    created_count = 0
    skipped_count = 0

    # Under --dry-run nothing is created, so there is no number to carry into
    # the dependency block. Predict the next ones GitHub would hand out, and say
    # they are predictions, so `Requires #N` lines read the way they will.
    next_predicted_number = max(
        [entry["number"] for entry in existing_issues.values()] or [0]
    ) + 1

    for issue in ledger_issues:
        title = issue["title"]
        body = issue.get("body", "")
        labels = ",".join(list(issue.get("labels", [])) + [ROADMAP_LABEL])
        milestone = issue.get("milestone", "")

        # Check if the issue already exists, under this title or an earlier one
        match = existing_issues.get(title)
        if match is None:
            match = match_by_previous_title(issue, existing_issues)

        if match is not None:
            issue_num = match["number"]
            title_to_id[title] = issue_num
            title_to_body[title] = body
            title_to_labels[title] = match["labels"]
            title_to_before[title] = match
            skipped_count += 1
            print("  = Exists #{}: {}".format(issue_num, title))
            continue

        # Create new issue
        args = ["issue", "create",
                "--repo", "{}/{}".format(GITHUB_OWNER, GITHUB_REPO),
                "--title", title, "--body", body]
        if labels:
            args.extend(["--label", labels])
        if milestone:
            args.extend(["--milestone", milestone])

        url = run_gh_write(
            args,
            "issue create",
            "CREATE '{}' [{}] milestone={} (would be ~#{})".format(
                title,
                ", ".join(list(issue.get("labels", [])) + [ROADMAP_LABEL]),
                milestone or "(none)",
                next_predicted_number,
            ),
            dry_result="https://github.com/{}/{}/issues/{}".format(
                GITHUB_OWNER, GITHUB_REPO, next_predicted_number
            ),
        )
        if DRY_RUN:
            next_predicted_number += 1
        if url:
            issue_num = parse_issue_number(url)
            if issue_num:
                title_to_id[title] = issue_num
                title_to_body[title] = body
                # Created with exactly the ledger's labels; nothing to reconcile.
                title_to_labels[title] = list(issue.get("labels", []))
                created_count += 1
                if not DRY_RUN:
                    print("  + Created #{}: {}".format(issue_num, title))
            else:
                print("  ! Created but could not parse ID from: {}".format(url))
        else:
            print("  x Failed to create: {}".format(title))

    print("\n  Pass 1 Summary: {} created, {} already existed.".format(
        created_count, skipped_count
    ))

    # =========================================================================
    # PASS 2: Link Dependencies
    # =========================================================================
    print("\n--- PASS 2: Linking Dependencies ---")
    linked_count = 0

    for issue in ledger_issues:
        title = issue["title"]
        deps = issue.get("depends_on", [])

        if not deps:
            continue

        if title not in title_to_id:
            print("  ! Skipping {} -- not found in Pass 1".format(title))
            continue

        issue_num = title_to_id[title]
        original_body = title_to_body[title]

        # Strip any previously appended dependency/sub-issue blocks
        clean_body = _strip_appended_blocks(original_body)

        # Build the dependency block
        dep_lines = []
        for dep_title in deps:
            dep_id = title_to_id.get(dep_title)
            if dep_id:
                dep_lines.append(
                    "- Requires #{}: {}".format(dep_id, dep_title)
                )
            else:
                print(
                    "  ! Dependency not found for '{}' "
                    "(referenced by #{})".format(dep_title, issue_num)
                )

        if not dep_lines:
            continue

        dep_block = "\n".join(dep_lines)
        updated_body = (
            "{}\n\n"
            "---\n"
            "### Architectural Dependencies\n"
            "{}".format(clean_body, dep_block)
        )

        # Store the updated body for the push below
        title_to_body[title] = updated_body

        linked_count += 1
        print("  -> Linked #{}: {} ({} deps)".format(
            issue_num, title, len(dep_lines)
        ))

    print("\n  Pass 2 Summary: {} issues linked.".format(linked_count))

    # =========================================================================
    # PUSH: Write all updated bodies to GitHub
    # =========================================================================
    print("\n--- Pushing Updated Issue Bodies to GitHub ---")
    push_count = 0

    # Every issue is pushed, not just the ones this run rewrote: the ledger is
    # the source of truth for body, milestone, and labels, and an issue that
    # already existed would otherwise keep whatever it was created with.
    for issue in ledger_issues:
        title = issue["title"]
        issue_num = title_to_id.get(title)
        if not issue_num:
            continue

        body = title_to_body.get(title, issue.get("body", ""))

        args = ["issue", "edit", str(issue_num),
                "--repo", "{}/{}".format(GITHUB_OWNER, GITHUB_REPO),
                "--body", body]

        milestone = issue.get("milestone", "")
        if milestone:
            args.extend(["--milestone", milestone])

        # The ledger decides the labels, so anything else on the issue comes
        # off. Add-only left the board accumulating whatever it had ever been
        # given — a bot's `stale`, a label from a retired taxonomy, two C4
        # labels on one issue — until the filters CONTRIBUTING points readers
        # at stopped meaning anything. A label worth keeping belongs in the
        # ledger, where the next sync will not undo it.
        ledger_labels = list(issue.get("labels", [])) + [ROADMAP_LABEL]
        for label in ledger_labels:
            args.extend(["--add-label", label])
        for label in title_to_labels.get(title, []):
            if label not in ledger_labels:
                args.extend(["--remove-label", label])

        # Describe the change in the terms an operator cares about: did the
        # text move, did the milestone move (the epic-to-theme migration lives
        # or dies here), and which labels arrive or leave.
        before = title_to_before.get(title, {})
        added = [
            label for label in ledger_labels
            if label not in title_to_labels.get(title, [])
        ]
        removed = [
            label for label in title_to_labels.get(title, [])
            if label not in ledger_labels
        ]
        changes = []
        if before.get("body", "") != body:
            changes.append("body")
        if milestone and before.get("milestone", "") != milestone:
            changes.append("milestone {} -> {}".format(
                before.get("milestone") or "(none)", milestone
            ))
        if added:
            changes.append("+labels {}".format(", ".join(added)))
        if removed:
            changes.append("-labels {}".format(", ".join(removed)))
        if before.get("state") == "CLOSED":
            changes.append("NOTE: issue is CLOSED (edited, not reopened)")

        res = run_gh_write(
            args,
            "issue edit",
            "EDIT #{} '{}' — {}".format(
                issue_num, title, "; ".join(changes) if changes else "no change"
            ),
        )
        if res is not None:
            push_count += 1
            if not DRY_RUN:
                print("  -> Updated #{}: {}".format(issue_num, title))
        else:
            print("  x Failed to update #{}: {}".format(issue_num, title))

    # =========================================================================
    # PASS 3: Add Issues to Project Board
    # =========================================================================
    print("\n--- PASS 3: Adding Issues to Project Board ---")
    project_num = find_project_number()
    project_add_count = 0

    if project_num:
        repo_full = "{}/{}".format(GITHUB_OWNER, GITHUB_REPO)
        for title, issue_num in title_to_id.items():
            url = "https://github.com/{}/issues/{}".format(repo_full, issue_num)
            res = run_gh_write(
                [
                    "project", "item-add", str(project_num),
                    "--owner", GITHUB_OWNER,
                    "--url", url,
                ],
                "project add",
                "PROJECT add #{} ({})".format(issue_num, title),
            )
            if res is not None:
                project_add_count += 1
                if not DRY_RUN:
                    print("  + Added #{} to project".format(issue_num))
            else:
                # item-add errors if already added — that's fine
                print("  = #{} already in project (or error)".format(issue_num))
    else:
        print("  ! Project '{}' not found. Run setup_orpheus_project.py first.".format(
            PROJECT_NAME
        ))

    print("\n  Pass 3 Summary: {} issues added to project.".format(project_add_count))

    # =========================================================================
    # Summary
    # =========================================================================
    header = "Rehearsal Complete — nothing was changed" if DRY_RUN \
        else "Board Synchronization Complete"
    print("\n=== {} ===".format(header))
    print("   Issues created:  {}".format(created_count))
    print("   Issues existed:  {}".format(skipped_count))
    print("   Dependencies:    {}".format(linked_count))
    print("   Bodies pushed:   {}".format(push_count))
    print("   Project items:   {}".format(project_add_count))

    print("\n   Actions {}:".format("that WOULD run" if DRY_RUN else "performed"))
    for action in sorted(ACTIONS):
        if ACTIONS[action]:
            print("     {:<20} {}".format(action, ACTIONS[action]))

    if DRY_RUN:
        print(
            "\n   This run only read the board. Issue numbers for new issues "
            "are predictions.\n   Closing and reopening issues is not this "
            "script's job — a human does those."
        )


def _strip_appended_blocks(body):
    """Remove previously appended dependency and sub-issue blocks.

    These blocks are appended by the sync script and should be
    regenerated fresh on each run to ensure correctness.
    """
    # Remove "### Architectural Dependencies" block (added by Pass 2)
    body = re.sub(
        r"\n*---\n### Architectural Dependencies\n.*",
        "",
        body,
        flags=re.DOTALL
    )
    # Remove a legacy "### Sub-Issues" block: epics are retired, so any
    # task list an earlier sync appended is stripped on the next push.
    body = re.sub(
        r"\n*---\n### Sub-Issues\n.*",
        "",
        body,
        flags=re.DOTALL
    )
    return body.rstrip()


if __name__ == "__main__":
    # Resolve path relative to the repository root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
    default_path = os.path.join(repo_root, "docs", "backlog.json")

    argv = sys.argv[1:]
    allow_empty_board = "--allow-empty-board" in argv
    DRY_RUN = "--dry-run" in argv
    positional = [arg for arg in argv if not arg.startswith("--")]

    if DRY_RUN:
        print("=== DRY RUN: reading {}/{}, changing nothing ===".format(
            GITHUB_OWNER, GITHUB_REPO
        ))

    path = positional[0] if positional else default_path
    sync_board(path, allow_empty_board=allow_empty_board)
