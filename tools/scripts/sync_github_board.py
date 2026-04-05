import json
import subprocess
import sys
import os
import re

# Repository owner (used for project commands)
GITHUB_OWNER = os.getenv("GITHUB_OWNER", "scottchronicity")
GITHUB_REPO = os.getenv("GITHUB_REPO", "orpheus")
PROJECT_NAME = "Orpheus Roadmap"


def run_gh_command(args):
    """Executes a GitHub CLI command and returns the output."""
    try:
        result = subprocess.run(
            ["gh"] + args, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print("Error running command {}: {}".format(" ".join(args), e.stderr))
        return None


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
    """Fetch all open issues and return a dict of title -> (number, body)."""
    print("  Fetching existing issues...")
    existing = {}
    # Fetch up to 500 issues (paginated by gh)
    result = run_gh_command([
        "issue", "list",
        "--state", "all",
        "--limit", "500",
        "--json", "number,title,body"
    ])
    if result:
        try:
            issues = json.loads(result)
            for issue in issues:
                existing[issue["title"]] = {
                    "number": issue["number"],
                    "body": issue.get("body", "")
                }
            print("  Found {} existing issues.".format(len(existing)))
        except json.JSONDecodeError:
            print("  Warning: could not parse existing issues JSON.")
    return existing


def sync_board(json_path):
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
    for label in data.get("labels", []):
        name = label["name"]
        color = label["color"]
        desc = label.get("description", "")
        res = run_gh_command(
            ["label", "create", name, "--color", color, "--description", desc]
        )
        if not res:
            run_gh_command(
                ["label", "edit", name, "--color", color, "--description", desc]
            )
            print("  ~ Updated label: {}".format(name))
        else:
            print("  + Created label: {}".format(name))

    # =========================================================================
    # Sync Milestones
    # =========================================================================
    print("\n--- Syncing Milestones ---")
    for ms in data.get("milestones", []):
        title = ms["title"]
        desc = ms.get("description", "")
        res = run_gh_command([
            "api", "repos/{owner}/{repo}/milestones",
            "-f", "title={}".format(title),
            "-f", "description={}".format(desc),
        ])
        if res:
            print("  + Created milestone: {}".format(title))
        else:
            print("  ~ Milestone likely exists: {}".format(title))

    # =========================================================================
    # PASS 1: Create/Fetch Issues (Idempotent)
    # =========================================================================
    print("\n--- PASS 1: Creating / Fetching Issues (Idempotent) ---")
    existing_issues = fetch_existing_issues()

    title_to_id = {}       # "Issue Title" -> issue number
    title_to_body = {}     # "Issue Title" -> original body from JSON
    created_count = 0
    skipped_count = 0

    for issue in data.get("issues", []):
        title = issue["title"]
        body = issue.get("body", "")
        labels = ",".join(issue.get("labels", []))
        milestone = issue.get("milestone", "")

        # Check if issue already exists
        if title in existing_issues:
            issue_num = existing_issues[title]["number"]
            title_to_id[title] = issue_num
            title_to_body[title] = body
            skipped_count += 1
            print("  = Exists #{}: {}".format(issue_num, title))
            continue

        # Create new issue
        args = ["issue", "create", "--title", title, "--body", body]
        if labels:
            args.extend(["--label", labels])
        if milestone:
            args.extend(["--milestone", milestone])

        url = run_gh_command(args)
        if url:
            issue_num = parse_issue_number(url)
            if issue_num:
                title_to_id[title] = issue_num
                title_to_body[title] = body
                created_count += 1
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

    for issue in data.get("issues", []):
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

        # Store the updated body for Pass 3 to build upon
        title_to_body[title] = updated_body

        linked_count += 1
        print("  -> Linked #{}: {} ({} deps)".format(
            issue_num, title, len(dep_lines)
        ))

    print("\n  Pass 2 Summary: {} issues linked.".format(linked_count))

    # =========================================================================
    # PASS 3: Sub-issue Hierarchy (Epic Task Lists)
    # =========================================================================
    print("\n--- PASS 3: Building Epic Sub-issue Hierarchy ---")
    epic_count = 0

    # Build a map of epic title -> list of child issue numbers
    epic_children = {}  # "Epic Title" -> [(issue_num, issue_title), ...]

    for issue in data.get("issues", []):
        parent = issue.get("parent_epic")
        if not parent:
            continue

        child_title = issue["title"]
        if child_title not in title_to_id:
            continue

        child_num = title_to_id[child_title]

        if parent not in epic_children:
            epic_children[parent] = []
        epic_children[parent].append((child_num, child_title))

    # Now update each epic tracking issue with its sub-issue task list
    for issue in data.get("issues", []):
        if not issue.get("is_epic"):
            continue

        epic_title = issue["title"]
        if epic_title not in title_to_id:
            print("  ! Epic not found: {}".format(epic_title))
            continue

        epic_num = title_to_id[epic_title]
        children = epic_children.get(epic_title, [])

        if not children:
            print("  - Epic #{} has no children: {}".format(
                epic_num, epic_title
            ))
            continue

        # Build task list (GitHub natively parses this into Sub-issues UI)
        task_lines = []
        for child_num, child_title in children:
            task_lines.append("- [ ] #{}".format(child_num))

        task_block = "\n".join(task_lines)

        # Get the current body (may have been updated in Pass 2, but epics
        # typically don't have dependencies)
        epic_body = title_to_body.get(epic_title, issue.get("body", ""))

        # Strip any previous sub-issue block
        clean_body = _strip_appended_blocks(epic_body)

        # Replace the placeholder or append
        if "_Populated automatically by sync script._" in clean_body:
            updated_body = clean_body.replace(
                "_Populated automatically by sync script._",
                task_block
            )
        else:
            updated_body = (
                "{}\n\n"
                "---\n"
                "### Sub-Issues\n"
                "{}".format(clean_body, task_block)
            )

        title_to_body[epic_title] = updated_body
        epic_count += 1
        print("  -> Epic #{}: {} ({} sub-issues)".format(
            epic_num, epic_title, len(children)
        ))

    # =========================================================================
    # PUSH: Write all updated bodies to GitHub
    # =========================================================================
    print("\n--- Pushing Updated Issue Bodies to GitHub ---")
    push_count = 0

    for title, body in title_to_body.items():
        issue_num = title_to_id.get(title)
        if not issue_num:
            continue

        # Check if body has actually been modified (has dependency or
        # sub-issue blocks)
        original_issue = next(
            (i for i in data.get("issues", []) if i["title"] == title),
            None
        )
        if not original_issue:
            continue

        original_body = original_issue.get("body", "")

        # Only push if the body differs from the original JSON body
        if body == original_body:
            continue

        res = run_gh_command(
            ["issue", "edit", str(issue_num), "--body", body]
        )
        if res is not None:
            push_count += 1
            print("  -> Updated #{}: {}".format(issue_num, title))
        else:
            print("  x Failed to update #{}: {}".format(issue_num, title))

    # =========================================================================
    # PASS 4: Add Issues to Project Board
    # =========================================================================
    print("\n--- PASS 4: Adding Issues to Project Board ---")
    project_num = find_project_number()
    project_add_count = 0

    if project_num:
        repo_full = "{}/{}".format(GITHUB_OWNER, GITHUB_REPO)
        for title, issue_num in title_to_id.items():
            url = "https://github.com/{}/issues/{}".format(repo_full, issue_num)
            res = run_gh_command([
                "project", "item-add", str(project_num),
                "--owner", GITHUB_OWNER,
                "--url", url,
            ])
            if res is not None:
                project_add_count += 1
                print("  + Added #{} to project".format(issue_num))
            else:
                # item-add errors if already added — that's fine
                print("  = #{} already in project (or error)".format(issue_num))
    else:
        print("  ! Project '{}' not found. Run setup_orpheus_project.py first.".format(
            PROJECT_NAME
        ))

    print("\n  Pass 4 Summary: {} issues added to project.".format(project_add_count))

    # =========================================================================
    # Summary
    # =========================================================================
    print("\n=== Board Synchronization Complete ===")
    print("   Issues created:  {}".format(created_count))
    print("   Issues existed:  {}".format(skipped_count))
    print("   Dependencies:    {}".format(linked_count))
    print("   Epics updated:   {}".format(epic_count))
    print("   Bodies pushed:   {}".format(push_count))
    print("   Project items:   {}".format(project_add_count))


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
    # Remove "### Sub-Issues" block (added by Pass 3)
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

    path = sys.argv[1] if len(sys.argv) > 1 else default_path
    sync_board(path)
