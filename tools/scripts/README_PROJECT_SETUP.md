# Orpheus GitHub Project Setup Script

## What This Does

This script safely creates or updates a GitHub Project (Projects v2) for the `scottchronicity/orpheus` repository with:

- ✅ Idempotent operation (safe to run multiple times)
- ✅ Dry-run mode to preview changes
- ✅ Basic fields (Status with Backlog/Todo/In Progress/Done)
- ✅ Uses official GitHub GraphQL API via `gh` CLI

## Prerequisites

### 1. Install GitHub CLI

**macOS:**

```bash
brew install gh
```

**Linux:**

```bash
# Debian/Ubuntu
sudo apt install gh

# Fedora/RHEL
sudo dnf install gh
```

**Windows:**

```bash
winget install --id GitHub.cli
```

Or download from: <https://cli.github.com/>

### 2. Authenticate with GitHub

```bash
gh auth login
```

Follow the prompts to authenticate.

### 3. Add Required Token Scope

The script needs the `project` scope to create/modify projects:

```bash
gh auth refresh -s project
```

This adds the `project` scope to your existing token. You'll be prompted to authorize the additional permission in your browser.

### 4. Verify Authentication

```bash
gh auth status
```

You should see:

- ✓ Logged in to github.com
- ✓ Token scopes include `project` (or at least `read:project`)

## Usage

### Step 1: Dry Run (Recommended First)

**Always run with `--dry-run` first** to see what the script will do:

```bash
python3 setup_orpheus_project.py --dry-run
```

Expected output:

```bash
✅ GitHub CLI authenticated
🔍 Looking up owner: scottchronicity
[DRY RUN] Would execute: gh api graphql -f query=...
[DRY RUN] Would retrieve owner ID
🔍 Checking for existing project named 'Orpheus'
[DRY RUN] Would search for project 'Orpheus'
📝 Creating new project: Orpheus
[DRY RUN] Would create project 'Orpheus'
📝 Adding Status field with options: Backlog, Todo, In Progress, Done
[DRY RUN] Would add Status field

✨ Project setup complete!
   Project: Orpheus
   Number: #999

💡 This was a dry run. Run without --dry-run to actually create the project.
```

### Step 2: Run for Real

If the dry run looks good:

```bash
python3 setup_orpheus_project.py
```

Expected output:

```bash
✅ GitHub CLI authenticated
🔍 Looking up owner: scottchronicity
✅ Found owner ID: MDQ6VXNlcjEyMzQ1Njc4
🔍 Checking for existing project named 'Orpheus'
ℹ️  No existing project named 'Orpheus' found
📝 Creating new project: Orpheus
✅ Created project: Orpheus (#1)
📝 Adding Status field with options: Backlog, Todo, In Progress, Done
✅ Added Status field: Status

✨ Project setup complete!
   Project: Orpheus
   Number: #1
   URL: https://github.com/users/scottchronicity/projects/1
```

### Step 3: Run Again (Idempotency Test)

Running it again is safe - it will reuse the existing project:

```bash
python3 setup_orpheus_project.py
```

Expected output:

```bash
✅ GitHub CLI authenticated
🔍 Looking up owner: scottchronicity
✅ Found owner ID: MDQ6VXNlcjEyMzQ1Njc4
🔍 Checking for existing project named 'Orpheus'
✅ Found existing project: Orpheus (#1)
♻️  Reusing existing project: Orpheus
ℹ️  Status field may already exist (this is okay)

✨ Project setup complete!
   Project: Orpheus
   Number: #1
   URL: https://github.com/users/scottchronicity/projects/1
```

## Options

```bash
# Use a different owner (if not scottchronicity)
python3 setup_orpheus_project.py --owner myusername

# Different project name
python3 setup_orpheus_project.py --project-name "My Wildlife Station"

# Combine options
python3 setup_orpheus_project.py --owner myusername --dry-run
```

## Environment Variables

You can set these instead of using flags:

```bash
export GITHUB_OWNER=scottchronicity
python3 setup_orpheus_project.py
```

## Troubleshooting

### Error: "GitHub CLI is not authenticated"

**Fix:**

```bash
gh auth login
```

### Error: "token has not been granted the required scopes"

**Fix:**

```bash
gh auth refresh -s project
```

### Error: "Failed to get owner ID"

**Possible causes:**

- Owner name is incorrect
- Owner doesn't exist
- Network issues

**Fix:**

```bash
# Verify owner exists
gh api users/scottchronicity

# Check your authentication
gh auth status
```

### Error: "Field might already exist"

**This is not an error!** The script gracefully handles existing fields. You'll see:

```bash
ℹ️  Status field may already exist (this is okay)
```

## What Gets Created

### Project Structure

```bash
Orpheus Project (#1)
├── Fields:
│   ├── Status (Single Select)
│   │   ├── Backlog (Gray)
│   │   ├── Todo (Yellow)
│   │   ├── In Progress (Blue)
│   │   └── Done (Green)
│   ├── Title (default)
│   ├── Assignees (default)
│   └── Labels (default)
└── Views:
    └── Table (default)
```

### Adding Items Later

Once the project exists, you can:

1. **Via Web UI**: <https://github.com/users/scottchronicity/projects/1>
2. **Via CLI**:

   ```bash
   # Add an issue to the project
   gh project item-add 1 --owner scottchronicity --url https://github.com/scottchronicity/orpheus/issues/5
   ```

3. **Via API** (in your repo automation):

   ```python
   # This script can be extended to add items programmatically
   ```

## Safety Features

✅ **Idempotent** - Safe to run multiple times  
✅ **Dry-run mode** - Preview before making changes  
✅ **Uses official API** - No hacky workarounds  
✅ **Least-privilege scope** - Only requests `project` permission  
✅ **Error handling** - Gracefully handles existing resources  
✅ **Clear output** - Shows exactly what it's doing  

## Security Notes

- The script uses `gh` CLI, which securely stores your token
- No token is passed as a command-line argument (secure)
- Token is stored in `~/.config/gh/hosts.yml` (protected by OS permissions)
- The `project` scope only allows managing projects, not repository code
- You can revoke the token anytime at: <https://github.com/settings/tokens>

## Next Steps

After creating the project:

1. **Link it to your repo**:
   - Go to: <https://github.com/scottchronicity/orpheus>
   - Click "Projects" tab
   - Link the Orpheus project

2. **Add automation** (optional):
   - Auto-add new issues to project
   - Auto-set status based on labels
   - GitHub Actions workflows

3. **Customize fields** (via web UI):
   - Add Priority field
   - Add Iteration/Sprint field  
   - Add custom fields for your workflow

## Documentation References

- GitHub Projects v2 API: <https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-api-to-manage-projects>
- GitHub CLI: <https://cli.github.com/>
- GraphQL API: <https://docs.github.com/en/graphql>

## Support

If you encounter issues:

1. Run with `--dry-run` first
2. Check `gh auth status`
3. Verify token has `project` scope
4. Check the script output for specific error messages

The script is designed to fail safely - it won't make changes if something is wrong.
