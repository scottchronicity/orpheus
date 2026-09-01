# 99 — Known landmines

Specific bugs and weird-library-behavior patterns that have bitten
agents (or humans) in this repo. Read this BEFORE adding workarounds
for unexpected behavior — the answer may already be here.

## panns_inference hardcodes `~/panns_data/class_labels_indices.csv`

The `panns_inference` PyPI package reads its labels CSV at MODULE-IMPORT
TIME from `Path.home() / 'panns_data' / 'class_labels_indices.csv'`,
with no override hook. If the file's missing, it `wget`s from a Google
storage URL we don't control. This is a problem for systemd
deployments (HOME varies by user) and for any environment with no
network access at startup.

**The fix in this repo:**
`agents/orpheus-agent-audio-events/src/orpheus_agent_audio_events/model.py`
has `_stage_panns_labels_and_pin_home()` which:
1. Copies the bundled 527-class CSV (from the agent's `data/`
   directory) to `$ORPHEUS_DATA_ROOT/panns_data/`.
2. Temporarily sets `os.environ["HOME"] = $ORPHEUS_DATA_ROOT` BEFORE
   importing `panns_inference`.
3. Restores HOME in a `finally` block.

If you're adding ML deps that read from `~/...`, consider whether the
same staging pattern applies.

## `.gitignore` `lib/` rule eats frontend files

`.gitignore` has a `lib/` rule for Python build artifacts. Without the
negation rules directly under it, this silently catches
`services/orpheus_ui/frontend/src/lib/*.ts` for new files. `git add`
fails with "paths ignored by gitignore"; `git status` shows them in
the "Untracked files (use git status -u)" section that's hidden by
default.

**The fix in this repo (already applied):**

```
lib/
!services/orpheus_ui/frontend/src/lib/
!services/orpheus_ui/frontend/src/lib/**
```

Always `git status` after committing. If anything's untracked, ask why
before pushing.

## AudioSet machine_ids: NEVER guess

The historical curated CSV at
`agents/orpheus-agent-audio-events/src/orpheus_agent_audio_events/data/audioset_class_labels_indices.csv`
had 40/45 wrong indices because someone built it from a different
AudioSet revision than PANNs uses. Effect: `post_process()`'s
`allowed_class_indices` filter dropped EVERY corvid detection silently.

Similar bug in `BIRD_LIKE_AUDIOSET_MIDS` (Bird Correlation dashboard
config in `services/orpheus_ui/backend/src/orpheus_ui/api/diagnostics.py`)
— "Caw" was at the Coo mid, "Owl" was at the Bird-flight mid, one mid
didn't exist at all.

**The rule:** if you need an AudioSet mid, look it up in
`agents/orpheus-agent-audio-events/src/orpheus_agent_audio_events/data/panns_class_labels_indices.csv`.
This is the canonical 527-class CSV that ships with the model. Never
copy mids from comments, README files, or PANNs documentation —
they've been wrong before.

## PANNs frame duration: 0.010s, NOT 0.032s

The model's framewise output is at 100 Hz (hop_size=320 @ 32000 Hz).
A previous comment said "~32 ms" which was for a different PANNs
variant. The wrong constant made `post_process()`'s time bounds off
by 3.2x.

If you find a model parameter you can't trace to a measurement,
measure it. Don't trust comments.

## OrpheusConfig singleton must be reset between tests

`OrpheusConfig.get_instance()` caches. Tests that read config will see
the previously-loaded config unless they reset it.

**The fix:** every per-component `tests/conftest.py` for code that
calls `OrpheusConfig.get_instance()` has an autouse fixture that
clears the singleton before each test. Copy this pattern when
creating a new test suite:

```python
@pytest.fixture(autouse=True)
def reset_orpheus_config_singleton() -> None:
    original_instance = OrpheusConfig._instance
    original_dotenv = OrpheusConfig._DOTENV_LOADED
    OrpheusConfig._instance = None
    OrpheusConfig._DOTENV_LOADED = False
    yield
    OrpheusConfig._instance = original_instance
    OrpheusConfig._DOTENV_LOADED = original_dotenv
```

## Local lint != CI lint unless invoked via `make lint-<X>`

