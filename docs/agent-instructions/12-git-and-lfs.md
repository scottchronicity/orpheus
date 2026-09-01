# 12 — Git, LFS, commit conventions

## TL;DR

- Branch = feature; PR = single PR per branch with many commits.
- **Never `git push` without explicit user permission.** Commit
  locally as much as you want; ask before pushing.
- LFS for any file >1MB. Configured via `.gitattributes`.
- Stage in batches (`git add -A && git commit`), not file-by-file.
  Run `git status` ONCE to sanity-check before adding.
- Don't force-push to `main` — or to ANY branch that exists on the
  remote. Add commits on top of the remote branch, never rewrite it.
  `git fetch` and check the remote branch state BEFORE starting dev.
- Don't `--no-verify`. Don't `git reset --hard` without confirming
  with the user.

## Commit messages

Follow the pattern visible in `git log --oneline`:

- `feat(<scope>): <imperative summary>` for new features
- `fix(<scope>): <imperative summary>` for bug fixes
- `docs(<scope>): <imperative summary>` for doc-only changes
- `test(<scope>): ...` for test-only changes
- `ci(<scope>): ...` for CI config changes
- `refactor(<scope>): ...` for code-cleanup-only changes

Body explains WHY (constraint, prior incident, design decision) — not
WHAT (the diff already shows that).

Commits in this repo carry no AI-attribution trailer. If your tooling appends a
`Co-Authored-By:` line naming a model, strip it before committing.

## LFS

The `.gitattributes` already tracks these patterns via LFS:

- `*.pth`, `*.onnx`, `*.tflite`, `*.h5`, `*.weights`, `*.pb` — note `*.pt` is
  **not** in `.gitattributes`; a `.pt` outside `artifacts/models/` commits raw
  — ML model weights
- `*.wav`, `*.flac`, `*.aiff`, `*.ogg` — audio samples (under
  `artifacts/audio-samples/`)
- `*.mp4`, `*.avi`, `*.mov` — video samples
- `*.zip`, `*.tar.gz` — datasets
- `artifacts/models`, `artifacts/models/*` — by-path tracking. Not `/**`: gitattributes globs do not match nested subdirectories

If you add a new large file:
1. Verify the path/extension is in `.gitattributes` (`git check-attr
   filter <file>`).
2. If not, add a pattern to `.gitattributes` BEFORE staging the file.
3. Commit the file normally; Git LFS handles the rest.
4. `git push` will upload the LFS object. Watch for the
   `Uploading LFS objects: ... done` line.

On Jetson / fresh clone: `git lfs pull` to fetch all LFS objects.

## Stage in batches, not file-by-file

The pattern that wastes the least tokens AND catches the most bugs:

```bash
# 1. Make your changes. Build, lint, test as you go.

# 2. ONE git status — verify the directory is in the state you want.
#    Is anything weird showing up? Stray editor files? .DS_Store?
#    Investigate before assuming it's fine. The .gitignore Python
#    `lib/` rule has silently dropped new frontend src/lib/*.ts
#    files in the past — git add -A WILL skip them and you won't
#    notice without looking.
git status

# 3. Batch add + commit.
git add -A
git commit -m "..."
```

Do NOT `git add path1 && git commit -m "..." && git add path2 && git
commit -m "..." && ...` across 10 rounds. Past agents have done this
and burnt the user's tokens for no reason. ONE coherent commit per
unit of work; the diff itself tells the story.

If a `git add -A` does drop a file silently, `git check-ignore -v <file>`
tells you which rule caught it.

## Never push without permission

Every push triggers CI which costs the user real money. Past sessions
have pushed at the wrong moment (after every commit, or at a self-
declared "natural shipping point" that was 1/20th of where the user
actually wanted to ship). Don't guess.

**The pattern:**
- Commit locally as you work, freely.
- When you reach what FEELS like a stopping point, ask: "Want me to
  push these N commits?" or similar. Don't just push.
- The user will say "push it," "open the PR," or "yes" → then push.
- If the user says "keep going" or doesn't reply, keep committing
  locally.

If you've been working a while and have a stack of local commits,
that's fine. The user can see them with `git log` whenever they
want; they're not lost.

## Check the remote before starting dev

Before you begin work on any branch that exists on the remote, sync
your view of it:

```bash
git fetch origin
git log --oneline <branch>..origin/<branch>   # commits on the remote you don't have?
```

If the remote branch has commits you don't have, start FROM them
(`git pull --ff-only`, or branch off `origin/<branch>`). The owner may
have advanced the branch between sessions — local work must never
silently diverge from the remote. A past session skipped this check,
developed on a stale local copy, and overwrote the owner's commits on
the remote: "absolutely dont overwrite the remote branch. you should
be adding ON TOP OF IT. you should have checked before you started
dev."

## Branch + PR conventions

One branch = one PR. Many commits per PR is fine and encouraged. Each
commit should be coherent (the diff matches the message).

The PR's branch name describes the work. PR numbers are just the next
available number in the repo — don't read meaning into the number.

When a PR is open and you push new commits to the branch, CI re-runs
automatically. Don't open a second PR for the same branch.

## When CI is failing because of a small problem

Don't push a series of "try fix" commits to see if CI passes. Each
push runs the entire CI matrix. Costs the user real money. Instead:

1. Reproduce the failure locally (`make lint-<x>` / `make test-<x>`).
2. Fix it.
3. Verify locally.
4. Push ONCE with the fix.

If you can't reproduce locally, that itself is a problem — local and
CI must match. Investigate the discrepancy before pushing again.

## Destructive operations

Never without explicit user confirmation:

- `git push --force` to `main` or to ANY branch that exists on the
  remote (feature/working branches included)
- `git reset --hard` (always offer the safe alternative)
- `git checkout -- <file>` (discards uncommitted work)
- `git branch -D <branch>`
- `git clean -fd`
- `rm -rf` on anything under git control

Once a branch exists on the remote — even "your own" feature branch —
treat its history as shared: add commits ON TOP of it, never rewrite
it. The owner may have advanced the branch since you last looked (see
"Check the remote before starting dev" above). Rebase-then-force-push
is reserved for branches that have never been pushed; after the first
push, history is append-only.

## See also

- [`13-ci-cd.md`](13-ci-cd.md) for what CI actually runs.
- [`99-gotchas.md`](99-gotchas.md) for the `.gitignore` lib/ pattern
  and other landmines.
