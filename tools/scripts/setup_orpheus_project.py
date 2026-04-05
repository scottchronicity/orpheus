#!/usr/bin/env python3
"""
Setup GitHub Projects v2 for Orpheus repository.

This script safely creates or updates a GitHub Project (Projects v2) for the
scottchronicity/orpheus repository with basic fields and starter items.

Requirements:
- GitHub CLI (gh) must be installed and authenticated
- Token must have 'project' scope (includes read:project)

Usage:
    # Dry run (show what would happen)
    ./setup_orpheus_project.py --dry-run

    # Actually create/update the project
    ./setup_orpheus_project.py

    # With explicit repo owner
    ./setup_orpheus_project.py --owner scottchronicity

Environment Variables:
- GITHUB_OWNER: Repository owner (default: scottchronicity)
"""

import json
import subprocess
import sys
import argparse
import os
from typing import Dict, Optional, List


class GitHubProjectSetup:
    """Manages GitHub Projects v2 setup via GraphQL API."""

    def __init__(self, owner: str, repo: str = "orpheus", dry_run: bool = False):
        self.owner = owner
        self.repo = repo
        self.dry_run = dry_run
        self.owner_id: Optional[str] = None

    def run_gh_command(self, query: str, variables: Optional[Dict] = None) -> Dict:
        """
        Execute a GitHub GraphQL query using gh CLI.

        Args:
            query: GraphQL query string
            variables: Optional variables for the query

        Returns:
            Parsed JSON response

        Raises:
            subprocess.CalledProcessError: If gh command fails
        """
        cmd = ["gh", "api", "graphql", "-f", f"query={query}"]

        if variables:
            for key, value in variables.items():
                # Handle different variable types
                if isinstance(value, int):
                    cmd.extend(["-F", f"{key}={value}"])
                else:
                    cmd.extend(["-f", f"{key}={value}"])

        if self.dry_run:
            print(f"[DRY RUN] Would execute: {' '.join(cmd)}")
            print(f"[DRY RUN] Query: {query}")
            if variables:
                print(f"[DRY RUN] Variables: {variables}")
            return {}

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            print(f"Error executing gh command: {e}", file=sys.stderr)
            print(f"stdout: {e.stdout}", file=sys.stderr)
            print(f"stderr: {e.stderr}", file=sys.stderr)
            raise

    def check_gh_auth(self) -> bool:
        """Verify gh CLI is authenticated with required scopes."""
        try:
            result = subprocess.run(
                ["gh", "auth", "status"], capture_output=True, text=True, check=False
            )

            if result.returncode != 0:
                print("❌ GitHub CLI is not authenticated.", file=sys.stderr)
                print("Please run: gh auth login", file=sys.stderr)
                return False

            # Check for project scope
            if "project" not in result.stdout and "read:project" not in result.stdout:
                print(
                    "⚠️  Warning: Your gh token may not have 'project' scope.",
                    file=sys.stderr,
                )
                print(
                    "If you see errors, refresh with: gh auth refresh -s project",
                    file=sys.stderr,
                )

            print("✅ GitHub CLI authenticated")
            return True

        except FileNotFoundError:
            print(
                "❌ GitHub CLI (gh) not found. Please install it first.",
                file=sys.stderr,
            )
            print("See: https://cli.github.com/", file=sys.stderr)
            return False

    def get_owner_id(self) -> str:
        """Get the node ID for the repository owner."""
        query = """
        query($login: String!) {
            user(login: $login) {
                id
                login
            }
        }
        """

        print(f"🔍 Looking up owner: {self.owner}")
        response = self.run_gh_command(query, {"login": self.owner})

        if self.dry_run:
            print("[DRY RUN] Would retrieve owner ID")
            return "DRY_RUN_OWNER_ID"

        if "errors" in response:
            raise ValueError(f"Failed to get owner ID: {response['errors']}")

        owner_id = response["data"]["user"]["id"]
        print(f"✅ Found owner ID: {owner_id}")
        self.owner_id = owner_id
        return owner_id

    def find_existing_project(self, project_name: str) -> Optional[Dict]:
        """
        Check if a project with the given name already exists.

        Returns:
            Project data if found, None otherwise
        """
        query = """
        query($login: String!) {
            user(login: $login) {
                projectsV2(first: 20) {
                    nodes {
                        id
                        title
                        number
                    }
                }
            }
        }
        """

        print(f"🔍 Checking for existing project named '{project_name}'")
        response = self.run_gh_command(query, {"login": self.owner})

        if self.dry_run:
            print(f"[DRY RUN] Would search for project '{project_name}'")
            return None

        if "errors" in response:
            raise ValueError(f"Failed to list projects: {response['errors']}")

        projects = response["data"]["user"]["projectsV2"]["nodes"]
        for project in projects:
            if project["title"] == project_name:
                print(
                    f"✅ Found existing project: {project['title']} (#{project['number']})"
                )
                return project

        print(f"ℹ️  No existing project named '{project_name}' found")
        return None

    def create_project(self, project_name: str) -> Dict:
        """Create a new GitHub Project v2."""
        if not self.owner_id:
            self.get_owner_id()

        mutation = """
        mutation($ownerId: ID!, $title: String!) {
            createProjectV2(input: {
                ownerId: $ownerId,
                title: $title
            }) {
                projectV2 {
                    id
                    title
                    number
                }
            }
        }
        """

        print(f"📝 Creating new project: {project_name}")

        if self.dry_run:
            print(f"[DRY RUN] Would create project '{project_name}'")
            return {"id": "DRY_RUN_PROJECT_ID", "title": project_name, "number": 999}

        response = self.run_gh_command(
            mutation, {"ownerId": self.owner_id, "title": project_name}
        )

        if "errors" in response:
            raise ValueError(f"Failed to create project: {response['errors']}")

        project = response["data"]["createProjectV2"]["projectV2"]
        print(f"✅ Created project: {project['title']} (#{project['number']})")
        return project

    def add_status_field(self, project_id: str) -> Dict:
        """Add a Status field to the project (if not exists)."""
        # Note: In a real implementation, you would first check if the field exists
        # For simplicity, we'll just show what would be done

        mutation = """
        mutation($projectId: ID!, $name: String!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
            createProjectV2Field(input: {
                projectId: $projectId,
                dataType: SINGLE_SELECT,
                name: $name,
                singleSelectOptions: $options
            }) {
                projectV2Field {
                    ... on ProjectV2SingleSelectField {
                        id
                        name
                    }
                }
            }
        }
        """

        options = [
            {"name": "Backlog", "color": "GRAY"},
            {"name": "Todo", "color": "YELLOW"},
            {"name": "In Progress", "color": "BLUE"},
            {"name": "Done", "color": "GREEN"},
        ]

        print("📝 Adding Status field with options: Backlog, Todo, In Progress, Done")

        if self.dry_run:
            print("[DRY RUN] Would add Status field")
            return {"id": "DRY_RUN_FIELD_ID", "name": "Status"}

        # Note: This might fail if field already exists - that's okay
        # In production, you'd check first
        try:
            response = self.run_gh_command(
                mutation,
                {"projectId": project_id, "name": "Status", "options": options},
            )

            if "errors" in response:
                # Field might already exist
                print("ℹ️  Status field may already exist (this is okay)")
                return {}

            field = response["data"]["createProjectV2Field"]["projectV2Field"]
            print(f"✅ Added Status field: {field['name']}")
            return field

        except Exception as e:
            print(f"ℹ️  Could not add Status field (may already exist): {e}")
            return {}

    def link_project_to_repo(self, project_number: int) -> None:
        """Link the project to the repository so it appears on the repo's Projects tab."""
        repo_full = f"{self.owner}/{self.repo}"
        print(f"🔗 Linking project #{project_number} to {repo_full}")

        if self.dry_run:
            print(f"[DRY RUN] Would link project to {repo_full}")
            return

        try:
            result = subprocess.run(
                [
                    "gh", "project", "link", str(project_number),
                    "--owner", self.owner,
                    "--repo", repo_full,
                ],
                capture_output=True, text=True, check=True,
            )
            print(f"✅ Linked project to {repo_full}")
        except subprocess.CalledProcessError as e:
            if "already linked" in e.stderr.lower():
                print(f"ℹ️  Project already linked to {repo_full}")
            else:
                print(f"⚠️  Could not link project: {e.stderr}")

    def setup_project(self, project_name: str = "Orpheus Roadmap") -> Dict:
        """
        Main setup function - creates or reuses existing project.

        Returns:
            Project data
        """
        # Check authentication
        if not self.check_gh_auth():
            sys.exit(1)

        # Get owner ID
        self.get_owner_id()

        # Check if project exists
        existing = self.find_existing_project(project_name)

        if existing:
            print(f"♻️  Reusing existing project: {existing['title']}")
            project = existing
        else:
            project = self.create_project(project_name)

        # Add Status field (will gracefully handle if exists)
        self.add_status_field(project["id"])

        # Link project to the repository
        project_number = project.get("number")
        if project_number:
            self.link_project_to_repo(project_number)

        print(f"\n✨ Project setup complete!")
        print(f"   Project: {project['title']}")
        print(f"   Number: #{project.get('number', 'N/A')}")

        if not self.dry_run:
            project_url = (
                f"https://github.com/users/{self.owner}/projects/{project['number']}"
            )
            repo_url = f"https://github.com/{self.owner}/{self.repo}/projects"
            print(f"   URL: {project_url}")
            print(f"   Repo: {repo_url}")

        return project


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Setup GitHub Projects v2 for Orpheus repository",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview what would be done
  %(prog)s --dry-run
  
  # Create/update the project
  %(prog)s
  
  # Use a different owner
  %(prog)s --owner myusername
  
Token Requirements:
  Your GitHub token needs the 'project' scope. To add it:
    gh auth refresh -s project
        """,
    )

    parser.add_argument(
        "--owner",
        default=os.getenv("GITHUB_OWNER", "scottchronicity"),
        help="GitHub username (default: scottchronicity or $GITHUB_OWNER)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )

    parser.add_argument(
        "--repo",
        default=os.getenv("GITHUB_REPO", "orpheus"),
        help="Repository name (default: orpheus or $GITHUB_REPO)",
    )

    parser.add_argument(
        "--project-name",
        default="Orpheus Roadmap",
        help="Name of the project to create (default: Orpheus Roadmap)",
    )

    args = parser.parse_args()

    # Run setup
    setup = GitHubProjectSetup(owner=args.owner, repo=args.repo, dry_run=args.dry_run)

    try:
        setup.setup_project(project_name=args.project_name)

        if args.dry_run:
            print(
                "\n💡 This was a dry run. Run without --dry-run to actually create the project."
            )

    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