Each component's `pyproject.toml` enables strict rule sets (`S`, `PT`,
`N`, `PTH`, `RUF`, etc). Running `venv/bin/ruff check src/ tests/`
from outside the component directory does NOT pick up those rules.
`make lint-<component>` (which `cd`s in and uses the agent's config)
does.

**Symptom:** local "ruff clean", CI "21 ruff errors."
**Fix:** Always `make lint-<component>` before pushing.
See [`10-tooling.md`](10-tooling.md).

## Ruff strict rule pitfalls

When you write tests:

| Rule | What triggers it | Fix |
|---|---|---|
| `S108` | Hardcoded `/tmp/...` paths in test data | Use `tmp_path` fixture |
| `PT018` | `assert a and b` (combined) | Split into two asserts |
| `PT006` | `@parametrize("a,b", ...)` (comma-separated) | Use tuple syntax: `("a", "b")` |
| `PLC0415` | Imports inside functions | Add `# noqa: PLC0415` if the lazy import is needed (e.g., to skip-if-missing); otherwise move to module top |
| `PTH123` | `open(path)` | Use `path.open()` if `path` is `Path`, else `Path(path).open()` |
| `N806` | UpperCase variable in function | Lowercase it |
| `ARG001` / `ARG002` | Unused fn / method arg | Either remove or `# noqa: ARG002 — fixture forces X` |
| `RUF003` | Unicode `×` in comment | Use ASCII `x` |
| `I001` | Imports unsorted | `make format-<component>` will auto-fix |

## SQLite ALTER TABLE on non-existent table

When `ensure_schema_updates()` runs on a partially-initialised DB
(some tests init only some tables), an `ALTER TABLE entities ADD
COLUMN ...` blows up if the entities table doesn't exist yet.

**The fix:** guard ALTER TABLE with a table-existence check:

```python
cursor.execute("PRAGMA table_info(entities)")
entity_cols = {row[1] for row in cursor.fetchall()}
if entity_cols and "event_signature" not in entity_cols:
    cursor.execute("ALTER TABLE entities ADD COLUMN event_signature TEXT")
```

`entity_cols and ...` — only attempts the ALTER when the table
actually exists.

## Detection / Entity persistence: schema fields fan out everywhere

When you add a new field to Detection or Entity, you MUST update:

1. The Pydantic model
2. The `CREATE TABLE` statement (for fresh DBs)
3. `ensure_schema_updates()` (for existing DBs — additive ALTER TABLE)
4. `DetectionDB.save()` / `save_entity()` (INSERT statements)
5. `_row_to_detection()` / `_row_to_entity()` (SELECT side)
6. Round-trip tests

A missed step is a silent persistence bug. See
[`31-recipes-schema-changes.md`](31-recipes-schema-changes.md).

## Pydantic v2 extra='ignore' is the default

If you add a field to a model and old code reads new data, the old
code's Pydantic model has `extra='ignore'` by default (not `'forbid'`).
Extra fields are dropped silently. This is intentional for our
forward-compat story but can hide bugs. Test round-trips explicitly.

## The PR-number question

The PR number for this branch's work is just the next available number
in the repo. There is ONE PR per feature branch. Past agents have
mistakenly thought "PR #2" implied "PR #1 was for the same work" and
spent time looking for it. Look at the PR's branch name; that's the
truth.

## `Cannot update time stamp of directory 'src/<pkg>.egg-info'` mid-deploy

**Symptom:** `make update-services` (or any component `make install`)
dies partway through an upgrade with:

```
error: Cannot update time stamp of directory 'src/orpheus_agent_audio_events.egg-info'
```

**Cause:** every component's `make install` does an editable install
(`-e .[dev]` in its requirements.txt), and setuptools regenerates
`src/<pkg>.egg-info/` in the git working tree each time. A past sudo'd
run (from before the "don't run `make install` as root" guards) can
leave that directory root-owned; the later non-sudo reinstall can't
touch it and setuptools fails with the cryptic timestamp error above.

**The fix in this repo (automatic):** `make/common_python.mk` hooks a
`preclean-egg-info` prerequisite onto every component's `install`
target. It removes `*.egg-info` dirs immediately before the editable
install (setuptools regenerates them, so this is always safe), and if
one can't be removed (foreign-owned, no sudo), it fails fast with the
exact one-liner instead of the timestamp error.

**Manual one-liner** (from the component directory):

```bash
sudo rm -rf src/*.egg-info
```

## pip "WARNING: Ignoring invalid distribution -..." is debris, not damage

**Symptom:** installs/updates print lines like:

```
WARNING: Ignoring invalid distribution -umpy (.../venv/lib/python3.9/site-packages)
```

**Cause:** an interrupted or killed pip run. While upgrading a package,
pip renames the old version's folder to `~name` inside site-packages
and deletes it at the end; if the process dies in between, the `~name`
folder is stranded. pip then warns about it on every later invocation
(the leading `~` is displayed as `-` in the warning). Folders starting
with `-` or `~` in site-packages are never legitimate.

**Harmless to runtime** — the real, valid distribution is still
installed and imports fine. But the debris hides real warnings, so
delete it:

```bash
# from the component dir; prefix with sudo for the /opt/orpheus venvs
find venv/lib/python*/site-packages -maxdepth 1 -name '~*' -exec rm -rf {} +
```

If a warning names a package you actually need and imports break,
reinstall it afterwards (`make install` / `make reinstall`).

## When you add to this file

If you hit a weird-library-behavior problem and figure it out, write
it down here. The next agent will save a session's worth of effort.
